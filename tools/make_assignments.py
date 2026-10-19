"""Assign items to evaluators with balanced coverage and counterbalanced option order.

Each evaluator gets --per distinct items. Items are chosen so every item is rated about
equally often, and for each item the multi-agent system (A) appears as "Option 1" in about
half of its ratings. Writes:
  docs/assignments.json   read by the evaluator page
  out/evaluators.csv      evaluator code + personal link; paste codes into the Google Sheet

Examples
  python tools/make_assignments.py --evaluators 12 --per 10 --base-url https://USER.github.io/hf-reader-study/
  python tools/make_assignments.py --add 3 --per 10      # add 3 evaluators, keep existing assignments
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
import itemlib  # noqa: E402

ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "O0I1L")
DOMAIN_ORDER = list(itemlib.DOMAINS)


def new_code(index, rng, taken):
    while True:
        code = f"R{index:02d}-" + "".join(rng.choice(ALPHABET) for _ in range(4))
        if code not in taken:
            return code


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--items", default="docs/items.json")
    ap.add_argument("--out", default="docs/assignments.json")
    ap.add_argument("--csv", default="out/evaluators.csv")
    ap.add_argument("--evaluators", type=int, default=0, help="number of evaluators (new file)")
    ap.add_argument("--add", type=int, default=0, help="add this many evaluators to an existing assignments file")
    ap.add_argument("--per", type=int, default=10, help="items per evaluator")
    ap.add_argument("--max-per-case", type=int, default=0, help="cap items from one case per evaluator (0 = no cap)")
    ap.add_argument("--order", choices=["random", "case"], default="random",
                    help="random: shuffle each queue; case: group an evaluator's items by case")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--base-url", default="", help="GitHub Pages URL, used to build personal links")
    args = ap.parse_args()

    doc = itemlib.load(args.items)
    errors = itemlib.validate(doc)
    if errors:
        sys.exit("items.json has errors:\n" + "\n".join(errors))
    items = {it["id"]: it for it in doc["items"]}

    rng = random.Random(args.seed)
    count = Counter()                     # ratings per item
    left = defaultdict(Counter)           # left[item]["A"|"B"] = times shown as Option 1
    evaluators = {}

    if args.add:
        if not os.path.exists(args.out):
            sys.exit(f"--add needs an existing {args.out}")
        prev = itemlib.load(args.out)
        evaluators = prev["evaluators"]
        args.base_url = args.base_url or prev.get("base_url", "")
        unknown = {e["item"] for q in evaluators.values() for e in q} - set(items)
        if unknown:
            print(f"warning: existing assignments use items no longer in items.json: {sorted(unknown)}")
        for queue in evaluators.values():  # count existing ratings so new evaluators fill the gaps
            for e in queue:
                if e["item"] in items:
                    count[e["item"]] += 1
                    left[e["item"]][e["left"]] += 1
        n_new = args.add
    else:
        if args.evaluators <= 0:
            sys.exit("give --evaluators N (or --add N to extend an existing file)")
        n_new = args.evaluators

    per = args.per
    if per > len(items):
        print(f"warning: --per {per} > {len(items)} items; using {len(items)}")
        per = len(items)

    start = len(evaluators) + 1
    for idx in range(start, start + n_new):
        code = new_code(idx, rng, evaluators)
        ranked = sorted(items, key=lambda i: (count[i], rng.random()))
        picked, per_case = [], Counter()
        for iid in ranked:
            case = items[iid]["case"]
            if args.max_per_case and per_case[case] >= args.max_per_case:
                continue
            picked.append(iid)
            per_case[case] += 1
            if len(picked) == per:
                break
        if len(picked) < per:
            print(f"warning: {code} got {len(picked)} items (per-case cap too tight)")

        if args.order == "case":
            picked.sort(key=lambda i: (items[i]["case"], DOMAIN_ORDER.index(items[i]["domain"])))
        else:
            rng.shuffle(picked)

        queue = []
        for iid in picked:
            a, b = left[iid]["A"], left[iid]["B"]
            side = "A" if a < b else "B" if b < a else rng.choice("AB")
            left[iid][side] += 1
            count[iid] += 1
            queue.append({"item": iid, "left": side})
        evaluators[code] = queue

    out = {
        "study": doc.get("study", ""),
        "items_version": doc.get("version", ""),
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "evaluators": evaluators,
    }
    itemlib.save(out, args.out)

    os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
    base = args.base_url.rstrip("/") + "/" if args.base_url else ""
    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "n_items", "link"])
        for code, queue in evaluators.items():
            w.writerow([code, len(queue), f"{base}?r={code}" if base else f"?r={code}"])

    counts = [count[i] for i in items]
    imbalance = max(abs(left[i]["A"] - left[i]["B"]) for i in items)
    print(f"{len(evaluators)} evaluators ({n_new} new), {per} items each")
    print(f"ratings per item: min {min(counts)}, max {max(counts)}, total {sum(counts)}")
    print(f"max |A-left minus B-left| for any item: {imbalance}")
    print(f"wrote {args.out} and {args.csv}")


if __name__ == "__main__":
    main()
