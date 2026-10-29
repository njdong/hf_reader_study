"""Render one case's full text progression (stage 1 -> 2 -> 3 -> shipped) as a local HTML page.

For every stem field and every plan line: the cited verbatim spans (collapsible), the stage-2
text with kept/dropped condition chips, the stage-3 text with a word-level diff against stage 2,
and confirmation that the shipped cell equals stage 3. Local use only (quotes licensed data);
output goes to data/bank_v2/case_reports/ (untracked).

Example
  python tools/bank2_casereport.py C081
"""

import argparse
import difflib
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from bank2_lib import BANK, ROOT  # noqa: E402
from bank2_align import align_line  # noqa: E402
from itemlib import DOMAINS as DOMAIN_LABELS  # noqa: E402

OUT_DIR = os.path.join(BANK, "case_reports")
STEM_FIELDS = [("presentation", "Presentation"), ("home_meds", "Medications"), ("vitals", "Vitals"),
               ("labs", "Labs"), ("exam", "Physical exam"), ("echo", "Echo"), ("ecg", "ECG"),
               ("imaging", "Imaging"), ("cath", "Catheterization / procedure")]

CSS = """
:root{--bg:#f5f6f8;--card:#fff;--fg:#1b2430;--muted:#5c6773;--line:#d8dee6;--s1:#8a63d2;
--s2:#1d7fb8;--s3:#2f8f5b;--kept:#e3f3e9;--kept-fg:#1d6b41;--drop:#fbe9e7;--drop-fg:#9a3b2a;
--ins:#dcf1e4;--ins-fg:#14532d;--del:#fde3e0;--del-fg:#8f2b1c;--mono:ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#13171c;--card:#1b2129;--fg:#e4e9ee;--muted:#97a3af;
--line:#2c3540;--s1:#a98ae8;--s2:#5aa8d6;--s3:#5cb688;--kept:#1b3326;--kept-fg:#7ecb9d;
--drop:#3a211d;--drop-fg:#e49a88;--ins:#173527;--ins-fg:#86d4a4;--del:#3c1f1a;--del-fg:#eba091}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14.5px/1.55 "Avenir Next","Segoe UI",system-ui,sans-serif;padding:0 16px 64px}
.wrap{max-width:1020px;margin:0 auto}h1{font-size:24px;margin:30px 0 2px}
h2{font-size:18px;margin:34px 0 10px}h3{font-size:14px;margin:0 0 4px}
.sub,.meta{color:var(--muted);font-size:12.5px}.sub{font-size:14px;margin:0 0 6px}
.item{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:10px 0}
.tag{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.06em;border-radius:4px;
padding:1px 7px;margin-right:8px;color:#fff;vertical-align:1px}
.t1{background:var(--s1)}.t2{background:var(--s2)}.t3{background:var(--s3)}
.stage{margin:7px 0 0;padding-left:2px}
.txt{font-size:14px;margin:2px 0 0}
del{background:var(--del);color:var(--del-fg);text-decoration:line-through;border-radius:3px;padding:0 2px}
ins{background:var(--ins);color:var(--ins-fg);text-decoration:none;border-radius:3px;padding:0 2px}
.chip{display:inline-block;font-size:11.5px;border-radius:10px;padding:0 8px;margin:3px 4px 0 0}
.kept{background:var(--kept);color:var(--kept-fg)}.drop{background:var(--drop);color:var(--drop-fg)}
details{margin:6px 0 0}summary{cursor:pointer;color:var(--muted);font-size:12px}
pre{white-space:pre-wrap;font-family:var(--mono);font-size:11.5px;background:var(--bg);
border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin:4px 0 0;max-height:320px;overflow:auto}
.same{color:var(--muted);font-size:12.5px}
.counts{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:var(--muted);margin:6px 0 0}
.notice{font-size:12.5px;color:var(--muted);border:1px solid var(--line);border-radius:8px;
padding:7px 11px;margin:12px 0 0;background:var(--card)}
"""


def esc(s):
    return html.escape(str(s))


def word_diff(a, b):
    """(a_html with <del>, b_html with <ins>) over whitespace tokens."""
    ta, tb = a.split(), b.split()
    sm = difflib.SequenceMatcher(a=ta, b=tb, autojunk=False)
    oa, ob = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        A, B = esc(" ".join(ta[i1:i2])), esc(" ".join(tb[j1:j2]))
        if op == "equal":
            oa.append(A), ob.append(B)
        else:
            if A:
                oa.append(f"<del>{A}</del>")
            if B:
                ob.append(f"<ins>{B}</ins>")
    return " ".join(x for x in oa if x), " ".join(x for x in ob if x)


def spans_details(from_ids, spans):
    out = []
    for sid in from_ids:
        s = spans.get(sid)
        body = esc(s["text"]) if s else "(span not found)"
        out.append(f"<details><summary>source span <code>{esc(sid)}</code></summary><pre>{body}</pre></details>")
    return "\n".join(out)


def chips(item):
    out = []
    for c in item.get("kept_conditions", []):
        out.append(f'<span class="chip kept">kept: {esc(c)}</span>')
    for c in item.get("dropped", []):
        out.append(f'<span class="chip drop">dropped: {esc(c)}</span>')
    return ("<div>" + "".join(out) + "</div>") if out else ""


def item_block(item, column, spans):
    s2 = item["text"]
    s3, _ = align_line(s2, column)
    if s3 == s2.strip():
        prog = (f'<div class="stage"><span class="tag t2">STAGE 2</span>'
                f'<span class="txt">{esc(s2)}</span>{chips(item)}</div>'
                f'<div class="stage same"><span class="tag t3">STAGE 3</span>unchanged by alignment → shipped as-is</div>')
    else:
        d2, d3 = word_diff(s2, s3)
        prog = (f'<div class="stage"><span class="tag t2">STAGE 2</span><span class="txt">{d2}</span>{chips(item)}</div>'
                f'<div class="stage"><span class="tag t3">STAGE 3</span><span class="txt">{d3}</span></div>')
    return f'<div class="item">{spans_details(item.get("from", []), spans)}{prog}</div>'


def stem_block(field, label, ext, spans):
    v = ext["stem"].get(field)
    items = v if isinstance(v, list) else ([v] if v else [])
    rows = []
    for it in items:
        rows.append(f'<div class="item"><div class="stage"><span class="tag t2">STAGE 2</span>'
                    f'<span class="txt">{esc(it["text"])}</span></div>'
                    f'{spans_details(it.get("from", []), spans)}</div>')
    return f"<h3>{esc(label)}</h3>" + ("\n".join(rows) or '<p class="meta">—</p>')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("case", help="e.g. C081")
    args = ap.parse_args()
    cid = args.case.upper()

    with open(os.path.join(BANK, "01_verbatim", f"{cid}.json"), encoding="utf-8") as f:
        verb = json.load(f)
    spans = {s["id"]: s for s in verb["sources"]}
    with open(os.path.join(BANK, "02_extracted", f"{cid}.json"), encoding="utf-8") as f:
        ext = json.load(f)
    with open(os.path.join(BANK, "assembly", "cases_v2.json"), encoding="utf-8") as f:
        shipped_doc = json.load(f)
    shipped = shipped_doc["cases"][cid]
    with open(os.path.join(BANK, "03_aligned", f"{cid}.json"), encoding="utf-8") as f:
        aligned = json.load(f)

    # shipped fidelity: every aligned line equals the shipped cell line
    fidelity = all(aligned[col_key][d] == [x["text"] for x in shipped[col][d]]
                   for col_key, col in (("mas", "A"), ("note", "B")) for d in aligned[col_key])

    parts = [f"<h1>{cid} — text progression through the pipeline</h1>",
             f'<p class="sub">{esc(shipped["cohort"].replace("_", " "))} · {esc(shipped.get("age_sex", ""))} · '
             f'bank version {esc(shipped_doc["version"])} · pid {esc(verb["pid"])} | hadm {esc(verb["hadm"])}</p>',
             f'<div class="counts"><span>{len(spans)} verbatim spans</span>'
             f'<span>MAS {ext["word_counts"]["mas"]} words</span><span>note {ext["word_counts"]["note"]} words</span>'
             f'<span>{len(aligned["edits"])} stage-3 edits</span>'
             f'<span>shipped cells byte-equal to stage 3: {"yes" if fidelity else "NO — investigate"}</span></div>',
             '<p class="notice">Local document only — quotes licensed data; lives in data/bank_v2/ (untracked), never share.</p>',
             '<p class="meta">Legend: <span class="tag t1">STAGE 1</span>verbatim span (expand to read) · '
             '<span class="tag t2">STAGE 2</span>cited extraction with <span class="chip kept">kept</span>'
             '<span class="chip drop">dropped</span> conditions · <span class="tag t3">STAGE 3</span>aligned = shipped; '
             'word diff shown as <del>removed</del> <ins>added</ins></p>']

    parts.append("<h2>Stem (what the rater reads first)</h2>"
                 '<p class="meta">The stem passes through stage 3 untouched; shipped text = stage 2.</p>')
    for field, label in STEM_FIELDS:
        parts.append(stem_block(field, label, ext, spans))

    for col_key, col_name in (("mas", "MAS column (Option A)"), ("note", "Clinical-note column (Option B)")):
        parts.append(f"<h2>{col_name}</h2>")
        for dom, dom_label in DOMAIN_LABELS.items():
            parts.append(f"<h3>{esc(dom_label)}</h3>")
            for item in ext[col_key].get(dom, []):
                parts.append(item_block(item, col_key, spans))

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"{cid}.html")
    doc = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
           "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
           f"<title>{cid} progression</title><style>{CSS}</style></head>"
           "<body><div class=\"wrap\">" + "\n".join(parts) + "</div></body></html>")
    with open(out, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"wrote {os.path.relpath(out, ROOT)}  (shipped fidelity: {'OK' if fidelity else 'MISMATCH'})")


if __name__ == "__main__":
    main()
