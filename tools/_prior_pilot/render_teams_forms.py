"""Render the five Teams-form questionnaires (data/teams-form) as a two-pane review page:
draft (stem + table with columns labelled MAS / Clinical note) on the left, judge notes
(data/judge-teams/caseNN.md, if present) on the right. Output: out/teams_forms.html.
"""
import html, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from build_fullcase import CSS, md_to_html  # noqa: E402
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TF = os.path.join(ROOT, "data", "teams-form"); JD = os.path.join(ROOT, "data", "judge-teams")
e = html.escape

def stem_html(txt):
    out, cur = [], []
    for line in txt.split("\n"):
        s = line.strip()
        if not s: continue
        if s.endswith(":") and len(s.split()) <= 4 or s in ("Physical Exam", "Imaging", "Cardiac Catheterization / Procedure", "Procedures/Other Studies"):
            out.append(f"<h3>{e(s.rstrip(':'))}</h3>")
        elif s.startswith(("Patient Home Medications", "Vitals:", "Labs:")):
            k, _, v = s.partition(":"); out.append(f"<p><b>{e(k)}:</b> {e(v)}</p>")
        elif s.startswith("Case ") or s.startswith("Clinical Evaluation"):
            continue
        else:
            out.append(f"<p>{e(s)}</p>")
    return "".join(out)

def main():
    tables = json.load(open(os.path.join(TF, "tables.json"), encoding="utf-8"))
    h = [f"<!doctype html><meta charset=utf-8><title>Teams forms — draft vs judge</title><style>{CSS}</style>",
         "<h1>Teams-form questionnaires (5 preferred cases) — draft (left) and judge notes (right)</h1>",
         "<p class=src>Columns are shown in the order they appear on each form, relabelled MAS / Clinical note (the forms say Option 1 / Option 2). MAS text is from the old MAS run; stems are whole-admission summaries; the Option 2 column is clipped in the PDF export (full image used here).</p>",
         "<p class=nav>" + " ".join(f"<a href='#f{n}'>Case {n} ({t['case_id']})</a>" for n, t in tables.items()) + "</p>"]
    summ = os.path.join(JD, "summary.md")
    if os.path.exists(summ):
        h.append("<details open><summary><b>Judge summary across the 5 forms</b></summary><div class=judge>" + md_to_html(open(summ, encoding="utf-8").read()) + "</div></details>")
    for n, t in tables.items():
        stem = open(os.path.join(TF, f"case{n}_stem.txt"), encoding="utf-8").read()
        jp = os.path.join(JD, f"case{n}.md")
        judge = md_to_html(open(jp, encoding="utf-8").read()) if os.path.exists(jp) else "<p><i>Judge notes pending.</i></p>"
        cls = lambda name: "mas" if name == "MAS" else "note"
        h.append(f"<h2 id='f{n}'>Teams form Case {n} — {t['case_id']} — on the form: Option 1 = {e(t['option_1'])}, Option 2 = {e(t['option_2'])}</h2><div class=two><div class=left>")
        h.append(f"<div class=stem>{stem_html(stem)}</div>")
        h.append(f"<table><tr><th>Domain</th><th class={cls(t['option_1'])}>{e(t['option_1'])} <span class=src>(Option 1 on the form)</span></th><th class={cls(t['option_2'])}>{e(t['option_2'])} <span class=src>(Option 2 on the form)</span></th></tr>")
        for r in t["rows"]:
            cells = ["".join(f"<div>• {e(x.strip())}</div>" for x in r[k].replace(". ", ".\n").split("\n") if x.strip()) for k in ("option_1", "option_2")]
            h.append(f"<tr><td>{e(r['domain'])}</td><td>{cells[0]}</td><td>{cells[1]}</td></tr>")
        h.append("</table><div class=rate><b>Select your preference for each category.</b> (5-point: strongly/slightly prefer Option 1 · neutral · slightly/strongly prefer Option 2) · Safety concerns Option 1 (0–4) · Safety concerns Option 2 (0–4) · Comments</div>")
        h.append(f"</div><div class=right><div class=judge>{judge}</div></div></div>")
    out = os.path.join(ROOT, "out", "teams_forms.html"); open(out, "w", encoding="utf-8").write("\n".join(h)); print("->", os.path.relpath(out, ROOT))

if __name__ == "__main__":
    main()
