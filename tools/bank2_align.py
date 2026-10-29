"""Bank v2 stage 3 (mechanical): apply data/bank_v2/00_template/ALIGN_RULES.md to stage-2 output.

Reads  data/bank_v2/02_extracted/C*.json
Writes data/bank_v2/03_aligned/C*.json   (stem passed through; mas/note as {domain: [text]}; edits)
       data/bank_v2/changes/C*.md        (stage1->2 record from the doer's from/kept/dropped fields,
                                          stage2->3 before/after per rule)

Deterministic: same input -> same output. Budget violations and unknown labels are reported and
fail the run (exit 1); the fix belongs in stage 2, never here.

Example
  python tools/bank2_align.py
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from bank2_lib import ROOT, BANK, manifest_update  # noqa: E402

IN_DIR = os.path.join(BANK, "02_extracted")
OUT_DIR = os.path.join(BANK, "03_aligned")
CHANGES_DIR = os.path.join(BANK, "changes")

DOMAINS = ["dx", "causes", "acute", "gdmt", "monitor", "dispo"]

VOCAB = ["DIAGNOSIS", "HF CHARACTERIZATION", "CONTRIBUTORS", "COMPLICATIONS", "COMORBIDITIES",
         "ACTIVE PROBLEMS", "HISTORY", "START", "STOP", "CONTINUE", "HOLD", "TITRATE UP",
         "TITRATE DOWN", "PERFORM", "OBTAIN", "MONITOR", "SAFETY", "REQUEST", "CONSIDER",
         "TRANSITION", "REFER", "CONSULT", "ADMIT", "TRANSFER", "FOLLOW-UP"]

# Rule 2: record tense -> plan tense (note column)
LABEL_MAP = {
    "GIVEN": "START", "PERFORMED": "PERFORM", "COMPLETED": "OBTAIN", "NEWLY PRESCRIBED": "START",
    "CONTINUED": "CONTINUE", "ADMITTED": "ADMIT", "TRANSFERRED": "TRANSFER",
    "MONITORING PLAN": "MONITOR", "FOLLOW-UP / DISCHARGE CRITERIA": "FOLLOW-UP",
    "OTHER CODED DIAGNOSES": "COMORBIDITIES",
}

LINE_RE = re.compile(r"^([A-Z][A-Z0-9 /\-]*?)(?:\s*\(([^)]*)\))?\s*:\s*(.*)$", re.S)
NOT_DOCUMENTED_RE = re.compile(r"^not documented( in the (record|narrative))?\.?$", re.I)

# Rule 4: provenance phrases (pattern, replacement)
STRIP = [
    (re.compile(r"\s*\(second-hand\)", re.I), ""),
    (re.compile(r"\bsecond-hand\b[,;]?\s*", re.I), ""),
    (re.compile(r"\b(in|from) the supplied record\b", re.I), ""),
    (re.compile(r"\b(in|from) the record\b", re.I), ""),
    (re.compile(r"\s*\(whole admission\)", re.I), ""),
    (re.compile(r"\bcoded\b\s+(?=primary|diagnos)", re.I), ""),
    (re.compile(r"\brecorded diagnos(is|es)\b", re.I), lambda m: "diagnos" + m.group(1)),
    (re.compile(r"\bprescription table\b[,;]?\s*", re.I), ""),
    (re.compile(r"\bsafety actions\b", re.I), "safety"),
    (re.compile(r"\bsupplied\b\s*", re.I), ""),
    (re.compile(r"\s*Contingency:\s*", re.I), " — "),
    (re.compile(r"\bnot_applicable\b", re.I), ""),
]
MARKUP = re.compile(r"[`|]|\*\*")


def tidy(body):
    body = MARKUP.sub("", body)
    body = re.sub(r"\s+—\s+", " — ", body.replace(" -- ", " — ").replace(" – ", " — "))
    body = re.sub(r"\(\s*\)", "", body)                 # emptied parentheses
    body = re.sub(r"\s+([,.;:])", r"\1", body)
    body = re.sub(r",\s*,", ",", body)
    body = re.sub(r"\s+", " ", body).strip()
    body = re.sub(r"[,;—\s]+$", "", body).strip()
    if body and not body.endswith("."):
        body += "."
    return body


def align_line(text, column):
    """Returns (new_text, [(rule, before, after)]) or raises ValueError for an unknown label."""
    m = LINE_RE.match(text.strip())
    if not m:
        raise ValueError(f"no LABEL: prefix in {text!r}")
    label, paren, body = m.group(1).strip(), m.group(2), m.group(3).strip()
    edits = []
    orig = text.strip()

    if column == "note" and label in LABEL_MAP:
        new_label = LABEL_MAP[label]
        edits.append(("rule2:label-map", label, new_label))
        label = new_label
        paren = None                                     # "(second-hand)", "(whole admission)" die with the map
    if label not in VOCAB:
        raise ValueError(f"label {label!r} not in vocabulary ({orig[:60]!r})")

    if NOT_DOCUMENTED_RE.match(body):
        out = f"{label}: No recommendation."
        if out != orig:
            edits.append(("rule3:not-documented", orig, out))
        return out, edits

    if paren:
        body = f"({paren}) {body}"                       # keep a non-provenance parenthetical
    before_strip = body
    for pat, rep in STRIP:
        body = pat.sub(rep, body)
    body = tidy(body)
    if not body or body == ".":
        out = f"{label}: No recommendation."
        edits.append(("rule4:stripped-empty", orig, out))
        return out, edits
    if body != tidy(before_strip):
        edits.append(("rule4:strip-provenance", before_strip, body))
    out = f"{label}: {body}"
    if out != orig and not edits:
        edits.append(("rule5:tidy", orig, out))
    return out, edits


def words(col):
    return sum(len(t.split()) for lines in col.values() for t in lines)


def align_case(rec):
    out = {"case_id": rec["case_id"], "stem": rec["stem"], "mas": {}, "note": {},
           "edits": [], "budget": {}}
    problems = []
    for column in ("mas", "note"):
        for dom in DOMAINS:
            lines, seen = [], set()
            for item in rec[column].get(dom, []):
                try:
                    new, edits = align_line(item["text"], column)
                except ValueError as e:
                    problems.append(f"{column}/{dom}: {e}")
                    continue
                for rule, before, after in edits:
                    out["edits"].append({"column": column, "domain": dom,
                                         "before": before, "after": after, "rule": rule})
                if new in seen:
                    out["edits"].append({"column": column, "domain": dom, "before": new,
                                         "after": None, "rule": "rule5:dedupe"})
                    continue
                seen.add(new)
                lines.append(new)
            out[column][dom] = lines
    mas_w, note_w = words(out["mas"]), words(out["note"])
    ok = 150 <= mas_w <= 280 and note_w <= 150
    out["budget"] = {"mas_words": mas_w, "note_words": note_w, "ok": ok}
    if not ok:
        problems.append(f"budget: mas {mas_w} (need 150-280), note {note_w} (need <=150)")
    return out, problems


def change_record(rec, aligned):
    L = [f"# Changes — {rec['case_id']}", "", "## Stage 1 → 2 (doer extraction; per item: source ids, kept/dropped conditions)", ""]
    for column in ("mas", "note"):
        for dom in DOMAINS:
            for item in rec[column].get(dom, []):
                L.append(f"- [{column}/{dom}] \"{item['text']}\"  ← from: {', '.join(item.get('from', []))}")
                if item.get("kept_conditions"):
                    L.append(f"  - kept: {'; '.join(item['kept_conditions'])}")
                if item.get("dropped"):
                    L.append(f"  - dropped: {'; '.join(item['dropped'])}")
    L += ["", "## Stage 2 → 3 (mechanical alignment; rule: before → after)", ""]
    if not aligned["edits"]:
        L.append("(no edits)")
    for e in aligned["edits"]:
        if e["rule"] == "rule5:dedupe":
            L.append(f"- [{e['column']}/{e['domain']}] {e['rule']}: dropped duplicate \"{e['before']}\"")
        else:
            L.append(f"- [{e['column']}/{e['domain']}] {e['rule']}:\n  - before: {e['before']}\n  - after:  {e['after']}")
    b = aligned["budget"]
    L += ["", f"## Budget: mas {b['mas_words']} words, note {b['note_words']} words — {'OK' if b['ok'] else 'VIOLATION'}", ""]
    return "\n".join(L)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(CHANGES_DIR, exist_ok=True)
    files = sorted(f for f in os.listdir(IN_DIR) if f.endswith(".json"))
    if not files:
        sys.exit("no stage-2 files in " + IN_DIR)
    entries, failures = {}, []
    for fn in files:
        with open(os.path.join(IN_DIR, fn), encoding="utf-8") as f:
            rec = json.load(f)
        aligned, problems = align_case(rec)
        out = os.path.join(OUT_DIR, fn)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(aligned, f, indent=1, ensure_ascii=False)
        cp = os.path.join(CHANGES_DIR, fn.replace(".json", ".md"))
        with open(cp, "w", encoding="utf-8") as f:
            f.write(change_record(rec, aligned))
        entries[os.path.relpath(out, ROOT)] = {"stage": "03_aligned", "case": rec["case_id"]}
        b = aligned["budget"]
        status = "OK " if not problems else "FAIL"
        print(f"{rec['case_id']}: {status} mas {b['mas_words']}w note {b['note_words']}w, {len(aligned['edits'])} edits"
              + ("".join(f"\n    ! {p}" for p in problems)))
        if problems:
            failures.append(rec["case_id"])
    manifest_update(entries, {"kind": "tool", "name": "bank2_align.py"})
    print(f"{len(files)} cases -> {os.path.relpath(OUT_DIR, ROOT)}")
    if failures:
        sys.exit(f"ALIGN FAILED for {', '.join(failures)} — fix in stage 2 and rerun")


if __name__ == "__main__":
    main()
