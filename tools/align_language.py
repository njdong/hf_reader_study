"""Proposal: rewrite the clinical-note column into the same planning language as the MAS column.

Nothing is applied by default. The script writes a side-by-side review page (out/language_alignment.html)
with the current text and the aligned text for every cell of every case, plus a JSON of the aligned
tables (out/cases_aligned.json). Pass --apply to write the aligned text into docs/cases.json.

Rules (deterministic, no LLM):
  clinical-note side
    GIVEN: x                      -> START: x                 (what was given, phrased as the plan to give it)
    PERFORMED: x                  -> PERFORM: x
    NEWLY PRESCRIBED: x           -> START: x
    HOME MEDS: x                  -> CONTINUE: x
    COMPLETED: x                  -> OBTAIN: x
    ADMITTED / ADMIT / TRANSFERRED: x -> ADMIT: x  /  TRANSFER: x
    RESPONSE: ...                 -> dropped (an outcome, not a plan)
    "(recorded diagnosis)", "(recorded diagnoses)", "(name as recorded in the source)" -> dropped
    "Not documented in the supplied extracts/output" lines -> "No recommendation."
    "MONITORING PLAN: Prospective schedule not documented ..." -> "MONITOR: No recommendation."
    "No new prescriptions recorded in the supplied ... extract." -> "START: None."
  MAS side
    " — specified in safety actions", " in safety actions", " in the prescription table", " per safety actions",
    " per safety review", " in safety review" -> dropped
    "source instruction is truncated"-type phrases -> dropped
Both sides keep their drug names, doses and clinical content unchanged.
"""

import argparse
import html
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NOTE_RULES = [
    (re.compile(r"^RESPONSE:.*$"), None),
    (re.compile(r"^(GIVEN|NEWLY PRESCRIBED|ED TREATMENT|START):\s*", re.I), "START: "),
    (re.compile(r"^PERFORMED:\s*", re.I), "PERFORM: "),
    (re.compile(r"^HOME MEDS:\s*", re.I), "CONTINUE: "),
    (re.compile(r"^COMPLETED:\s*", re.I), "OBTAIN: "),
    (re.compile(r"^(ADMITTED|ADMIT):\s*", re.I), "ADMIT: "),
    (re.compile(r"^TRANSFERRED:\s*", re.I), "TRANSFER: "),
    (re.compile(r"^RECOMMENDED:\s*", re.I), "REQUEST: "),
    (re.compile(r"^DIET RECOMMENDATION:\s*", re.I), "START: diet — "),
]
NOTE_PHRASES = [
    (re.compile(r"\s*\((recorded diagnos[ie]s|name as recorded in the source)\)"), ""),
    (re.compile(r"^(MONITORING PLAN|FURTHER WORKUP):\s*(Prospective (schedule|recommendations) )?not documented in the supplied extracts\.?$", re.I), "MONITOR: No recommendation."),
    (re.compile(r"^(FOLLOW-UP / DISCHARGE CRITERIA|LEVEL OF CARE / FOLLOW-UP / DISCHARGE CRITERIA|FOLLOW-UP / DISCHARGE CRITERIA):\s*Not documented.*$", re.I), "FOLLOW-UP: No recommendation."),
    (re.compile(r"^No new prescriptions recorded in the supplied.*$", re.I), "START: None."),
    (re.compile(r"^SOURCE LIMITATION:.*$", re.I), ""),
    (re.compile(r",?\s*(as documented in the narrative|documented in the clinical narrative|in the supplied clinical narrative|recorded in examination)", re.I), ""),
    (re.compile(r"^Acute IV diuretic or antibiotic administration is not documented.*$", re.I), ""),
    (re.compile(r"^No acute decongestive treatment documented.*$", re.I), ""),
    (re.compile(r"\s*\(unit name redacted\)|;\s*unit name redacted", re.I), ""),
    (re.compile(r"\s*—\s*type redacted in the source", re.I), ""),
    (re.compile(r"\s*recorded among coded diagnoses", re.I), ""),
    (re.compile(r"\s*among recorded diagnoses", re.I), ""),
]
MAS_PHRASES = [
    (re.compile(r"\s*—\s*specified in safety actions", re.I), ""),
    (re.compile(r"\s*(in|per) safety (actions|review)", re.I), ""),
    (re.compile(r"\s*in the prescription table", re.I), ""),
    (re.compile(r";\s*safety review recommends", re.I), "; recommend"),
    (re.compile(r"\s*—\s*at least 6-hour interval stated in output; source instruction is truncated", re.I), " — at least 6 hours between."),
    (re.compile(r";\s*safety instruction is truncated in the source", re.I), ""),
    (re.compile(r";\s*source initially assumes low body weight", re.I), ""),
    (re.compile(r",\s*as specified in the output", re.I), ""),
    (re.compile(r"\s*in prescription rationale", re.I), ""),
    (re.compile(r";\s*HFpEF recorded separately in the completeness assessment", re.I), ""),
    (re.compile(r"^(LEVEL OF CARE / (FOLLOW-UP / )?DISCHARGE CRITERIA|LEVEL OF CARE / FOLLOW-UP TIMING / DISCHARGE CRITERIA):\s*Not (otherwise )?documented in the supplied output\.?$", re.I), "FOLLOW-UP: No recommendation."),
    (re.compile(r"^LEVEL OF CARE / FOLLOW-UP / DISCHARGE CRITERIA:\s*Not documented in the supplied output\.?$", re.I), "FOLLOW-UP: No recommendation."),
]


def align_note(text):
    t = text.strip()
    for rx, rep in NOTE_RULES:
        if rx.search(t):
            if rep is None:
                return None
            t = rx.sub(rep, t, count=1)
            break
    for rx, rep in NOTE_PHRASES:
        t = rx.sub(rep, t)
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def align_mas(text):
    t = text.strip()
    for rx, rep in MAS_PHRASES:
        t = rx.sub(rep, t)
    return re.sub(r"\s+", " ", t).strip() or None


def align_cases(doc):
    out = {}
    for cid, c in doc["cases"].items():
        A = {d: [{"text": y} for y in (align_mas(x["text"]) for x in v) if y] for d, v in c["A"].items()}
        B = {d: [{"text": y} for y in (align_note(x["text"]) for x in v) if y] for d, v in c["B"].items()}
        for d in B:                                   # drop duplicates produced by the rewrite, keep order
            seen, uniq = set(), []
            for x in B[d]:
                if x["text"] not in seen:
                    seen.add(x["text"]); uniq.append(x)
            B[d] = uniq or [{"text": "No recommendation."}]
        out[cid] = {"A": A, "B": B}
    return out


def render(doc, aligned, path):
    e = html.escape
    css = """body{font:14px/1.45 -apple-system,Segoe UI,sans-serif;max-width:1250px;margin:24px auto;padding:0 16px;color:#111}
h1{font-size:21px}h2{font-size:18px;margin-top:40px;border-top:3px solid #345;padding-top:12px}
table{border-collapse:collapse;width:100%;margin:8px 0 18px;font-size:13px}th,td{border:1px solid #bbb;padding:6px 8px;vertical-align:top;text-align:left}
th{background:#dfe8f3}td.lab{width:11%;font-weight:600;background:#f4f7fa}td div{margin:2px 0}
.chg{background:#fff3b0}.gone{color:#999;text-decoration:line-through}.note{color:#666;font-size:12.5px}"""
    h = [f"<!doctype html><meta charset=utf-8><title>Language alignment proposal</title><style>{css}</style>",
         "<h1>Proposal: clinical-note column in the same planning language as the MAS column</h1>",
         "<p class=note>Not applied to the site. Left pair = clinical note (current → aligned); right pair = MAS (current → aligned, provenance jargon removed). <span class=chg>Yellow</span> = changed line; <span class=gone>struck</span> = dropped line. Rules are deterministic (tools/align_language.py); drug names, doses and clinical content are unchanged.</p>"]
    labels = dict(doc["domains"])
    for cid, c in doc["cases"].items():
        a = aligned[cid]
        h.append(f"<h2>{cid} — {e(c['cohort'].replace('_', ' '))} — {e(c.get('age_sex') or '')}</h2>")
        h.append("<table><tr><th>Domain</th><th>Clinical note — current</th><th>Clinical note — aligned</th><th>MAS — current</th><th>MAS — aligned</th></tr>")
        for d, label in doc["domains"]:
            def col(cur, new, fn):
                out_cur, out_new = [], []
                for x in cur:
                    y = fn(x["text"])
                    if y is None:
                        out_cur.append(f"<div class=gone>• {e(x['text'])}</div>")
                    elif y != x["text"].strip():
                        out_cur.append(f"<div>• {e(x['text'])}</div>"); out_new.append(f"<div class=chg>• {e(y)}</div>")
                    else:
                        out_cur.append(f"<div>• {e(x['text'])}</div>"); out_new.append(f"<div>• {e(y)}</div>")
                if not out_new:
                    out_new.append("<div class=chg>• No recommendation.</div>")
                return "".join(out_cur), "".join(out_new)
            bc, bn = col(c["B"][d], a["B"][d], align_note)
            ac, an = col(c["A"][d], a["A"][d], align_mas)
            h.append(f"<tr><td class=lab>{e(label)}</td><td>{bc}</td><td>{bn}</td><td>{ac}</td><td>{an}</td></tr>")
        h.append("</table>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(h))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", default=os.path.join(ROOT, "docs", "cases.json"))
    ap.add_argument("--html", default=os.path.join(ROOT, "out", "language_alignment.html"))
    ap.add_argument("--json", default=os.path.join(ROOT, "out", "cases_aligned.json"))
    ap.add_argument("--apply", action="store_true", help="write the aligned text into docs/cases.json")
    args = ap.parse_args()
    with open(args.cases, encoding="utf-8") as f:
        doc = json.load(f)
    aligned = align_cases(doc)
    render(doc, aligned, args.html)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(aligned, f, ensure_ascii=False, indent=1)
    n_b = sum(1 for cid, c in doc["cases"].items() for d, v in c["B"].items() for x in v if align_note(x["text"]) != x["text"].strip())
    n_a = sum(1 for cid, c in doc["cases"].items() for d, v in c["A"].items() for x in v if align_mas(x["text"]) != x["text"].strip())
    print(f"clinical-note lines changed: {n_b}; MAS lines changed: {n_a} -> {os.path.relpath(args.html, ROOT)}")
    if args.apply:
        for cid, c in doc["cases"].items():
            c["A"], c["B"] = aligned[cid]["A"], aligned[cid]["B"]
        with open(args.cases, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print("applied to", os.path.relpath(args.cases, ROOT))


if __name__ == "__main__":
    main()
