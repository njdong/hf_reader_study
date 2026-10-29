"""Assemble the 20 backup cases in the Teams-form format and record every edit between stages.

Stages per case (all kept on disk):
  1. extracted    data/formcases/extracted/C*.json   stem (vignette), note_raw (docx physician column), mas_raw (current MAS, uncondensed)
  2. reformatted  data/formcases/reformatted/C*.json MAS column rewritten in form style by an Opus 5.5 subagent (tools: SPEC.md)
  3. aligned      produced here with tools/align_language.py rules (same as the 10 form cases)

Writes
  data/formcases/tables_backup20.json   form-style tables for the 20 (option_1 = MAS, option_2 = Clinical note), aligned
  data/formcases/CHANGES_backup20.md    per case: stage-1 MAS raw → stage-2 reformatted (full text of both) and
                                        stage-2 → stage-3 line edits; clinical-note stage-1 → stage-3 line edits
  merged into data/teams-form/tables.json under keys "B06".."B95" so build_study.py --forms-only picks them up

Example
  python tools/build_formcases.py
"""

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from align_language import align_note, align_mas  # noqa: E402
from build_study import BULLET_SPLIT  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FC = os.path.join(ROOT, "data", "formcases")
DOMAINS = [("dx", "Diagnosis and HF characterization"), ("causes", "Decompensation causes and other active problems"),
           ("acute", "Acute treatment and decongestion"), ("gdmt", "Ongoing medication/GDMT decisions"),
           ("monitor", "Monitoring and further workup"), ("dispo", "Disposition and follow-up")]


def lines(txt):
    return [x.strip() for x in BULLET_SPLIT.split(txt or "") if x.strip()]


def align_cell(txt, fn):
    out, seen = [], set()
    for l in lines(txt):
        y = fn(l)
        if y and y not in seen:
            seen.add(y); out.append(y)
    return out or ["No recommendation."]


def main():
    tables, md = {}, ["# Backup-20 cases: edits from extracted → reformatted → aligned", "",
                      "Stage 1 (extracted) is verbatim source material. Stage 2 rewrites only the MAS column (Opus 5.5 subagent, "
                      "spec in data/formcases/SPEC.md). Stage 3 applies the deterministic rules in tools/align_language.py to both columns.", ""]
    missing = []
    for path in sorted(glob.glob(os.path.join(FC, "extracted", "C*.json"))):
        ex = json.load(open(path, encoding="utf-8"))
        cid = ex["case_id"]
        rp = os.path.join(FC, "reformatted", f"{cid}.json")
        if not os.path.exists(rp):
            missing.append(cid); continue
        rf = json.load(open(rp, encoding="utf-8"))
        rows, md_case = [], [f"\n## {cid} — {ex['cohort']} — {ex['age_sex']}\n", f"*Reformatter notes:* {rf.get('notes', '').strip()}\n"]
        for d, label in DOMAINS:
            mas_raw = ex["mas_raw"].get(d) or ""
            mas_ref = rf["mas"].get(d) or ""
            note_raw = ex["note_raw"].get(d) or ""
            mas_al = align_cell(mas_ref, align_mas)
            note_al = align_cell(note_raw, align_note)
            rows.append({"domain": label, "option_1": ". ".join(x.rstrip(".") for x in mas_al) + ".",
                         "option_2": ". ".join(x.rstrip(".") for x in note_al) + "."})
            md_case.append(f"### {label}")
            md_case.append("**MAS, stage 1 (extracted, uncondensed):**\n```\n" + (mas_raw.strip() or "(nothing)") + "\n```")
            md_case.append("**MAS, stage 2 (reformatted):** " + (mas_ref.strip() or "(nothing)"))
            ch = [(l, align_mas(l)) for l in lines(mas_ref) if align_mas(l) != l]
            md_case.append("**MAS, stage 2 → 3:** " + ("; ".join(f"“{a}” → “{b or '(dropped)'}”" for a, b in ch) if ch else "no change"))
            chn = [(l, align_note(l)) for l in lines(note_raw) if align_note(l) != l]
            md_case.append("**Clinical note, stage 1 (verbatim):** " + (note_raw.strip() or "(nothing)"))
            md_case.append("**Clinical note, stage 1 → 3:** " + ("; ".join(f"“{a}” → “{b or '(dropped)'}”" for a, b in chn) if chn else "no change") + "\n")
        key = "B" + cid[2:]
        tables[key] = {"form_case": key, "case_id": cid, "option_1": "MAS", "option_2": "Clinical note",
                       "domains": [l for _, l in DOMAINS], "rows": rows,
                       "notes": "Backup case: stem = Case Formatting vignette; clinical note = editable-tables column; MAS = current run reformatted by subagent, then aligned."}
        md += md_case
    if missing:
        print("missing reformatted files:", missing)
    json.dump(tables, open(os.path.join(FC, "tables_backup20.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(FC, "CHANGES_backup20.md"), "w", encoding="utf-8").write("\n".join(md))
    # merge into the form tables so build_study.py treats them like the other forms
    tp = os.path.join(ROOT, "data", "teams-form", "tables.json")
    all_t = json.load(open(tp, encoding="utf-8"))
    all_t = {k: v for k, v in all_t.items() if not k.startswith("B")}
    all_t.update(tables)
    json.dump(all_t, open(tp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(tables)} backup cases -> tables_backup20.json, CHANGES_backup20.md; tables.json now has {len(all_t)} entries")


if __name__ == "__main__":
    main()
