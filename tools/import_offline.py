"""Turn an evaluator's downloaded answers file into rows for the Google Sheet.

When a network blocks Google, the study page lets the evaluator save a file
(hf_reader_study_<CODE>.json, via "Download my answers"). This script converts one or more such
files into the exact column layout of the `responses` tab (see apps_script/Code.gs HEADERS) so the
rows can be pasted in. Rows are produced for every answered case in the file, whether or not the page
managed to upload it; de-duplicate against the sheet by (evaluator, item_id) if in doubt.

Example
  python tools/import_offline.py ~/Downloads/hf_reader_study_R01-A5PV.json -o out/offline_rows.csv
"""

import argparse
import csv
import datetime as dt
import json

HEADERS = ["received_at", "study", "items_version", "evaluator", "item_id", "case_id", "domain", "position",
           "left_system", "choice", "score_A", "comment", "seconds_on_item", "submitted_at", "page_version", "user_agent",
           "safety_1", "safety_2", "safety_A", "safety_B"]
CHOICE_SCORE = {"strong_1": -2, "slight_1": -1, "neutral": 0, "slight_2": 1, "strong_2": 2}


def rows_from(doc):
    code = doc["evaluator"]
    pos = {e["case"]: i + 1 for i, e in enumerate(doc.get("queue", []))}
    left = {e["case"]: e["left"] for e in doc.get("queue", [])}
    pending = {p["case_id"]: p for p in doc.get("pending_upload", [])}
    out = []
    for case, a in doc.get("answers", {}).items():
        p = pending.get(case, {})
        lft = left.get(case, p.get("left_system", "A"))
        s1, s2 = a.get("safety_1", ""), a.get("safety_2", "")
        sA, sB = (s1, s2) if lft == "A" else (s2, s1)
        for dom, choice in a["answers"].items():
            raw = CHOICE_SCORE[choice]
            out.append([
                dt.datetime.now().isoformat(timespec="seconds") + " (imported from file)", doc.get("study", ""), doc.get("items_version", ""),
                code, f"{case}-{dom}", case, dom, pos.get(case, ""), lft, choice, -raw if lft == "A" else raw,
                a.get("comment", ""), p.get("seconds", ""), p.get("submitted_at", doc.get("exported_at", "")),
                doc.get("page_version", ""), "", s1, s2, sA, sB,
            ])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--out", default="out/offline_rows.csv")
    args = ap.parse_args()
    rows = []
    for f in args.files:
        with open(f, encoding="utf-8") as fh:
            doc = json.load(fh)
        r = rows_from(doc)
        print(f"{f}: evaluator {doc.get('evaluator')}, {len(doc.get('answers', {}))} cases, {len(r)} rows")
        rows += r
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADERS)
        w.writerows(rows)
    print(f"{len(rows)} rows -> {args.out}  (paste under the header of the 'responses' tab)")


if __name__ == "__main__":
    main()
