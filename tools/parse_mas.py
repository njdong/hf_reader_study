"""Parse the MAS cardiologist-review markdown into one structured JSON record per case.

Input:  data/cases_mas_review_100.md  (multi-agent system run, one "## Case NNN" block per case)
Output: data/mas_outputs.json
  {
    "source": "...", "n_cases": 100,
    "cases": {
      "006": {
        "case": "006", "cohort": "I21_MI", "pid": "12200430", "hadm": "27518127",
        "chart":  {age_sex, admission, admit_type, snapshot{...}, input_meds[...]},   # what the MAS received
        "truth":  {primary_icd, primary_dx, all_icds[], hf_type, gdmt_on[], gdmt_missing[],
                   new_prescriptions[], drug_concordance{...}, class_concordance{...}},
        "mas":    {primary{dx, confidence, phenotype, ...}, categories{pred, truth}, ranked_icds[],
                   prescriptions[], next_tests[], completeness_audit{...}, safety_actions[],
                   safety_summary, guidelines[]},
        "auto_score": {...}
      }, ...
    }
  }
chart.narrative holds the verbatim HPI, physical exam, echo report, ECG and imaging text the system received.

Examples
  python tools/parse_mas.py
  python tools/parse_mas.py data/cases_mas_review_100.md -o data/mas_outputs.json
"""

import argparse
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CASE_RE = re.compile(r"^## Case (\d+) — pid `(\d+)` \| hadm `(\d+)` \((\w+)\)\s*$")
SECTION_RE = re.compile(r"^### (.+?)\s*$")
CATEGORY_RE = re.compile(r"(✓|✗)(\w+)")


def split_cases(text):
    """Yield (header_match, lines) for each '## Case' block."""
    cur, lines = None, []
    for line in text.splitlines():
        m = CASE_RE.match(line)
        if m:
            if cur:
                yield cur, lines
            cur, lines = m, []
        elif cur:
            lines.append(line)
    if cur:
        yield cur, lines


def split_sections(lines):
    """Map section title -> list of lines. Prescriptions/ICD titles carry counts, so key on the stem."""
    out, key = {}, None
    for line in lines:
        m = SECTION_RE.match(line)
        if m:
            key = re.sub(r"\s*\(\d+ \w+\)$", "", m.group(1))
            out[key] = []
        elif key:
            out[key].append(line)
    return out


def table_rows(lines):
    """Data rows of a markdown table (skips header and separator rows)."""
    rows = []
    for line in lines:
        if not line.startswith("| ") or re.match(r"^\|[-| ]+\|$", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0] == "#":
            continue
        rows.append(cells)
    return rows


def none_if_blank(s):
    s = s.strip()
    return None if s in ("", "—", "None") or s.startswith("None ") else s


def strip_code(s):
    return s.strip().strip("`")


def parse_chart(lines):
    chart = {"snapshot": {}, "input_meds": []}
    m = re.match(r"^- \*\*(\d+[MF])\*\* \| admission: (\S+) → (\S+) \| type: (.+)$", lines[0]) if lines else None
    if m:
        chart.update(age_sex=m.group(1), admission=[m.group(2), m.group(3)], admit_type=m.group(4).strip())
    # Bullet fields outside code blocks: Labs (snapshot), Echo numerics, LV wall motion, Valvular findings
    in_code = False
    for line in lines:
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        b = re.match(r"^- \*\*([^*]+):\*\* (.+)$", line)
        if b:
            chart["snapshot"][b.group(1)] = b.group(2).strip()
    # Narrative blocks: a bold label followed by one or more fenced code blocks
    chart["narrative"] = {}
    labels = {"Chief complaint / HPI": "hpi", "Physical exam": "exam", "Echo raw report": "echo_report",
              "ECG findings": "ecg", "Imaging": "imaging"}
    key, buf, in_code = None, [], False
    for line in lines + ["**end**"]:
        m = re.match(r"^\*\*([^*]+?)(?: \(\d+ studies\))?:?\*\*\s*$", line)
        if m and not in_code:
            if key:
                chart["narrative"][key] = "\n".join(buf).strip()
            key, buf = labels.get(m.group(1)), []
            continue
        if line.startswith("```"):
            in_code = not in_code
            continue
        if key and not line.startswith("- **"):
            buf.append(line)
    # Home medications table = orders started in the first 12 h, i.e. what the MAS was given
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith("**Home medications"))
    except StopIteration:
        return chart
    block = []
    for line in lines[start + 1:]:
        if line.startswith("**") or line.startswith("### "):
            break
        block.append(line)
    for r in table_rows(block):
        chart["input_meds"].append({
            "medication": r[1], "dose": none_if_blank(r[2]), "route": none_if_blank(r[3]),
            "frequency": none_if_blank(r[4]), "indication": none_if_blank(r[5]),
        })
    return chart


def parse_truth(lines):
    t = {}
    for line in lines:
        if m := re.match(r"^- \*\*Primary:\*\* `([^`]+)` — \*(.+)\*$", line):
            t["primary_icd"], t["primary_dx"] = m.group(1), m.group(2)
        elif m := re.match(r"^- \*\*All ICDs \(\d+\):\*\* (.+)$", line):
            t["all_icds"] = [c.strip() for c in m.group(1).split("·")]
        elif m := re.match(r"^- \*\*HF type:\*\* (.+?) \| GDMT pillars on: (.*?) \| missing: (.*)$", line):
            t["hf_type"] = m.group(1).strip()
            t["gdmt_on"] = [p.strip() for p in m.group(2).split(",") if p.strip() and p.strip() != "—"]
            t["gdmt_missing"] = [p.strip() for p in m.group(3).split(",") if p.strip() and p.strip() != "—"]
    return t


def parse_truth_rx(lines):
    """Clinician-administered new prescriptions + MAS concordance against them."""
    out = {"new_prescriptions": [], "drug_concordance": {}, "class_concordance": {}}
    mode = None
    for line in lines:
        s = line.strip()
        if s.startswith("**Truth = newly prescribed"):
            mode = "truth"
        elif s.startswith("**Drug-level concordance"):
            mode = "drug"
        elif s.startswith("**Class-level concordance"):
            mode = "class"
        elif mode == "truth" and s:
            for item in s.split(" · "):
                m = re.match(r"^`([^`]+)` \[(.*)\]$", item.strip())
                if m:
                    atc = [a.strip() for a in m.group(2).split(",") if a.strip() not in ("", "—")]
                    out["new_prescriptions"].append({"drug": m.group(1), "atc": atc})
        elif mode in ("drug", "class") and s.startswith("- "):
            target = out["drug_concordance" if mode == "drug" else "class_concordance"]
            body = s[2:]
            if body.startswith("F1"):
                for kv in body.split("|"):
                    k, _, v = kv.strip().partition(" = ")
                    target[k.strip().replace("-", "_").replace(" ", "_")] = float(v)
            else:
                m = re.match(r"^(✓|✗) (.+?) \((?:[^)]*?)(\d+)\):\s*(.*)$", body)
                if m:
                    label = {"Pred ∩ Truth": "matched", "Truth − Pred": "missed_by_mas",
                             "Pred − Truth": "added_by_mas"}
                    key = next((v for k, v in label.items() if m.group(2).startswith(k)), m.group(2))
                    target[key] = re.findall(r"`([^`]+)`", m.group(4))
    # A drug can appear twice in the truth list (two orders); keep order, drop exact repeats
    seen, uniq = set(), []
    for p in out["new_prescriptions"]:
        if p["drug"] not in seen:
            seen.add(p["drug"])
            uniq.append(p)
    out["new_prescriptions"] = uniq
    return out


def parse_primary(lines):
    p = {}
    for line in lines:
        if m := re.match(r"^- \*\*Dx:\*\* (.+?)\s+_\(confidence: ([^)]+)\)_\s*$", line):
            p["dx"], p["confidence"] = m.group(1).strip(), none_if_blank(m.group(2))
        elif m := re.match(r"^- \*\*Phenotype:\*\* `([^`]+)` _\((\w+)\)_\s+\|\s+\*\*Etiology:\*\* `([^`]+)` _\((\w+)\)_", line):
            p["phenotype"], p["phenotype_confidence"] = m.group(1), m.group(2)
            p["etiology"], p["etiology_confidence"] = m.group(3), m.group(4)
    return p


def parse_categories(lines):
    out = {}
    for line in lines:
        for label, key in (("**Pred:**", "pred"), ("**Truth:**", "truth")):
            if line.startswith(label):
                out[key] = {name: mark == "✓" for mark, name in CATEGORY_RE.findall(line)}
    return out


def parse_ranked_icds(lines):
    return [{"rank": int(r[0]), "icd": strip_code(r[1]), "dx": r[2], "role": r[3], "match": r[4]}
            for r in table_rows(lines)]


def parse_prescriptions(lines):
    return [{
        "n": int(r[0]), "drug": r[1], "dose": none_if_blank(r[2]), "route": none_if_blank(r[3]),
        "freq": none_if_blank(r[4]), "indication": none_if_blank(r[5]), "action": r[6].strip(),
        "contingency": none_if_blank(r[7]),
    } for r in table_rows(lines)]


def parse_next_tests(lines):
    out = []
    for line in lines:
        if m := re.match(r"^- \*\*(.+?)\*\* \((\w+)\) — (.*)$", line):
            out.append({"test": m.group(1), "urgency": m.group(2), "rationale": m.group(3).strip()})
    return out


def parse_audit(lines):
    a = {"additions": [], "skipped": [], "summary": None}
    for line in lines:
        if m := re.match(r"^- \*\*GDMT additions \(\d+\):\*\* (.+)$", line):
            a["additions"] = [x.strip() for x in m.group(1).split(",")]
        elif m := re.match(r"^- \*\*Skipped \(contraindicated, n=\d+\):\*\* (.+)$", line):
            # The run often writes "None" for skipped classes; the class names are only in the summary
            a["skipped"] = [x.strip() for x in m.group(1).split(",") if x.strip() != "None"]
            a["n_skipped"] = int(re.search(r"n=(\d+)", line).group(1))
        elif m := re.match(r"^- _Summary:_ (.+)$", line):
            a["summary"] = m.group(1).strip()
    return a


def parse_safety(lines):
    actions, summary = [], None
    for line in lines:
        if m := re.match(r"^- \*\*([A-Z_]+)\*\* (.+?) \((major|moderate|minor|critical)\): (.*)$", line):
            actions.append({"type": m.group(1), "target": m.group(2).strip(), "severity": m.group(3),
                            "rationale": m.group(4).strip()})
        elif m := re.match(r"^- _Summary:_ (.+)$", line):
            summary = m.group(1).strip()
    return actions, summary


def parse_guidelines(lines):
    out = []
    for line in lines:
        if m := re.match(r"^- _(.+?)_ §(.*?) \(Class ([^/]*)/([^)]*)\) — (.*)$", line):
            out.append({"guideline": m.group(1), "section": m.group(2).strip(), "class": m.group(3),
                        "loe": m.group(4), "text": m.group(5).strip()})
    return out


def parse_auto_score(lines):
    s = {}
    for line in lines:
        if m := re.match(r"^- \*\*Primary ICD:\*\* (.+)$", line):
            s["primary_icd_match"] = m.group(1).strip()
        elif m := re.match(r"^- \*\*Top-10 prefix-3 F1:\*\* ([\d.]+) \| full-set prefix-3 F1: ([\d.]+)", line):
            s["top10_prefix3_f1"], s["fullset_prefix3_f1"] = float(m.group(1)), float(m.group(2))
        elif m := re.match(r"^- \*\*GDMT \(deterministic\) gap-detection F1:\*\* (.+)$", line):
            v = m.group(1).strip()
            s["gdmt_gap_f1"] = None if v == "—" else float(v)
        elif m := re.match(r"^- \*\*Tool calls:\*\* (\d+) \| latency ([\d.]+)s", line):
            s["tool_calls"], s["latency_s"] = int(m.group(1)), float(m.group(2))
    return s


def parse_case(header, lines):
    sec = split_sections(lines)
    safety, safety_summary = parse_safety(sec.get("MAS — SAFETY ACTIONS", []))
    truth = parse_truth(sec.get("TRUTH (coder)", []))
    truth.update(parse_truth_rx(sec.get("TRUTH PRESCRIPTIONS (clinician-administered) + concordance", [])))
    return {
        "case": header.group(1), "cohort": header.group(4), "pid": header.group(2), "hadm": header.group(3),
        "chart": parse_chart(sec.get("CHART", [])),
        "truth": truth,
        "mas": {
            "primary": parse_primary(sec.get("MAS — PRIMARY CALL", [])),
            "categories": parse_categories(sec.get("MAS — CARDIOLOGY CATEGORIES", [])),
            "ranked_icds": parse_ranked_icds(sec.get("MAS — RANKED ICDs", [])),
            "prescriptions": parse_prescriptions(sec.get("MAS — PRESCRIPTIONS", [])),
            "next_tests": parse_next_tests(sec.get("MAS — NEXT TESTS / ACTIONS", [])),
            "completeness_audit": parse_audit(sec.get("MAS — COMPLETENESS AUDIT", [])),
            "safety_actions": safety,
            "safety_summary": safety_summary,
            "guidelines": parse_guidelines(sec.get("MAS — GUIDELINES CITED", [])),
        },
        "auto_score": parse_auto_score(sec.get("AUTO-SCORE", [])),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src", nargs="?", default=os.path.join(ROOT, "data", "cases_mas_review_100.md"))
    ap.add_argument("-o", "--out", default=os.path.join(ROOT, "data", "mas_outputs.json"))
    args = ap.parse_args()

    with open(args.src, encoding="utf-8") as f:
        text = f.read()
    src_line = next((l for l in text.splitlines() if l.startswith("Source:")), "")
    cases = {}
    for header, lines in split_cases(text):
        c = parse_case(header, lines)
        cases[c["case"]] = c

    # Cross-check the parse against the counts printed in the section titles
    problems = []
    for m in re.finditer(r"^## Case (\d+).*?(?=^## Case |\Z)", text, re.S | re.M):
        n_rx = re.search(r"### MAS — PRESCRIPTIONS \((\d+) drugs\)", m.group(0))
        n_icd = re.search(r"### MAS — RANKED ICDs \((\d+) predicted\)", m.group(0))
        c = cases[m.group(1)]
        if n_rx and int(n_rx.group(1)) != len(c["mas"]["prescriptions"]):
            problems.append(f"{c['case']}: {len(c['mas']['prescriptions'])} prescriptions parsed, header says {n_rx.group(1)}")
        if n_icd and int(n_icd.group(1)) != len(c["mas"]["ranked_icds"]):
            problems.append(f"{c['case']}: {len(c['mas']['ranked_icds'])} ICDs parsed, header says {n_icd.group(1)}")
        if not c["mas"]["primary"].get("dx"):
            problems.append(f"{c['case']}: no primary call parsed")
    for p in problems:
        print("WARN", p)

    out = {"source": os.path.relpath(args.src, ROOT), "source_note": src_line.strip(),
           "n_cases": len(cases), "cases": cases}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"{len(cases)} cases -> {os.path.relpath(args.out, ROOT)} ({len(problems)} warnings)")


if __name__ == "__main__":
    main()
