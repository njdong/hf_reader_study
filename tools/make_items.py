"""Turn raw cases + two system outputs into reader-study items with an LLM.

Input: data/cases/<CASE>.json
  {
    "case_id": "C01",
    "case_text": "full case text (HPI, meds, vitals, labs, exam, echo, ECG, imaging)",
    "system_a": {"dx": "...", "causes": "...", "acute": "...", "gdmt": "...", "monitor": "...", "dispo": "..."},
    "system_b": {... same keys ...}
  }
system_a is the multi-agent system, system_b the baseline. Missing domains are skipped.

Output: items are validated and merged into docs/items.json (same id = replaced).

LLM: any OpenAI-compatible chat endpoint (OpenAI, Azure OpenAI, Anthropic's compatible endpoint,
vLLM on PARCC, ...). Set:
  LLM_BASE_URL   e.g. https://api.openai.com/v1  or  http://localhost:8000/v1
  LLM_API_KEY
  LLM_MODEL
Or the Claude Code CLI, which needs no API key: set CLAUDE_BIN to the `claude` binary (and LLM_MODEL,
default claude-opus-5-5). Or replace call_llm() below with your own client.

Examples
  python tools/make_items.py data/cases/C01.json                 # one case
  python tools/make_items.py data/cases/*.json                   # all cases
  python tools/make_items.py data/cases/C01.json --dry-run       # write prompts to out/prompts/, no LLM call
  python tools/make_items.py data/cases/C01.json --domains gdmt acute
  CLAUDE_BIN=~/.claude/local/claude python tools/make_items.py data/cases/C0*.json --jobs 6
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(__file__))
import itemlib  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT_PATH = os.path.join(ROOT, "prompts", "item_prompt.md")

STEM_FIELDS = {
    "dx": "Course (presentation) · Vitals · Labs (BNP, troponin) · Echo · Imaging",
    "causes": "Course (history, timeline, treatments already given) · Vitals · Labs · Echo · Imaging · Home meds",
    "acute": "Given (treatments already given) · Vitals (with congestion signs) · Labs (Cr, K, Hb) · Home meds",
    "gdmt": "Vitals · Labs (Cr, K, QTc, Hb) · History (bleeding, anticoagulation, intolerances) · Home meds",
    "monitor": "Echo or Imaging (structural findings) · Labs (Cr, K, QTc, troponin, Hb) · New meds",
    "dispo": "Status (current vitals, oxygen, mental status) · Echo (EF, valves) · Labs",
}


def call_llm(prompt):
    base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "")
    if os.environ.get("CLAUDE_BIN"):
        r = subprocess.run(
            [os.environ["CLAUDE_BIN"], "-p", "--model", model or "claude-opus-5-5", "--output-format", "text"],
            input=prompt, capture_output=True, text=True, timeout=600,
        )
        if r.returncode != 0:
            raise ValueError(f"claude exited {r.returncode}: {r.stderr.strip()[:300]}")
        return r.stdout
    if not (base and model):
        sys.exit("Set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL (or CLAUDE_BIN), or use --dry-run.")
    body = json.dumps({
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        base + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def build_prompt(case, domain, example):
    template = open(PROMPT_PATH, encoding="utf-8").read()
    return template.format(
        domain=domain,
        domain_label=itemlib.DOMAINS[domain],
        case_id=case["case_id"],
        stem_fields=STEM_FIELDS[domain],
        core_slots=", ".join(itemlib.CORE_SLOTS[domain]),
        example=json.dumps(example, ensure_ascii=False, indent=1),
        case_text=case["case_text"].strip(),
        a_text=(case["system_a"].get(domain) or "(nothing for this domain)").strip(),
        b_text=(case["system_b"].get(domain) or "(nothing for this domain)").strip(),
    )


def pick_example(doc, case_id, domain):
    # Prefer a finished item from another case, same domain; fall back to any item.
    pool = [it for it in doc["items"] if it["case"] != case_id]
    same = [it for it in pool if it["domain"] == domain]
    return (same or pool or doc["items"])[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases", nargs="+")
    ap.add_argument("--items", default="docs/items.json")
    ap.add_argument("--domains", nargs="*", default=list(itemlib.DOMAINS))
    ap.add_argument("--dry-run", action="store_true", help="write prompts to out/prompts/ only")
    ap.add_argument("--retries", type=int, default=1, help="re-ask with the validation errors this many times")
    ap.add_argument("--jobs", type=int, default=1, help="LLM calls to run in parallel")
    args = ap.parse_args()

    doc = itemlib.load(args.items)
    by_id = {it["id"]: it for it in doc["items"]}
    failed = []

    jobs = []                             # (item id, prompt)
    for path in args.cases:
        case = itemlib.load(path)
        for domain in args.domains:
            if not (case["system_a"].get(domain) or case["system_b"].get(domain)):
                continue
            iid = f"{case['case_id']}-{domain}"
            prompt = build_prompt(case, domain, pick_example(doc, case["case_id"], domain))
            if args.dry_run:
                os.makedirs("out/prompts", exist_ok=True)
                with open(f"out/prompts/{iid}.txt", "w", encoding="utf-8") as f:
                    f.write(prompt)
                print(f"{iid}: prompt written")
                continue
            jobs.append((iid, prompt))

    def make(job):
        iid, prompt = job
        ask = prompt
        for attempt in range(args.retries + 1):
            try:
                item = parse_json(call_llm(ask))
            except (ValueError, KeyError, subprocess.TimeoutExpired) as e:
                errs = [f"{iid}: response was not valid JSON ({e})"]
            else:
                errs = []
                itemlib.validate_item(item, errs)
                if not errs and item["id"] != iid:
                    errs = [f"{iid}: returned id {item['id']!r}"]
            if not errs:
                return iid, item, []
            ask = prompt + "\n\nYour previous answer had these problems; return corrected JSON only:\n" + "\n".join(errs)
        return iid, None, errs

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for iid, item, errs in pool.map(make, jobs):
            if item:
                by_id[iid] = item
                print(f"{iid}: ok", flush=True)
            else:
                failed.append(iid)
                print(f"{iid}: FAILED\n  " + "\n  ".join(errs), flush=True)

    if not args.dry_run:
        order = {d: i for i, d in enumerate(itemlib.DOMAINS)}
        doc["items"] = sorted(by_id.values(), key=lambda it: (it["case"], order[it["domain"]]))
        itemlib.save(doc, args.items)
        print(f"{args.items}: {len(doc['items'])} items")
    if failed:
        sys.exit(f"{len(failed)} items failed: {failed}")


if __name__ == "__main__":
    main()
