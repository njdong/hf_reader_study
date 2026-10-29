"""Build non-fragmented study cases: a first-12 h stem, a 6-domain MAS vs clinical-note table, one page per case.

For each case (default: the "preferred" rows of data/case_selection.csv):
  stem           written by the LLM from the first-12 h chart blocks only (HPI, exam, labs, echo, ECG,
                 imaging, orders), in the sectioned vignette layout: presentation, home meds, vitals, labs,
                 then Physical Exam / Echo / ECG / Imaging / Cath bullets. Nothing from later in the admission.
  mas            rendered mechanically from mas_outputs.json (no LLM): grouped by verb, meta text removed,
                 contingencies and rationales kept as collapsible detail.
  reference      parsed directly from the record, no LLM: coded primary diagnosis and HF type, other coded
                 diagnoses (whole admission), the first-12 h order list verbatim, the clinicians' new
                 prescriptions verbatim, studies present in the first 12 h, admission type and dates.
                 It is a record of what happened, shown as reference, not a competing plan.
Output: data/fullcases/C<case>.json and out/fullcases.html: a two-pane viewer, questionnaire draft on the
left and the judge's notes (data/judge/C<case>.md, if present) on the right.

LLM: the Claude Code CLI (CLAUDE_BIN) or an OpenAI-compatible endpoint, as in make_items.py.

Examples
  CLAUDE_BIN=~/.claude/local/claude python tools/build_fullcase.py --jobs 6
  python tools/build_fullcase.py --cases 081 031 --render-only     # re-render HTML from existing JSON
"""

import argparse
import csv
import html
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(__file__))
from itemlib import DOMAINS  # noqa: E402
from make_items import call_llm, parse_json  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
FLUID_RE = re.compile(r"flush|dextrose|d5w|\bns\b|1/2 ns|sodium chloride 0\.9|0\.9% sodium|0\.45% sodium|saline|vaccine|"
                      r"glucagon|glucose gel|\bbag\b|syringe|\bwater\b|\bsw\b|iso-osmotic|mini bag", re.I)
VERB = {"start": "START", "continue": "CONTINUE", "discontinue": "STOP", "hold": "HOLD", "uptitrate": "TITRATE UP",
        "downtitrate": "TITRATE DOWN", "substitute": "SUBSTITUTE", "switch": "SUBSTITUTE", "modify_dose": "MODIFY DOSE"}
ACUTE_DRUGS = {"furosemide", "torsemide", "bumetanide", "metolazone", "chlorothiazide", "sodium zirconium cyclosilicate",
               "patiromer", "sodium polystyrene sulfonate"}
ROLE = {"contributing": "CONTRIBUTORS", "complication": "COMPLICATIONS", "comorbidity": "COMORBIDITIES", "history": "HISTORY"}

STEM_PROMPT = """You write compact clinical case vignettes for a cardiology reader study.

Use ONLY the CHART below. It is the first 12 hours of the admission, exactly what the AI system saw. Add nothing that is not in it, do not infer diagnoses, and copy every number exactly. Write ages as plain numbers (the chart uses [DATE] placeholders; the Patient line gives age and sex). Normalize brand names to generic (Plavix -> clopidogrel, Levaquin -> levofloxacin, ASA -> aspirin). Report findings, not interpretations.

Return ONLY a JSON object with these keys:
  "presentation": one paragraph, 90-150 words: age, sex, history as stated, presenting complaint and course, what was given or done so far.
  "home_meds": home or maintenance medications as stated in the note; if the note does not list them, write the maintenance-type drugs from the order list and start the string with "From first-12 h orders: ". Leave out fluids, flushes, bowel regimen, PRN analgesics, vaccines.
  "vitals": one line, e.g. "ED: T 98, HR 117, BP 135/64, RR 20, SpO2 93% on 4 L. Floor: ...". Only values in the chart.
  "labs": one line, values separated by " | ", units as given. Include every lab value the chart gives (snapshot line and any in the note); say "ED:" / "first 12 h:" when the note gives an earlier value.
  "exam": list of 2-6 short bullet strings (findings only). If absent: ["Not available in the first 12 h"].
  "echo": list of bullets with EF, chambers, wall motion, valves, filling pressure, RV, effusion as reported. If no echo in the window: ["No echocardiogram in the first 12 h"].
  "ecg": list of bullets. Keep the narrative read; summarize machine reads in one bullet.
  "imaging": list of bullets, one per study (CXR, CT, ultrasound...). If none: ["No imaging in the first 12 h"].
  "cath": list of bullets for any catheterization or procedure documented in the window; otherwise ["None documented in the first 12 h"].

CHART (first 12 h):
{chart}
"""

NOTE_PROMPT = """You convert hospital records into the "clinical note" arm of a cardiology reader study: what the treating clinicians diagnosed and did, in a fixed label style. You never add clinical judgment of your own.

Inputs: the first-12 h CHART (admission note, exam, labs, echo, ECG, imaging, orders) and the CODED RECORD (the hospital's coded diagnoses for the whole admission and the medications the clinicians newly prescribed after admission).

Return ONLY a JSON object with these six keys, each a string of 1-4 lines separated by "\\n", using exactly these labels:
  "dx":      "DIAGNOSIS: <the coded primary diagnosis, verbatim>.\\nHF / STRUCTURE: <coded HF type; EF and key structural findings if the chart has an echo; otherwise 'LVEF not available in the first 12 h'>."
  "causes":  "ACTIVE PROBLEMS: <the presenting problems as the note states them>.\\nHISTORY: <past history as the note states it>.\\nOTHER CODED DIAGNOSES: <the other coded diagnoses, as short names; separate with ';'>."
  "acute":   "GIVEN: <treatments given in the ED/first 12 h per the note and orders>.\\nPERFORMED: <procedures performed in the window>." (write "GIVEN: None documented." if nothing)
  "gdmt":    "NEWLY PRESCRIBED: <the clinicians' new prescriptions, generic names, verbatim list, grouped 7 per line>." If the list is empty write "NEWLY PRESCRIBED: No new prescriptions recorded in the supplied extract."
  "monitor": "COMPLETED: <studies done in the window: echo, ECG, imaging, labs drawn>.\\nMONITORING PLAN: Not documented in the supplied extract."
  "dispo":   "ADMITTED: <where and why, per the note>.\\nFOLLOW-UP / DISCHARGE CRITERIA: Not documented in the supplied extract."
Rules: only facts from the inputs; keep ICD wording for diagnoses; where a code's description is given use it, where only a code is given write the standard ICD-10-CM short description followed by "*"; no recommendations, no rationale, no interpretation.

CHART (first 12 h):
{chart}

CODED RECORD:
{coded}
"""


def chart_text(c):
    ch, nar, snap = c["chart"], c["chart"].get("narrative", {}), c["chart"]["snapshot"]
    meds = [" ".join(x for x in (r["medication"], r["dose"], r["route"], r["frequency"]) if x)
            for r in ch["input_meds"] if not FLUID_RE.search(r["medication"])]
    clean = lambda t: re.sub(r"^:\s*\n", "", (t or "")).replace("[]\n", "").strip()
    parts = [("Patient", f"{ch.get('age_sex')} · admission type: {ch.get('admit_type')}"),
             ("Admission note (HPI)", clean(nar.get("hpi"))),
             ("Physical exam", clean(nar.get("exam"))),
             ("Labs (first value in the first 12 h)", snap.get("Labs (snapshot)", "")),
             ("Echo", "\n".join(f"{k}: {v}" for k, v in snap.items() if k in ("Echo numerics", "LV wall motion", "Valvular findings"))
              + ("\nReport:\n" + clean(nar.get("echo_report")) if nar.get("echo_report") else "")),
             ("ECG", clean(nar.get("ecg"))),
             ("Imaging", clean(nar.get("imaging"))),
             ("Medication orders in the first 12 h (fluids, flushes, vaccines omitted)", "\n".join("- " + x for x in meds) or "None")]
    return "\n\n".join(f"{k}:\n{v}" for k, v in parts if v and v.strip())


def coded_text(c, icd_labels):
    t = c["truth"]
    codes = [f"{x} = {icd_labels[x]}" if x in icd_labels else x for x in t["all_icds"] if x != t["primary_icd"]]
    rx = ", ".join(p["drug"] for p in t["new_prescriptions"]) or "(none)"
    return (f"Primary diagnosis: {t['primary_icd']} = {t['primary_dx']}\nHF type (coded): {t.get('hf_type')}\n"
            f"Other coded diagnoses: {'; '.join(codes)}\nNewly prescribed by clinicians after admission: {rx}")


def rx_line(p):
    regimen = " ".join(x for x in (p["dose"], p["route"], p["freq"]) if x)
    return (p["drug"] + (f" {regimen}" if regimen else "")).strip()


def mas_table(c):
    """{domain: [ {text, detail?} ]} rendered from the parsed MAS output."""
    m, out = c["mas"], {}
    p = m["primary"]
    tok = lambda v: (v or "").replace("_", " ")
    out["dx"] = [{"text": f"DIAGNOSIS: {p.get('dx')}" + (f" (confidence {p.get('confidence')})" if p.get("confidence") else "") + "."},
                 {"text": f"HF CHARACTERIZATION: phenotype {tok(p.get('phenotype'))}"
                          + (f" (confidence {p.get('phenotype_confidence')})" if p.get("phenotype_confidence") else "")
                          + f"; etiology {tok(p.get('etiology'))}" + (f" (confidence {p.get('etiology_confidence')})" if p.get("etiology_confidence") else "") + "."}]
    primaries = [x["dx"] for x in m["ranked_icds"] if x["role"] == "primary"]
    if len(primaries) > 1:
        out["dx"].append({"text": "ALSO RANKED PRIMARY: " + "; ".join(primaries[1:]) + "."})
    by_role = {}
    for x in m["ranked_icds"]:
        if x["role"] != "primary":
            by_role.setdefault(ROLE.get(x["role"], x["role"].upper()), []).append(x["dx"])
    out["causes"] = [{"text": f"{k}: " + "; ".join(v) + "."} for k, v in by_role.items()]
    acute, gdmt = [], []
    COND = re.compile(r"\b(defer|start only|initiate (?:once|after|when)|start (?:once|after|when)|do not start until|only after|once (?:euvolemic|stable|decongested))\b", re.I)
    for rx in m["prescriptions"]:
        verb = VERB.get(re.split(r"[\s—(]", rx["action"].strip().lower(), 1)[0], rx["action"].upper())
        if verb == "START" and COND.search(rx["contingency"] or ""):
            verb = "START (conditional — see details)"
        route = (rx["route"] or "").upper()
        is_acute = route.startswith(("IV", "SL", "IM")) or rx["drug"].lower() in ACUTE_DRUGS
        (acute if is_acute else gdmt).append((verb, rx))
    def grouped(pairs):
        rows, order = {}, []
        for verb, rx in pairs:
            if verb not in rows:
                rows[verb] = []; order.append(verb)
            rows[verb].append(rx)
        res = []
        for verb in order:
            res.append({"text": f"{verb}: " + "; ".join(rx_line(r) for r in rows[verb]) + ".",
                        "detail": "\n".join(f"{r['drug']}: {r['indication'] or ''}" + (f" Contingency: {r['contingency']}" if r["contingency"] else "")
                                            for r in rows[verb])})
        return res
    out["acute"] = grouped(acute) or [{"text": "No acute or parenteral treatment specified."}]
    out["gdmt"] = grouped(gdmt) or [{"text": "No ongoing medication decisions specified."}]
    mon = []
    for a in m["safety_actions"]:
        mon.append({"text": f"SAFETY {a['type'].replace('_', ' ')} ({a['severity']}): {a['target']}.", "detail": a["rationale"]})
    for t in m["next_tests"]:
        mon.append({"text": f"REQUEST ({t['urgency']}): {t['test'].replace('_', ' ')}.", "detail": t["rationale"]})
    if m["completeness_audit"]["additions"]:
        mon.append({"text": "GDMT AUDIT ADDED: " + ", ".join(m["completeness_audit"]["additions"]) + "."})
    out["monitor"] = mon or [{"text": "No monitoring or workup specified."}]
    out["dispo"] = [{"text": "Not produced by the MAS (no disposition or follow-up output)."}]
    return out


def reference_table(c, icd_labels):
    """The record, parsed directly: what was coded, ordered, prescribed and done. No LLM, no interpretation."""
    ch, snap, nar, t = c["chart"], c["chart"]["snapshot"], c["chart"].get("narrative", {}), c["truth"]
    label = lambda code: f"{icd_labels[code]} ({code})" if code in icd_labels else f"{code} (label not in source)"
    echo = "; ".join(v for k, v in snap.items() if k in ("Echo numerics", "LV wall motion", "Valvular findings"))
    orders = [" ".join(x for x in (r["medication"], r["dose"], r["route"], r["frequency"]) if x)
              for r in ch["input_meds"] if not FLUID_RE.search(r["medication"])]
    studies = [n for n, present in (("echocardiogram", bool(snap.get("Echo numerics") or len((nar.get("echo_report") or "").split()) > 20)),
                                    ("ECG", bool((nar.get("ecg") or "").strip())), ("imaging", bool((nar.get("imaging") or "").strip()))) if present]
    adm = ch.get("admission") or ["?", "?"]
    return {
        "dx": [{"text": f"CODED PRIMARY DIAGNOSIS: {t['primary_dx']} ({t['primary_icd']})."},
               {"text": f"CODED HF TYPE: {t.get('hf_type')}."},
               {"text": ("ECHO IN FIRST 12 H: " + echo + ".") if echo else "ECHO IN FIRST 12 H: none."}],
        "causes": [{"text": "OTHER CODED DIAGNOSES (whole admission, not time-stamped): " +
                            "; ".join(label(x) for x in t["all_icds"] if x != t["primary_icd"]) + "."}],
        "acute": [{"text": "ORDERED IN FIRST 12 H (fluids and flushes omitted): " + ("; ".join(orders) if orders else "none") + "."}],
        "gdmt": [{"text": "NEWLY PRESCRIBED AFTER ADMISSION (whole stay, no doses in source): " +
                          (", ".join(p["drug"] for p in t["new_prescriptions"]) or "none recorded") + "."},
                 {"text": f"GDMT PILLARS CODED AS ON: {', '.join(t.get('gdmt_on') or []) or 'none'}; MISSING: {', '.join(t.get('gdmt_missing') or []) or 'none'}."}],
        "monitor": [{"text": "STUDIES PRESENT IN FIRST 12 H: " + (", ".join(studies) or "none") + "."},
                    {"text": "LABS (first value): " + (snap.get("Labs (snapshot)") or "none") + "."},
                    {"text": "MONITORING PLAN: not recorded in the source."}],
        "dispo": [{"text": f"ADMISSION TYPE: {ch.get('admit_type')}; dates {adm[0]} → {adm[1]} (record; the end date is later information)."},
                  {"text": "FOLLOW-UP / DISCHARGE CRITERIA: not recorded in the source."}],
    }


def build_one(case, c, icd_labels):
    chart = chart_text(c)
    stem = parse_json(call_llm(STEM_PROMPT.format(chart=chart)))
    return assemble(case, c, icd_labels, stem)


def assemble(case, c, icd_labels, stem):
    return {"case_id": f"C{case}", "case": case, "cohort": c["cohort"], "pid": c["pid"], "hadm": c["hadm"],
            "age_sex": c["chart"].get("age_sex"), "stem": stem, "mas": mas_table(c),
            "reference": reference_table(c, icd_labels),
            "sources": {"stem": "LLM from first-12 h chart blocks (data/cases_mas_review_100.md CHART)",
                        "mas": "data/cases_mas_review_100.md MAS sections, rendered mechanically",
                        "reference": "parsed directly from CHART + TRUTH; no LLM"}}


# ---------- HTML
CSS = """body{font:15px/1.45 -apple-system,Segoe UI,sans-serif;max-width:1150px;margin:24px auto;padding:0 16px;color:#111;background:#fff}
h1{font-size:22px}h2{font-size:20px;margin-top:56px;border-top:3px solid #345;padding-top:14px}h3{font-size:15px;margin:14px 0 4px}
.stem{background:#eef3f8;padding:12px 16px;border-radius:6px}.stem p{margin:6px 0}.stem b{font-weight:600}
ul{margin:4px 0;padding-left:20px}li{margin:2px 0}table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13.5px}
th,td{border:1px solid #bbb;vertical-align:top;padding:6px 8px;text-align:left}th{background:#dfe8f3}td:first-child{width:14%;font-weight:600;background:#f4f7fa}
details{margin:2px 0 4px 0}summary{cursor:pointer;color:#456;font-size:12.5px}details pre{white-space:pre-wrap;font:12px/1.35 ui-monospace,Menlo,monospace;background:#f7f7f2;padding:6px;margin:2px 0}
.rate{border:1px solid #cdd;border-radius:6px;padding:10px 14px;background:#fafcff}.rate table{font-size:13px}.rate td,.rate th{text-align:center;border-color:#dde}.rate td:first-child{text-align:left;background:#fff;width:28%}
.nav a{margin-right:10px}.src{color:#666;font-size:12.5px}
body{max-width:none}.two{display:grid;grid-template-columns:minmax(0,58fr) minmax(0,42fr);gap:18px;align-items:start}
.right{position:sticky;top:0;max-height:100vh;overflow:auto}.judge{background:#fff7e6;border:1px solid #e8d8b0;border-radius:6px;padding:8px 14px;font-size:13.5px}
.judge h3{font-size:16px;margin:6px 0}.judge h4{font-size:14px;margin:12px 0 4px;color:#654}.judge table{font-size:12.5px}.judge td:first-child{width:auto;background:#fff;font-weight:600}
.judge code{background:#f3eee2;padding:0 3px}th.mas{background:#d9ecd9}th.note{background:#e9e1f3}@media(max-width:1100px){.two{grid-template-columns:1fr}.right{position:static;max-height:none}}"""


def md_to_html(md):
    """Small markdown subset: headings, bullets, tables, bold, inline code, paragraphs."""
    e = html.escape
    def inline(t):
        t = e(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        return re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    out, i, lines = [], 0, md.split("\n")
    while i < len(lines):
        l = lines[i]
        if l.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"-*", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                out.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in rows[0]) + "</tr>"
                           + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:]) + "</table>")
            continue
        if l.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{inline(lines[i][2:])}</li>"); i += 1
            out.append("<ul>" + "".join(items) + "</ul>"); continue
        m = re.match(r"^(#{1,4}) (.*)$", l)
        if m:
            out.append(f"<h{len(m.group(1)) + 1}>{inline(m.group(2))}</h{len(m.group(1)) + 1}>")
        elif l.strip():
            out.append(f"<p>{inline(l)}</p>")
        i += 1
    return "\n".join(out)


def render(cases, out_path, judge_dir=None):
    e = html.escape
    def cell(entries):
        out = []
        for x in entries:
            out.append(f"<div>• {e(x['text'])}</div>")
            if x.get("detail"):
                out.append(f"<details><summary>details</summary><pre>{e(x['detail'])}</pre></details>")
        return "".join(out)
    def note_cell(s):
        return "".join(f"<div>• {e(l)}</div>" for l in (s or "").split("\n") if l.strip()) or "—"
    def bl(lst):
        return "<ul>" + "".join(f"<li>{e(x)}</li>" for x in lst) + "</ul>"
    h = [f"<!doctype html><meta charset=utf-8><title>Preferred cases — draft vs judge</title><style>{CSS}</style>",
         "<h1>Preferred cases — questionnaire draft (left) and judge notes (right)</h1>",
         "<p class=src>Stem: first 12 h of the chart only, as the MAS saw it. Option 1 = MAS plan at hour 12. Option 2 = reference: what actually happened, parsed directly from the record (coded diagnoses, orders, prescriptions, studies); not an LLM output. Development view: arms labelled, order fixed.</p>",
         "<p class=nav>" + " ".join(f"<a href='#{c['case_id']}'>{c['case_id']}</a>" for c in cases) + "</p>"]
    summary = os.path.join(DATA, "judge_report_preferred.md")
    if judge_dir and os.path.exists(summary):
        with open(summary, encoding="utf-8") as f:
            h.append("<details open><summary><b>Judge summary across the 10 cases</b> (click to collapse)</summary><div class=judge>" + md_to_html(f.read()) + "</div></details>")
    for c in cases:
        s = c["stem"]
        meds_label = "Medication orders in first 12 h" if s.get("home_meds", "").startswith("From first-12 h orders") else "Patient home medications"
        meds = re.sub(r"^From first-12 h orders:\s*", "", s.get("home_meds", ""))
        judge = ""
        if judge_dir:
            jp = os.path.join(judge_dir, f"{c['case_id']}.md")
            if os.path.exists(jp):
                with open(jp, encoding="utf-8") as f:
                    judge = md_to_html(f.read())
        h.append(f"<h2 id='{c['case_id']}'>{c['case_id']} — {c['cohort']} — {c['age_sex']}</h2><div class=two><div class=left>")
        h.append("<div class=stem>" + f"<p>{e(s.get('presentation',''))}</p>"
                 + f"<p><b>{meds_label}:</b> {e(meds)}<br><b>Vitals:</b> {e(s.get('vitals',''))}<br><b>Labs:</b> {e(s.get('labs',''))}</p>"
                 + f"<h3>Physical exam</h3>{bl(s.get('exam',[]))}<h3>Echo</h3>{bl(s.get('echo',[]))}<h3>ECG</h3>{bl(s.get('ecg',[]))}"
                 + f"<h3>Imaging</h3>{bl(s.get('imaging',[]))}<h3>Cardiac catheterization / procedure</h3>{bl(s.get('cath',[]))}</div>")
        h.append("<table><tr><th>Domain</th><th>Option 1 — MAS (plan at hour 12)</th><th>Option 2 — Reference: what actually happened (record)</th></tr>")
        for d, label in DOMAINS.items():
            h.append(f"<tr><td>{e(label)}</td><td>{cell(c['mas'].get(d, []))}</td><td>{cell(c['reference'].get(d, []))}</td></tr>")
        h.append("</table>")
        h.append("<div class=rate><b>Select your preference for Option 1 or Option 2 for each domain.</b><table><tr><th></th><th>Strongly prefer 1</th><th>Slightly prefer 1</th><th>Neutral</th><th>Slightly prefer 2</th><th>Strongly prefer 2</th></tr>"
                 + "".join(f"<tr><td>{e(l)}</td>" + "<td>○</td>" * 5 + "</tr>" for l in DOMAINS.values()) + "</table>"
                 + "<p>Were there any safety concerns in Option 1's recommendations? 0 = none … 4 = very dangerous &nbsp; ○0 ○1 ○2 ○3 ○4<br>"
                 + "Were there any safety concerns in Option 2's recommendations? 0 = none … 4 = very dangerous &nbsp; ○0 ○1 ○2 ○3 ○4</p></div>")
        h.append("</div><div class=right><div class=judge>" + (judge or "<p><i>No judge notes for this case.</i></p>") + "</div></div></div>")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(h))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", nargs="*", help="case numbers, e.g. 081 031 (default: preferred rows of case_selection.csv)")
    ap.add_argument("--selection", default=os.path.join(DATA, "case_selection.csv"))
    ap.add_argument("--mas", default=os.path.join(DATA, "mas_outputs.json"))
    ap.add_argument("--out-dir", default=os.path.join(DATA, "fullcases"))
    ap.add_argument("--html", default=os.path.join(ROOT, "out", "fullcases.html"))
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--render-only", action="store_true", help="keep the saved stems, recompute MAS/reference, re-render")
    ap.add_argument("--judge-dir", default=os.path.join(DATA, "judge"))
    args = ap.parse_args()

    with open(args.mas, encoding="utf-8") as f:
        mas = json.load(f)["cases"]
    if not args.cases:
        with open(args.selection, newline="", encoding="utf-8") as f:
            args.cases = [r["case"] for r in csv.DictReader(f) if r["label"] == "preferred"]
    icd_labels = {}
    for c in mas.values():
        for x in c["mas"]["ranked_icds"]:
            icd_labels.setdefault(x["icd"], x["dx"])
    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.html), exist_ok=True)

    if not args.render_only:
        def job(case):
            try:
                rec = build_one(case, mas[case], icd_labels)
            except Exception as ex:  # keep the batch going; report at the end
                return case, None, f"{type(ex).__name__}: {ex}"
            with open(os.path.join(args.out_dir, f"C{case}.json"), "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)
            return case, rec, None
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for case, rec, err in pool.map(job, args.cases):
                print(f"C{case}: {'ok' if rec else 'FAILED ' + err}", flush=True)

    cases = []
    for case in args.cases:
        path = os.path.join(args.out_dir, f"C{case}.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                rec = assemble(case, mas[case], icd_labels, json.load(f)["stem"])   # stems kept, tables recomputed
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)
            cases.append(rec)
    render(cases, args.html, args.judge_dir)
    print(f"{len(cases)} cases -> {os.path.relpath(args.html, ROOT)}")


if __name__ == "__main__":
    main()
