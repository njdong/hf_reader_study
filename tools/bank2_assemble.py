"""Bank v2 assembly (mechanical): stage-3 files -> assembly/tables_v2.json -> docs/cases.json.

Also writes assembly/cases_v2.json (exact copy of the shipped docs/cases.json), assembly/build.log,
and manifest entries. Hard guards (fail the build):
  - every A/B label in the stage-3 vocabulary
  - no provenance phrase in any A/B cell (supplied|safety actions|prescription table|
    recorded diagnos|in the record|second-hand|Contingency:|not documented|not_applicable)
  - budgets: MAS 150-280 words, note <= 150
  - 30 cases, 6 domains each

Example
  python tools/bank2_assemble.py --version 2026-10-29
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from bank2_lib import ROOT, BANK, load_selection, manifest_update, manifest_set_version, sha256_file  # noqa: E402
from bank2_align import DOMAINS, VOCAB  # noqa: E402
from itemlib import DOMAINS as DOMAIN_LABELS  # noqa: E402

ALIGNED = os.path.join(BANK, "03_aligned")
ASSEMBLY = os.path.join(BANK, "assembly")

GUARD = re.compile(r"supplied|safety actions|prescription table|recorded diagnos|in the record|"
                   r"second-hand|Contingency:|not documented|not_applicable", re.I)
LABEL_RE = re.compile(r"^([A-Z][A-Z0-9 /\-]*?):\s")


def flatten_stem(stem):
    out = {}
    for k in ("presentation", "home_meds", "vitals", "labs"):
        v = stem.get(k) or {}
        out[k] = v.get("text", "") if isinstance(v, dict) else str(v)
    for k in ("exam", "echo", "ecg", "imaging", "cath"):
        out[k] = [x["text"] if isinstance(x, dict) else str(x) for x in (stem.get(k) or [])]
    return out


def check_case(cid, A, B, problems):
    for col, name in ((A, "A"), (B, "B")):
        for dom in DOMAINS:
            lines = col.get(dom, [])
            if not lines:
                problems.append(f"{cid} {name}/{dom}: empty domain")
            for t in lines:
                m = LABEL_RE.match(t)
                if not m or m.group(1).strip() not in VOCAB:
                    problems.append(f"{cid} {name}/{dom}: label outside vocabulary: {t[:60]!r}")
                if g := GUARD.search(t):
                    problems.append(f"{cid} {name}/{dom}: guard phrase {g.group(0)!r} in {t[:60]!r}")
    mas_w = sum(len(t.split()) for d in DOMAINS for t in A.get(d, []))
    note_w = sum(len(t.split()) for d in DOMAINS for t in B.get(d, []))
    if not 150 <= mas_w <= 280:
        problems.append(f"{cid}: MAS {mas_w} words (need 150-280)")
    if note_w > 150:
        problems.append(f"{cid}: note {note_w} words (need <=150)")
    return mas_w, note_w


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--version", default=dt.date.today().isoformat())
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "cases.json"))
    args = ap.parse_args()

    os.makedirs(ASSEMBLY, exist_ok=True)
    sel = load_selection()
    tables, cases, problems, log = {}, {}, [], []
    for r in sel:
        cid = f"C{r['case']}"
        path = os.path.join(ALIGNED, f"{cid}.json")
        if not os.path.exists(path):
            problems.append(f"{cid}: no stage-3 file")
            continue
        with open(path, encoding="utf-8") as f:
            a = json.load(f)
        stem = flatten_stem(a["stem"])
        A = {d: list(a["mas"].get(d, [])) for d in DOMAINS}
        B = {d: list(a["note"].get(d, [])) for d in DOMAINS}
        mas_w, note_w = check_case(cid, A, B, problems)
        tables[cid] = {"case_id": cid, "cohort": r["cohort"], "age_sex": r["age_sex"],
                       "stem": stem, "option_1": A, "option_2": B,
                       "words": {"option_1": mas_w, "option_2": note_w}}
        cases[cid] = {"case_id": cid, "cohort": r["cohort"], "age_sex": r["age_sex"], "stem": stem,
                      "A": {d: [{"text": t} for t in A[d]] for d in DOMAINS},
                      "B": {d: [{"text": t} for t in B[d]] for d in DOMAINS},
                      "source": "bank_v2: verbatim sources -> staged extraction -> aligned (see data/bank_v2/MANIFEST.json)"}
        log.append(f"{cid}: mas {mas_w}w note {note_w}w")
    if len(cases) != 30:
        problems.append(f"{len(cases)} cases assembled, expected 30")
    for p in problems:
        print("FAIL", p)
    if problems:
        sys.exit("assembly failed — fix stage 2/3 and rerun")

    tp = os.path.join(ASSEMBLY, "tables_v2.json")
    with open(tp, "w", encoding="utf-8") as f:
        json.dump({"version": args.version, "option_1": "MAS", "option_2": "clinical note",
                   "cases": tables}, f, indent=1, ensure_ascii=False)
    doc = {
        "study": "hf_reader_study", "version": args.version, "mode": "case",
        "systems": {"A": "multi-agent system (current run, first-12 h chart)",
                    "B": "clinical note (record: coded diagnoses, first-12 h orders, clinician prescriptions)"},
        "domains": [[k, v] for k, v in DOMAIN_LABELS.items()],
        "cases": cases,
    }
    payload = json.dumps(doc, ensure_ascii=False, indent=1)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(payload)
    cp = os.path.join(ASSEMBLY, "cases_v2.json")
    with open(cp, "w", encoding="utf-8") as f:
        f.write(payload)
    with open(os.path.join(ASSEMBLY, "build.log"), "a", encoding="utf-8") as f:
        f.write(f"\n== build {dt.datetime.now().isoformat(timespec='seconds')} version={args.version}\n"
                + "\n".join(log) + f"\ncases.json sha256 {sha256_file(args.out)}\n")
    entries = {os.path.relpath(p, ROOT): {"stage": "assembly", "case": None} for p in (tp, cp, args.out)}
    manifest_update(entries, {"kind": "tool", "name": "bank2_assemble.py"})
    manifest_set_version(args.version)
    print(f"{len(cases)} cases -> {os.path.relpath(args.out, ROOT)} (version {args.version}); "
          f"copy + tables in {os.path.relpath(ASSEMBLY, ROOT)}")


if __name__ == "__main__":
    main()
