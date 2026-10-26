"""Assemble the case-mode study: docs/cases.json from data/fullcases/, and case-level assignments.

Each evaluator rates whole cases (all six domains on one screen), in a random order, with the side
of the MAS randomized per case. Every case is rated about equally often, and for each case the MAS
appears as Option 1 in about half of its ratings.

Writes
  docs/cases.json          what the page shows: stem, MAS column (A), clinical-note column (B)
  docs/assignments.json    {evaluators: {code: [{case, left}, ...]}}   left = system shown as Option 1
  out/evaluators.csv       code, n_cases, link
  out/randomization_key.csv  evaluator, position, case, option_1, option_2, left_system

Examples
  python tools/build_study.py --evaluators 25 --per 6 --seed 20261026 --base-url https://njdong.github.io/hf_reader_study/
  python tools/build_study.py --cases-only          # rebuild docs/cases.json, keep assignments
"""

import argparse
import csv
import datetime as dt
import json
import os
import random
import string
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from itemlib import DOMAINS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "O0I1L")


def load_cases(selection, fullcases_dir):
    with open(selection, newline="", encoding="utf-8") as f:
        sel = {r["case"]: r for r in csv.DictReader(f)}
    cases = {}
    for case, r in sel.items():
        path = os.path.join(fullcases_dir, f"C{case}.json")
        if not os.path.exists(path):
            print(f"warning: no full case file for {case}; skipped")
            continue
        with open(path, encoding="utf-8") as f:
            fc = json.load(f)
        cases[fc["case_id"]] = {
            "case_id": fc["case_id"], "cohort": fc["cohort"], "age_sex": fc.get("age_sex"), "label": r["label"],
            "stem": fc["stem"], "A": fc["mas"], "B": fc["reference"],
        }
    return cases


def new_code(index, rng, taken):
    while True:
        code = f"R{index:02d}-" + "".join(rng.choice(ALPHABET) for _ in range(4))
        if code not in taken:
            return code


def deck(cases, rng):
    """Case ids interleaved by cohort, shuffled within cohort, so round-robin dealing spreads cohorts."""
    by = defaultdict(list)
    for cid, c in cases.items():
        by[c["cohort"]].append(cid)
    for g in by.values():
        rng.shuffle(g)
    out = []
    for i in range(max(len(g) for g in by.values())):
        out += [g[i] for g in by.values() if i < len(g)]
    return out


def assign(cases, n_eval, per, rng):
    """Each evaluator gets `per` distinct cases; coverage balanced; MAS side alternates per case."""
    count = Counter()
    side_count = defaultdict(Counter)
    evaluators = {}
    base = deck(cases, rng)
    for idx in range(1, n_eval + 1):
        code = new_code(idx, rng, evaluators)
        # least-rated cases first, ties broken by deck order (cohort spread) then randomness
        order = sorted(base, key=lambda c: (count[c], rng.random()))
        picked = order[:per]
        rng.shuffle(picked)                                   # random case order for this evaluator
        queue = []
        for cid in picked:
            a, b = side_count[cid]["A"], side_count[cid]["B"]
            left = "A" if a < b else "B" if b < a else rng.choice("AB")
            side_count[cid][left] += 1
            count[cid] += 1
            queue.append({"case": cid, "left": left})
        evaluators[code] = queue
    return evaluators, count, side_count


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selection", default=os.path.join(DATA, "case_selection.csv"))
    ap.add_argument("--fullcases", default=os.path.join(DATA, "fullcases"))
    ap.add_argument("--out-cases", default=os.path.join(ROOT, "docs", "cases.json"))
    ap.add_argument("--out-assign", default=os.path.join(ROOT, "docs", "assignments.json"))
    ap.add_argument("--csv", default=os.path.join(ROOT, "out", "evaluators.csv"))
    ap.add_argument("--evaluators", type=int, default=25)
    ap.add_argument("--per", type=int, default=6, help="cases per evaluator")
    ap.add_argument("--seed", type=int, default=20261026)
    ap.add_argument("--base-url", default="")
    ap.add_argument("--version", default=dt.date.today().isoformat())
    ap.add_argument("--cases-only", action="store_true")
    args = ap.parse_args()

    cases = load_cases(args.selection, args.fullcases)
    doc = {
        "study": "hf_reader_study", "version": args.version, "mode": "case",
        "systems": {"A": "multi-agent system (current run, first-12 h chart)", "B": "clinical note (record: coded diagnoses, orders, prescriptions)"},
        "domains": [[k, v] for k, v in DOMAINS.items()],
        "cases": cases,
    }
    with open(args.out_cases, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"{len(cases)} cases -> {os.path.relpath(args.out_cases, ROOT)}")
    if args.cases_only:
        return

    rng = random.Random(args.seed)
    evaluators, count, side_count = assign(cases, args.evaluators, args.per, rng)
    out = {"study": doc["study"], "items_version": args.version, "mode": "case",
           "generated": dt.datetime.now().isoformat(timespec="seconds"), "base_url": args.base_url,
           "evaluators": evaluators}
    with open(args.out_assign, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
    base = args.base_url.rstrip("/") + "/" if args.base_url else ""
    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "n_cases", "link"])
        for code, q in evaluators.items():
            w.writerow([code, len(q), f"{base}?r={code}" if base else f"?r={code}"])
    keyp = os.path.join(os.path.dirname(args.csv) or ".", "randomization_key.csv")
    with open(keyp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["evaluator", "position", "case", "cohort", "option_1", "option_2", "left_system"])
        for code, q in evaluators.items():
            for pos, e in enumerate(q, 1):
                o1, o2 = ("MAS", "clinical note") if e["left"] == "A" else ("clinical note", "MAS")
                w.writerow([code, pos, e["case"], cases[e["case"]]["cohort"], o1, o2, e["left"]])

    counts = [count[c] for c in cases]
    imb = max(abs(side_count[c]["A"] - side_count[c]["B"]) for c in cases)
    print(f"{len(evaluators)} evaluators, {args.per} cases each; ratings per case min {min(counts)} max {max(counts)}; "
          f"max MAS-left imbalance per case {imb}")
    print(f"wrote {os.path.relpath(args.out_assign, ROOT)}, {os.path.relpath(args.csv, ROOT)}, {os.path.relpath(keyp, ROOT)}")


if __name__ == "__main__":
    main()
