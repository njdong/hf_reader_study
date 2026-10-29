"""Staged evaluator assignments for the reader study (bank v2 schedule).

Implements the CLI around the reference algorithm in data/bank_v2/schedule/simulation.py
(design: data/bank_v2/schedule/DESIGN.md). The reference module is imported, not copied,
so a seed plus the command history reproduces the simulated queues bit for bit.

Commands
  python tools/schedule.py --init --evaluators 3 --per 20 --core 10 --seed 20261028 \
         --base-url https://njdong.github.io/hf_reader_study/
  python tools/schedule.py --add 2 [--per 15]
  python tools/schedule.py --test-code      # create/refresh the R00 staff test evaluator (all 30 cases)
  ... --dry-run prints the planning report and writes nothing.

The R00 test evaluator is for the study team: it sees every case through the real page and real
backend, is persisted in STATE (so --add keeps it in assignments.json), appears in evaluators.csv
but NOT in randomization_key.csv, and its rows must be excluded from analysis by code.

Writes (atomically): docs/assignments.json (existing evaluators byte-identical on --add),
data/bank_v2/schedule/{STATE.json, evaluators.csv, randomization_key.csv}.
New codes must be pasted into the Google Sheet's `evaluators` tab.
"""

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import secrets
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHED = os.path.join(ROOT, "data", "bank_v2", "schedule")
STATE = os.path.join(SCHED, "STATE.json")
ASSIGN = os.path.join(ROOT, "docs", "assignments.json")
CASES_JSON = os.path.join(ROOT, "docs", "cases.json")

sys.path.insert(0, SCHED)
try:
    from simulation import LEVELS, Schedule, add_evaluators, check_invariants, init_schedule, load_cases, uniform_done, done_counts  # noqa: E402,F401
except ImportError as e:
    sys.exit(f"cannot import the reference implementation from {SCHED}/simulation.py: {e}")

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def new_code(ordinal, taken):
    while True:
        code = f"R{ordinal:02d}-" + "".join(secrets.choice(ALPHABET) for _ in range(4))
        if code not in taken:
            return code


def atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def planning_report(S):
    lines = []
    for pct in (100, 70, 50, 30):
        r, _ = done_counts(S, uniform_done(S, pct))
        vals = [r[c] for c in S.cases]
        lines.append(f"  {pct:>3}% done: cases>=1 {sum(v >= 1 for v in vals):>2}, "
                     f">=3 {sum(v >= 3 for v in vals):>2}, min {min(vals)}")
    budget = sum(e["per"] // 2 for e in S.evals)
    lines.append(f"  budget sum(per//2) = {budget}; need >= 90 for >=3 on all 30 at 50% completion"
                 + ("" if budget >= 90 else "  ** BELOW BUDGET **"))
    return "\n".join(lines)


def rebuild(state):
    """Replay init + history adds; returns the Schedule. Non-add entries (test-code) are skipped."""
    cases = {c: coh for c, coh in state["cases"].items()}
    h0 = state["history"][0]
    S = init_schedule(cases, h0["n"], h0["per"], h0["core"], state["seed"])
    for h in state["history"][1:]:
        if h["cmd"] == "add":
            add_evaluators(S, h["n"], h["per"])
    return S


def make_test_evaluator(state):
    """R00-XXXX with all cases: cohort-shuffled order, exactly balanced sides, seeded queue."""
    import random
    rng = random.Random(f"{state['seed']}:test")
    cases = sorted(state["cases"])
    rng.shuffle(cases)
    sides = ["A", "B"] * (len(cases) // 2) + (["A"] if len(cases) % 2 else [])
    rng.shuffle(sides)
    taken = {se["code"] for se in state["evaluators"]}
    prev = state.get("test_evaluator", {}).get("code")
    code = prev or new_code(0, taken)
    return {"code": code, "queue": [[c, s] for c, s in zip(cases, sides)]}


def queues_equal(S, state):
    if len(S.evals) != len(state["evaluators"]):
        return False
    for e, se in zip(S.evals, state["evaluators"]):
        if [[c, s] for c, s in e["queue"]] != [list(x) for x in se["queue"]] or e["per"] != se["per"]:
            return False
    return True


def write_outputs(S, state, dry):
    codes = [se["code"] for se in state["evaluators"]]
    doc_version = ""
    if os.path.exists(CASES_JSON):
        with open(CASES_JSON, encoding="utf-8") as f:
            cj = json.load(f)
        doc_version = cj.get("version", "")
        missing = [c for c in S.cases if c not in cj.get("cases", {})]
        if missing:
            sys.exit(f"cases missing from docs/cases.json: {', '.join(missing)}")
    assign = {"study": "hf_reader_study", "items_version": doc_version, "mode": "case",
              "generated": dt.datetime.now().isoformat(timespec="seconds"),
              "base_url": state.get("base_url", ""),
              "evaluators": {code: [{"case": c, "left": s} for c, s in e["queue"]]
                             for code, e in zip(codes, S.evals)}}
    base = state.get("base_url", "").rstrip("/")
    ev_rows = [[code, e["per"], f"{base}/?r={code}" if base else f"?r={code}"]
               for code, e in zip(codes, S.evals)]
    test = state.get("test_evaluator")
    if test:  # staff account: in assignments + evaluators.csv, never in randomization_key.csv
        assign["evaluators"][test["code"]] = [{"case": c, "left": s} for c, s in test["queue"]]
        ev_rows.append([test["code"], len(test["queue"]),
                        f"{base}/?r={test['code']}" if base else f"?r={test['code']}"])
    key_rows = []
    for code, e in zip(codes, S.evals):
        for p, (c, left) in enumerate(e["queue"], 1):
            key_rows.append([code, p, c, S.cohort[c], left, "B" if left == "A" else "A",
                             "MAS" if left == "A" else "NOTE"])
    if dry:
        print("(dry run: nothing written)")
        return
    atomic_write(ASSIGN, json.dumps(assign, ensure_ascii=False, indent=1))
    out = []
    w = csv.writer(_ListIO(out))
    w.writerow(["code", "n_cases", "link"])
    w.writerows(ev_rows)
    atomic_write(os.path.join(SCHED, "evaluators.csv"), "".join(out))
    out = []
    w = csv.writer(_ListIO(out))
    w.writerow(["evaluator", "position", "case", "cohort", "option_1", "option_2", "left_system"])
    w.writerows(key_rows)
    atomic_write(os.path.join(SCHED, "randomization_key.csv"), "".join(out))
    atomic_write(STATE, json.dumps(state, ensure_ascii=False, indent=1))
    print(f"wrote docs/assignments.json ({len(codes)} evaluators), "
          f"data/bank_v2/schedule/{{STATE.json, evaluators.csv, randomization_key.csv}}")
    print("paste the NEW codes into the sheet's `evaluators` tab (column A).")


class _ListIO:
    def __init__(self, out):
        self.out = out

    def write(self, s):
        self.out.append(s)


def state_from(S, old_state, args, cmd):
    sel_csv = os.path.join(ROOT, "data", "case_selection.csv")
    evaluators = old_state["evaluators"][:] if old_state else []
    taken = {se["code"] for se in evaluators}
    for e in S.evals[len(evaluators):]:
        code = new_code(len(evaluators) + 1, taken)
        taken.add(code)
        evaluators.append({"ordinal": len(evaluators) + 1, "code": code, "batch": e["batch"],
                           "per": e["per"], "queue": [[c, s] for c, s in e["queue"]]})
    history = (old_state["history"][:] if old_state else [])
    history.append({"batch": len(history), "cmd": cmd, "n": args_n(args, cmd), "per": args.per,
                    **({"core": args.core} if cmd == "init" else {}),
                    "at": dt.datetime.now().isoformat(timespec="seconds")})
    return {"schema": 1, "seed": old_state["seed"] if old_state else args.seed,
            "levels_pct": list(LEVELS), "target_pct": LEVELS[1],
            "core_k": old_state["core_k"] if old_state else args.core,
            "default_per": old_state["default_per"] if old_state else args.per,
            "base_url": old_state["base_url"] if old_state else args.base_url,
            "cases": dict(S.cohort), "case_selection_sha256": sha256_file(sel_csv),
            "core": list(S.core), "history": history, "evaluators": evaluators,
            "counters": {c: {"cnt": S.cnt[c], "sides": S.side[c], "relpos_sum": round(S.rsum[c], 6)}
                         for c in S.cases}}


def args_n(args, cmd):
    return args.evaluators if cmd == "init" else args.add


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--add", type=int)
    ap.add_argument("--test-code", action="store_true",
                    help="create/refresh the R00 staff test evaluator (sees all cases; excluded from analysis)")
    ap.add_argument("--evaluators", type=int, default=3)
    ap.add_argument("--per", type=int, default=None)
    ap.add_argument("--core", type=int, default=10)
    ap.add_argument("--seed", type=int, default=20261028)
    ap.add_argument("--base-url", default="https://njdong.github.io/hf_reader_study/")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite an existing STATE.json on --init")
    args = ap.parse_args()
    if sum([args.init, args.add is not None, args.test_code]) != 1:
        sys.exit("use exactly one of --init / --add N / --test-code")

    if args.test_code:
        with open(STATE, encoding="utf-8") as f:
            old = json.load(f)
        S = rebuild(old)
        if not queues_equal(S, old):
            sys.exit("replay does not reproduce STATE.json queues; aborting")
        state = dict(old)
        state["test_evaluator"] = make_test_evaluator(state)
        state["history"] = old["history"] + [{"batch": None, "cmd": "test-code",
                                              "at": dt.datetime.now().isoformat(timespec="seconds")}]
        print(f"test evaluator {state['test_evaluator']['code']}: all {len(state['test_evaluator']['queue'])} cases "
              f"(sides {sum(1 for _, s in state['test_evaluator']['queue'] if s == 'A')}A/"
              f"{sum(1 for _, s in state['test_evaluator']['queue'] if s == 'B')}B); excluded from analysis by code")
        write_outputs(S, state, args.dry_run)
        return

    if args.init:
        if os.path.exists(STATE) and not args.force:
            sys.exit(f"{STATE} exists; --init would invalidate distributed links (use --force to override)")
        args.per = args.per or 20
        cases = load_cases()
        S = init_schedule(cases, args.evaluators, args.per, args.core, args.seed)
        state = state_from(S, None, args, "init")
    else:
        with open(STATE, encoding="utf-8") as f:
            old = json.load(f)
        sel_sha = sha256_file(os.path.join(ROOT, "data", "case_selection.csv"))
        if sel_sha != old["case_selection_sha256"]:
            sys.exit("case_selection.csv changed since init; refusing to extend")
        S = rebuild(old)
        if not queues_equal(S, old):
            sys.exit("replay does not reproduce STATE.json queues (hand-edited file or code drift); aborting")
        if os.path.exists(ASSIGN):
            with open(ASSIGN, encoding="utf-8") as f:
                cur = json.load(f).get("evaluators", {})
            for se in old["evaluators"]:
                want = [{"case": c, "left": s} for c, s in se["queue"]]
                if cur.get(se["code"]) != want:
                    sys.exit(f"docs/assignments.json diverges from STATE for {se['code']}; aborting")
        before = [[list(x) for x in e["queue"]] for e in S.evals]
        args.per = args.per or old["default_per"]
        add_evaluators(S, args.add, args.per)
        for q0, e in zip(before, S.evals):
            assert [list(x) for x in e["queue"]] == q0, "existing queue changed"
        state = state_from(S, old, args, "add")

    fails = check_invariants(S)
    if fails:
        sys.exit("invariant violations: " + "; ".join(fails))
    print(f"{len(S.evals)} evaluators, queue lengths {[e['per'] for e in S.evals]}, core {' '.join(S.core)}")
    print(planning_report(S))
    write_outputs(S, state, args.dry_run)


if __name__ == "__main__":
    main()
