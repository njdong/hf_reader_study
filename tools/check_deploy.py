"""End-to-end deployment check for the HF reader study (stdlib only; run from any network).

Checks (PASS/FAIL each):
  1. GitHub Pages serves index.html with the expected PAGE_VERSION
  2. cases.json: expected version (if given), 30 cases, 6 domains, grep guard clean
  3. assignments.json: every assigned case exists in cases.json; evaluator code format
  4. config.js carries an /exec endpoint
  5. GET  endpoint?r=TEST-DEPLOY returns JSON (needs TEST-DEPLOY in the sheet's evaluators tab)
  6. POST a marked test case as TEST-DEPLOY -> {ok:true, rows:6}        (--live only)
  7. GET again: the six TEST-* item ids are listed as done               (--live only)

The test rows are marked (evaluator TEST-DEPLOY, comment "deployment check - delete");
delete them from the responses tab afterwards.

Examples
  python tools/check_deploy.py                 # read-only checks
  python tools/check_deploy.py --live          # also POST one test case and read it back
"""

import argparse
import datetime as dt
import json
import os
import re
import ssl
import sys
import urllib.request

# macOS python.org builds often lack root certs; use certifi when the default store fails to load.
try:
    SSL_CTX = ssl.create_default_context()
    if not SSL_CTX.cert_store_stats().get("x509_ca"):
        raise ValueError("empty CA store")
except Exception:
    SSL_CTX = None
if SSL_CTX is None:
    try:
        import certifi
        SSL_CTX = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        sys.exit("no usable CA store: install certifi (pip install certifi) or run with a python that has root certs")

BASE = "https://njdong.github.io/hf_reader_study/"
GUARD = re.compile(r"supplied|safety actions|prescription table|recorded diagnos|in the record|"
                   r"second-hand|Contingency:|not documented|not_applicable", re.I)
CODE_RE = re.compile(r"^(R\d{2}-[A-HJKMNP-Z2-9]{4}|TEST-DEPLOY)$")
RESULTS = []


def fetch(url, data=None):
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "hf-reader-study-check", **({"Content-Type": "text/plain;charset=utf-8"} if data else {})})
    with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
        return r.read().decode("utf-8")


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-url", default=BASE)
    ap.add_argument("--page-version", default=None, help="expected PAGE_VERSION in index.html")
    ap.add_argument("--cases-version", default=None, help="expected cases.json version")
    ap.add_argument("--live", action="store_true", help="POST a marked test case and read it back")
    args = ap.parse_args()
    base = args.base_url.rstrip("/") + "/"

    # 1 page
    try:
        html = fetch(base + "index.html")
        m = re.search(r'PAGE_VERSION = "([^"]+)"', html)
        got = m.group(1) if m else None
        check("index.html served", bool(m), f"PAGE_VERSION {got}")
        if args.page_version:
            check("PAGE_VERSION matches", got == args.page_version, f"{got} vs {args.page_version}")
        check("completeness radios in page", "comp-1" in html and "completeness_1" in html)
        check("no time estimate", "minutes" not in html.split("Before you start")[-1][:600])
    except Exception as e:
        check("index.html served", False, str(e))
        html = ""

    # 2 cases.json
    doc = {}
    try:
        doc = json.loads(fetch(base + "cases.json"))
        check("cases.json: 30 cases", len(doc.get("cases", {})) == 30, f"{len(doc.get('cases', {}))} cases, version {doc.get('version')}")
        if args.cases_version:
            check("cases.json version matches", doc.get("version") == args.cases_version, str(doc.get("version")))
        bad = [f"{cid}/{col}/{d}" for cid, c in doc.get("cases", {}).items() for col in ("A", "B")
               for d, items in c.get(col, {}).items() for x in items if GUARD.search(x.get("text", ""))]
        check("grep guard clean (A/B cells)", not bad, "; ".join(bad[:5]))
        nd = {len(c.get("A", {})) for c in doc.get("cases", {}).values()} | {len(c.get("B", {})) for c in doc.get("cases", {}).values()}
        check("6 domains per column", nd == {6}, str(nd))
    except Exception as e:
        check("cases.json served", False, str(e))

    # 3 assignments.json
    try:
        asg = json.loads(fetch(base + "assignments.json"))
        evs = asg.get("evaluators", {})
        missing = [e["case"] for q in evs.values() for e in q if e["case"] not in doc.get("cases", {})]
        check("assignments: all cases exist", not missing, "; ".join(sorted(set(missing))[:5]) or f"{len(evs)} evaluators")
        badc = [c for c in evs if not CODE_RE.match(c)]
        check("assignments: code format", not badc, "; ".join(badc[:5]))
    except Exception as e:
        check("assignments.json served", False, str(e))

    # 4 config.js endpoint
    endpoint = None
    try:
        cfg = fetch(base + "config.js")
        m = re.search(r'endpoint:\s*"(https://script\.google\.com/[^"]+/exec)"', cfg)
        endpoint = m.group(1) if m else None
        check("config.js endpoint", bool(endpoint))
    except Exception as e:
        check("config.js served", False, str(e))

    # 5-7 backend
    if endpoint:
        try:
            r = json.loads(fetch(endpoint + ("&" if "?" in endpoint else "?") + "r=TEST-DEPLOY"))
            known = r.get("ok") is True
            check("GET ?r=TEST-DEPLOY returns JSON", isinstance(r, dict),
                  "ok" if known else f"{r.get('error')} (add TEST-DEPLOY to the evaluators tab)")
            if known:
                check("backend has completeness columns", r.get("columns") == 24,
                      f"columns={r.get('columns')} (24 = current Code.gs; else redeploy: Manage deployments -> Edit -> New version)")
            if args.live and check("TEST-DEPLOY registered", known):
                domains = [d[0] for d in doc.get("domains", [])] or ["dx", "causes", "acute", "gdmt", "monitor", "dispo"]
                payload = {"study": doc.get("study", "hf_reader_study"), "items_version": doc.get("version", ""),
                           "evaluator": "TEST-DEPLOY", "case_id": "TEST", "position": 0, "left_system": "A",
                           "answers": {d: "neutral" for d in domains}, "safety_1": 0, "safety_2": 0,
                           "completeness_1": 0, "completeness_2": 0,
                           "comment": "deployment check - delete", "seconds": 0,
                           "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                           "page_version": "check_deploy", "user_agent": "check_deploy.py"}
                res = json.loads(fetch(endpoint, json.dumps(payload).encode("utf-8")))
                check("POST test case accepted", res.get("ok") is True and res.get("rows") == len(domains), str(res))
                r2 = json.loads(fetch(endpoint + ("&" if "?" in endpoint else "?") + "r=TEST-DEPLOY"))
                want = {f"TEST-{d}" for d in domains}
                check("GET lists the 6 test item ids", want <= set(r2.get("done", [])),
                      f"{len(want & set(r2.get('done', [])))}/{len(want)} listed")
        except Exception as e:
            check("backend reachable", False, str(e))

    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{'ALL PASS' if not n_fail else f'{n_fail} FAILED'} ({len(RESULTS)} checks)")

    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bank_v2", "deployment")
    if os.path.isdir(os.path.dirname(log_dir)):
        os.makedirs(log_dir, exist_ok=True)
    else:
        log_dir = "."
    log = os.path.join(log_dir, f"check_{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.log")
    with open(log, "w", encoding="utf-8") as f:
        f.write(f"check_deploy {dt.datetime.now().isoformat(timespec='seconds')} base={base} live={args.live}\n")
        for name, ok, detail in RESULTS:
            f.write(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}\n")
    print(f"log: {log}")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
