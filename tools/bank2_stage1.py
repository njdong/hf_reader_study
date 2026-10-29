"""Bank v2 stage 1 (mechanical): verbatim spans per case, with sha256 and a recomputable locator.

For each case in data/case_selection.csv:
  - dataset spans (kind "dataset") from mimic-iv-ext-cardiac-disease-1.0.0/: the discharge-summary
    columns (HPI, chief complaint, exam, invasions, each imaging/echo/ECG snippet, machine reads),
    each coded diagnosis, each first lab, each procedure, a deterministic microbiology summary;
  - markdown spans (kind "markdown") from data/cases_mas_review_100.md with 1-based line locators:
    CHART header/bullets/orders-table rows, TRUTH lines, each TRUTH new prescription (char-offset
    span), and each "### MAS —" block as one span;
  - the parse_mas.py parse of the case (mas_parsed / truth_parsed) for item counting.

Writes data/bank_v2/01_verbatim/C*.json, a task sheet data/bank_v2/02_extracted/_tasks/C*.md
(paths and span ids only), and manifest entries. Also regenerates data/mas_outputs.json is left to
parse_mas.py (run separately; it is mechanical).

Example
  python tools/bank2_stage1.py
"""

import ast
import csv
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from bank2_lib import ROOT, BANK, DATASET, MAS_MD, load_selection, manifest_update, sha256_text, sha256_file  # noqa: E402
import parse_mas  # noqa: E402

csv.field_size_limit(10 ** 9)

OUT_DIR = os.path.join(BANK, "01_verbatim")
TASK_DIR = os.path.join(BANK, "02_extracted", "_tasks")

DS_FILE = "heart_diagnoses.csv"
DS_TEXT_COLS = [("hpi", "HPI"), ("chief_complaint", "chief_complaint"),
                ("physical_exam", "physical_exam"), ("invasions", "invasions")]
DS_LIST_COLS = [("xray", "X-ray"), ("ct", "CT"), ("ultrasound", "Ultrasound"),
                ("cath", "CATH"), ("ecg", "ECG"), ("mri", "MRI")]

MAS_SECTIONS = {
    "MAS — PRIMARY CALL": "primary_call",
    "MAS — CARDIOLOGY CATEGORIES": "categories",
    "MAS — RANKED ICDs": "ranked_icds",
    "MAS — PRESCRIPTIONS": "prescriptions",
    "MAS — NEXT TESTS / ACTIONS": "next_tests",
    "MAS — COMPLETENESS AUDIT": "completeness_audit",
    "MAS — SAFETY ACTIONS": "safety_actions",
    "MAS — GUIDELINES CITED": "guidelines",
}
RX_RE = re.compile(r"`([^`]+)` \[([^\]]*)\]")


def slug(s):
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", s.lower())).strip("_")


def span(sid, kind, file, locator, text):
    return {"id": sid, "kind": kind, "file": file, "locator": locator,
            "text": text, "sha256": sha256_text(text)}


# ---------- dataset ----------

def read_csv_rows(name):
    with open(os.path.join(DATASET, name), newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def norm_hadm(v):
    return (v or "").split(".")[0].strip()


def collect_dataset(hadms):
    """One pass per file; returns dicts keyed by hadm."""
    ds, dx, labs, procs, micro = {}, {}, {}, {}, {}
    for row in read_csv_rows(DS_FILE):
        h = row["hadm_id"]
        if h in hadms and h not in ds and row.get("note_type") == "DS":
            ds[h] = row
    for row in read_csv_rows("heart_diagnoses_all_true.csv"):
        h = row["hadm_id"]
        if h in hadms:
            dx.setdefault(h, []).append(row)
    for row in read_csv_rows("heart_labevents_first_lab.csv"):
        h = norm_hadm(row["hadm_id"])
        if h in hadms:
            labs.setdefault(h, []).append(row)
    for row in read_csv_rows("heart_procedures.csv"):
        h = row["hadm_id"]
        if h in hadms:
            procs.setdefault(h, []).append(row)
    for row in read_csv_rows("heart_microbiologyevents_first_micro.csv"):
        h = norm_hadm(row.get("hadm_id"))
        if h in hadms:
            micro.setdefault(h, []).append(row)
    return ds, dx, labs, procs, micro


def dataset_spans(hadm, ds_row, dx_rows, lab_rows, proc_rows, micro_rows, warn):
    spans = []
    if not ds_row:
        warn(f"hadm {hadm}: no DS row in {DS_FILE}")
    else:
        note_id = ds_row["note_id"]
        for sid, col in DS_TEXT_COLS:
            v = ds_row.get(col) or ""
            if v.strip():
                spans.append(span(f"ds:{sid}", "dataset", DS_FILE,
                                  {"note_id": note_id, "column": col}, v))
        for sid, col in DS_LIST_COLS:
            v = (ds_row.get(col) or "").strip()
            if not v or v == "[]":
                continue
            try:
                items = ast.literal_eval(v)
                assert isinstance(items, list)
            except Exception:
                warn(f"hadm {hadm}: column {col} not a literal list; kept raw")
                items = None
            if items is None:
                spans.append(span(f"ds:{sid}:raw", "dataset", DS_FILE,
                                  {"note_id": note_id, "column": col, "raw": True}, v))
            else:
                for i, item in enumerate(items):
                    t = str(item)
                    if t.strip():
                        spans.append(span(f"ds:{sid}:{i}", "dataset", DS_FILE,
                                          {"note_id": note_id, "column": col, "index": i}, t))
        v = ds_row.get("reports") or ""
        if v.strip():
            spans.append(span("ds:reports", "dataset", DS_FILE,
                              {"note_id": note_id, "column": "reports"}, v))
    seen_dx = {}
    for row in sorted(dx_rows, key=lambda r: int(r["seq_num"])):
        t = f"{row['seq_num']}. {row['icd_code']} — {row['long_title']}"
        seen_dx[row["seq_num"]] = seen_dx.get(row["seq_num"], 0) + 1
        sid = f"dx:{row['seq_num']}" + (f":{seen_dx[row['seq_num']]}" if seen_dx[row["seq_num"]] > 1 else "")
        spans.append(span(sid, "dataset", "heart_diagnoses_all_true.csv",
                          {"hadm_id": hadm, "seq_num": row["seq_num"], "icd_code": row["icd_code"]}, t))
    seen = {}
    for row in lab_rows:
        val = (row.get("value") or "").strip() or (row.get("valuenum") or "").strip()
        if not val:
            continue
        label = row["label"]
        s = slug(label)
        seen[s] = seen.get(s, 0) + 1
        sid = f"lab:{s}" + (f":{seen[s]}" if seen[s] > 1 else "")
        uom = (row.get("valueuom") or "").strip()
        flag = (row.get("flag") or "").strip()
        t = f"{label}: {val}" + (f" {uom}" if uom else "") + (" [abnormal]" if flag == "abnormal" else "") \
            + f" @ {row['charttime']}"
        spans.append(span(sid, "dataset", "heart_labevents_first_lab.csv",
                          {"hadm_id": hadm, "label": label, "charttime": row["charttime"]}, t))
    for row in sorted(proc_rows, key=lambda r: int(r["seq_num"])):
        t = f"{row['icd_code']} — {row['long_title']} — {row['chartdate']}"
        spans.append(span(f"proc:{row['seq_num']}", "dataset", "heart_procedures.csv",
                          {"hadm_id": hadm, "seq_num": row["seq_num"]}, t))
    uniq = []
    for row in micro_rows:
        key = (row.get("chartdate") or "", row.get("spec_type_desc") or "",
               row.get("test_name") or "", row.get("org_name") or "")
        if key not in uniq:
            uniq.append(key)
    for i, (date, spec, test, org) in enumerate(uniq, 1):
        t = f"{date} {spec} — {test}: {org or 'no growth reported'}"
        spans.append(span(f"micro:{i}", "dataset", "heart_microbiologyevents_first_micro.csv",
                          {"hadm_id": hadm, "index": i,
                           "rule": "unique (chartdate, spec_type_desc, test_name, org_name) in file order"}, t))
    return spans


# ---------- markdown ----------

def md_line_span(sid, lines, a, b):
    """Span over 0-based line indices [a, b] inclusive; locator is 1-based."""
    text = "\n".join(lines[a:b + 1])
    return span(sid, "markdown", os.path.relpath(MAS_MD, ROOT), {"lines": [a + 1, b + 1]}, text)


def md_blocks(lines):
    """{case_number: (header_idx, end_idx)}; end_idx = last line of the block (0-based)."""
    starts = [(i, m.group(1)) for i, l in enumerate(lines) if (m := parse_mas.CASE_RE.match(l))]
    out = {}
    for n, (i, case) in enumerate(starts):
        end = (starts[n + 1][0] - 1) if n + 1 < len(starts) else len(lines) - 1
        out[case] = (i, end)
    return out


def sections(lines, a, b):
    """[(title, header_idx, end_idx)] for '### ' sections between a and b (0-based, inclusive)."""
    heads = [(i, re.sub(r"\s*\(\d+ \w+\)$", "", m.group(1)))
             for i in range(a, b + 1) if (m := parse_mas.SECTION_RE.match(lines[i]))]
    out = []
    for n, (i, title) in enumerate(heads):
        end = (heads[n + 1][0] - 1) if n + 1 < len(heads) else b
        while end > i and not lines[end].strip():
            end -= 1
        out.append((title, i, end))
    return out


def markdown_spans(lines, a, b, warn):
    spans = []
    secs = sections(lines, a, b)
    sec = {t: (i, e) for t, i, e in secs}

    # CHART: header bullet, snapshot bullets, orders-table rows
    if "CHART" in sec:
        ca, cb = sec["CHART"]
        in_code, meds_at, n_med = False, None, 0
        for i in range(ca + 1, cb + 1):
            l = lines[i]
            if l.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            if re.match(r"^- \*\*\d+[MF]\*\*", l):
                spans.append(md_line_span("md:chart:header", lines, i, i))
            elif m := re.match(r"^- \*\*([^*]+):\*\*", l):
                spans.append(md_line_span(f"md:chart:{slug(m.group(1))}", lines, i, i))
            elif l.startswith("**Home medications"):
                meds_at = i
            elif meds_at is not None and l.startswith("| ") and not re.match(r"^\|[-| ]+\|$", l):
                if l.split("|")[1].strip() != "#":
                    n_med += 1
                    spans.append(md_line_span(f"md:chart:med:{n_med}", lines, i, i))
            elif meds_at is not None and l.startswith("**"):
                meds_at = None
    else:
        warn("no CHART section")

    # TRUTH (coder)
    if "TRUTH (coder)" in sec:
        ta, tb = sec["TRUTH (coder)"]
        for i in range(ta + 1, tb + 1):
            for prefix, sid in (("- **Primary:**", "md:truth:primary"),
                                ("- **All ICDs", "md:truth:all_icds"),
                                ("- **HF type:**", "md:truth:hf_type")):
                if lines[i].startswith(prefix):
                    spans.append(md_line_span(sid, lines, i, i))
    else:
        warn("no TRUTH (coder) section")

    # TRUTH PRESCRIPTIONS: each `drug` [atc] item, char-offset locator
    t = next((k for k in sec if k.startswith("TRUTH PRESCRIPTIONS")), None)
    n_claimed = None
    if t:
        ta, tb = sec[t]
        in_list = False
        n_rx = 0
        for i in range(ta + 1, tb + 1):
            l = lines[i]
            if l.strip().startswith("**Truth = newly prescribed"):
                in_list = True
                if m := re.search(r"\(n=(\d+)\)", l):
                    n_claimed = int(m.group(1))
                continue
            if in_list and l.strip().startswith("**"):
                in_list = False
            if in_list:
                for m in RX_RE.finditer(l):
                    n_rx += 1
                    spans.append(span(f"md:truth:rx:{n_rx}", "markdown", os.path.relpath(MAS_MD, ROOT),
                                      {"line": i + 1, "col": [m.start(), m.end()]}, m.group(0)))
        if n_claimed is not None and n_rx != n_claimed:
            warn(f"TRUTH rx: {n_rx} parsed, header says {n_claimed}")

    # each MAS block as one span
    for title, sid in MAS_SECTIONS.items():
        if title in sec:
            i, e = sec[title]
            spans.append(md_line_span(f"md:mas:{sid}", lines, i, e))
    if "MAS — PRIMARY CALL" not in sec:
        warn("no MAS — PRIMARY CALL section")
    return spans


# ---------- task sheets ----------

def task_sheet(case_id, spans):
    groups = {}
    for s in spans:
        g = s["id"].split(":")[0] if not s["id"].startswith("md:") else ":".join(s["id"].split(":")[:2])
        groups.setdefault(g, []).append(s["id"])
    lines = [f"# Stage-2 task — {case_id}", "",
             "Read (paths relative to the repo root):",
             "- data/bank_v2/00_template/TEMPLATE.md",
             f"- data/bank_v2/01_verbatim/{case_id}.json", "",
             f"Write: data/bank_v2/02_extracted/{case_id}.json (schema in TEMPLATE.md)", "",
             "Span ids available in this case:"]
    for g in sorted(groups):
        ids = groups[g]
        shown = ", ".join(ids if len(ids) <= 12 else ids[:12] + [f"… ({len(ids)} total)"])
        lines.append(f"- {g}: {shown}")
    return "\n".join(lines) + "\n"


def main():
    sel = load_selection()
    hadms = {r["hadm"] for r in sel}
    ds, dx, labs, procs, micro = collect_dataset(hadms)
    with open(MAS_MD, encoding="utf-8") as f:
        md_lines = f.read().splitlines()
    blocks = md_blocks(md_lines)

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(TASK_DIR, exist_ok=True)
    manifest_entries = {}
    all_warns = []
    for r in sel:
        case, hadm = r["case"], r["hadm"]
        case_id = f"C{case}"
        warns = []
        warn = lambda msg: warns.append(f"{case_id}: {msg}")  # noqa: E731
        spans = dataset_spans(hadm, ds.get(hadm), dx.get(hadm, []), labs.get(hadm, []),
                              procs.get(hadm, []), micro.get(hadm, []), warn)
        if case not in blocks:
            warn("case not found in markdown")
            mas_parsed = truth_parsed = None
        else:
            a, b = blocks[case]
            spans += markdown_spans(md_lines, a, b, warn)
            header = parse_mas.CASE_RE.match(md_lines[a])
            parsed = parse_mas.parse_case(header, md_lines[a + 1:b + 1])
            mas_parsed, truth_parsed = parsed["mas"], parsed["truth"]
        ids = [s["id"] for s in spans]
        assert len(ids) == len(set(ids)), f"{case_id}: duplicate span ids"
        rec = {"case_id": case_id, "pid": r["pid"], "hadm": hadm, "cohort": r["cohort"],
               "generated": dt.datetime.now().isoformat(timespec="seconds"),
               "source_files": {"markdown": os.path.relpath(MAS_MD, ROOT),
                               "markdown_sha256": None,  # filled below once
                               "dataset_dir": os.path.relpath(DATASET, ROOT)},
               "warnings": warns, "sources": spans,
               "mas_parsed": mas_parsed, "truth_parsed": truth_parsed}
        all_warns += warns
        out = os.path.join(OUT_DIR, f"{case_id}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1, ensure_ascii=False)
        with open(os.path.join(TASK_DIR, f"{case_id}.md"), "w", encoding="utf-8") as f:
            f.write(task_sheet(case_id, spans))
        manifest_entries[os.path.relpath(out, ROOT)] = {"stage": "01_verbatim", "case": case_id}
        print(f"{case_id}: {len(spans)} spans"
              + (f"  WARN: {'; '.join(warns)}" if warns else ""))

    md_sha = sha256_file(MAS_MD)
    for r in sel:
        p = os.path.join(OUT_DIR, f"C{r['case']}.json")
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
        rec["source_files"]["markdown_sha256"] = md_sha
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1, ensure_ascii=False)

    manifest_update(manifest_entries, {"kind": "tool", "name": "bank2_stage1.py"})
    print(f"{len(sel)} cases -> {os.path.relpath(OUT_DIR, ROOT)}  ({len(all_warns)} warnings)")


if __name__ == "__main__":
    main()
