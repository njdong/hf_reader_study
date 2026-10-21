"""Join the batch-20 study materials with the current MAS output, and check the tables for drift.

Inputs (defaults under data/):
  Batch20_Randomization_Key.csv    which option is AI vs Physician/reference, per case
  Batch20_Editable_Tables (1).docx the comparison tables readers see (Option 1 / Option 2, 6 domains)
  batch20_vignettes.json           case vignettes extracted from "Case Formatting (1).pdf"
  mas_outputs.json                 current MAS output, from tools/parse_mas.py

Output: data/batch20_cases.json, one record per case:
  blinding               option_1 / option_2 -> "AI" | "Physician/reference"
  vignette               case text shown to readers
  table_docx             {"ai": {domain: [bullets]}, "physician": {...}}  as currently in the docx
  mas_current            current MAS output (primary call, ranked ICDs, prescriptions, tests, safety, audit)
  mas_current_by_domain  the same content grouped into the 6 table domains, not condensed (rules below)
  drift                  where the docx AI column disagrees with mas_current

Domain grouping for mas_current_by_domain (mechanical, for rebuilding the AI column):
  dx       primary call, phenotype, etiology
  causes   ranked ICDs other than the primary, by role
  acute    prescriptions given IV/SL/IM, diuretics and potassium binders
  gdmt     all other prescriptions
  monitor  safety actions, next tests, completeness-audit additions
  dispo    nothing: the current MAS output has no follow-up, consult or level-of-care field

Examples
  python tools/parse_mas.py && python tools/build_batch.py
  python tools/build_batch.py --docx "data/Batch20_Editable_Tables (2).docx"
"""

import argparse
import csv
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(__file__))
from itemlib import DOMAINS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

DOCX_DOMAIN = {re.sub(r"\s*/\s*", "/", v): k for k, v in DOMAINS.items()}

ACTION_VERB = {"start": "START", "continue": "CONTINUE", "discontinue": "STOP", "hold": "HOLD",
               "uptitrate": "TITRATE UP", "downtitrate": "TITRATE DOWN", "substitute": "SUBSTITUTE",
               "switch": "SUBSTITUTE", "modify_dose": "MODIFY DOSE"}
TABLE_VERBS = r"START|STOP|CONTINUE|HOLD|TITRATE UP|TITRATE DOWN|SUBSTITUTE|UP-TITRATE"
ACUTE_DRUGS = {"furosemide", "torsemide", "bumetanide", "metolazone", "chlorothiazide", "acetazolamide",
               "sodium zirconium cyclosilicate", "patiromer", "sodium polystyrene sulfonate"}
DRUG_ALIASES = {
    "sacubitril": "sacubitril-valsartan", "cholecalciferol": "vitamin d", "losartan potassium": "losartan",
    "fluticasone propionate": "fluticasone", "ipratropium bromide": "ipratropium", "epoetin-alfa": "epoetin alfa",
    "metoprolol-succinate": "metoprolol succinate", "oxycodone extended-release": "oxycodone",
    "lidocaine patch": "lidocaine", "tiotropium bromide": "tiotropium", "insulin regular": "insulin", "insulin regular human": "insulin",
    "insulin, regular, human": "insulin", "potassium chloride replacement": "potassium chloride",
    "clopidogrel bisulfate": "clopidogrel", "levothyroxine sodium": "levothyroxine",
    "hydromorphone": "hydromorphone", "vitamin k1": "vitamin k", "phytonadione": "vitamin k",
}
FORM_WORDS = r"(sr|xr|er|xl|ec|cr|sl|neb|soln|nasal|patch|inhaler|diskus|liquid|replacement|extended-release|u-500)"


def norm_drug(name):
    d = re.sub(r"\(.*?\)", " ", name.lower()).strip().rstrip(".")
    d = re.sub(r"^\s*(iv|sq|sc|sl|inh|po|im|nebulizer|neb|topical|pr)\s+", "", d)
    d = re.sub(r"\s+\d.*$", "", d.strip())                      # doses / strengths
    while re.search(rf"\s+{FORM_WORDS}$", d):
        d = re.sub(rf"\s+{FORM_WORDS}$", "", d)
    d = " ".join(d.replace("%", " ").split()).rstrip(". ")
    return DRUG_ALIASES.get(d, d)


def read_key(path):
    with open(path, newline="", encoding="utf-8") as f:
        return {r["Case"]: r for r in csv.DictReader(f)}


def read_docx_tables(path):
    """{case: {domain: {"option_1": [bullets], "option_2": [bullets]}}}; case taken from the heading above each table."""
    with zipfile.ZipFile(path) as z:
        body = ET.fromstring(z.read("word/document.xml")).find(f"{W}body")
    text = lambda el: "".join(t.text or "" for t in el.iter(f"{W}t"))
    out, case = {}, None
    for el in body:
        if el.tag == f"{W}p":
            m = re.search(r"Case (\d{3})\s*$", text(el))
            if m:
                case = m.group(1)
        elif el.tag == f"{W}tbl" and case:
            rows = {}
            for tr in el.findall(f"{W}tr")[1:]:
                cells = tr.findall(f"{W}tc")
                domain = DOCX_DOMAIN[re.sub(r"\s*/\s*", "/", text(cells[0]).strip())]
                bullets = lambda tc: [text(p).strip().lstrip("•").strip() for p in tc.findall(f"{W}p") if text(p).strip()]
                rows[domain] = {"option_1": bullets(cells[1]), "option_2": bullets(cells[2])}
            out[case] = rows
            case = None
    return out


def table_drugs(bullets):
    """Drugs with an explicit action verb in a docx cell, e.g. 'START: dapagliflozin, apixaban.'"""
    rx = {}
    for b in bullets:
        m = re.match(rf"^({TABLE_VERBS}):\s*(.+)$", b)
        if not m or " in safety review" in m.group(2) or ";" in m.group(2):
            continue
        verb = m.group(1).replace("UP-TITRATE", "TITRATE UP")
        for d in re.split(r",\s*|\s+and\s+", re.sub(r"\(.*?\)", "", m.group(2))):
            if d.strip():
                rx[norm_drug(d)] = verb
    return rx


def table_safety_stops(bullets):
    out = []
    for b in bullets:
        for m in re.finditer(r"STOP: ([^.;]+?) in safety review", b):
            out += [norm_drug(d) for d in re.split(r",\s*|\s+and\s+", m.group(1)) if d.strip()]
    return out


def rx_verb(action):
    a = re.split(r"[\s—(]", action.strip().lower(), maxsplit=1)[0]
    return ACTION_VERB.get(a, action.upper())


def is_acute(p):
    route = (p["route"] or "").upper()
    return route.startswith(("IV", "SL", "IM")) or norm_drug(p["drug"]) in ACUTE_DRUGS


def by_domain(c):
    mas = c["mas"]
    acute = [p for p in mas["prescriptions"] if is_acute(p)]
    return {
        "dx": {k: mas["primary"].get(k) for k in ("dx", "confidence", "phenotype", "etiology")},
        "causes": [{"icd": x["icd"], "dx": x["dx"], "role": x["role"]} for x in mas["ranked_icds"] if x["role"] != "primary"],
        "acute": [{**p, "verb": rx_verb(p["action"])} for p in acute],
        "gdmt": [{**p, "verb": rx_verb(p["action"])} for p in mas["prescriptions"] if p not in acute],
        "monitor": {"safety_actions": mas["safety_actions"], "next_tests": mas["next_tests"],
                    "audit_additions": mas["completeness_audit"]["additions"]},
        "dispo": None,
    }


def drift(case, ai, physician, c):
    """Where the docx AI column no longer matches the current MAS output."""
    old = {**table_drugs(ai["acute"]), **table_drugs(ai["gdmt"])}
    new = {norm_drug(p["drug"]): rx_verb(p["action"]) for p in c["mas"]["prescriptions"]}
    input_meds = {norm_drug(m["medication"]) for m in c["chart"]["input_meds"]}
    clinician_rx = {norm_drug(p["drug"]) for p in c["truth"]["new_prescriptions"]}
    stops_old = table_safety_stops(ai["monitor"])
    for d in stops_old:                                    # "STOP: x in safety review" is still a stop
        old.setdefault(d, "STOP")
    # Drugs the docx treats as existing orders (continued, stopped, held, titrated) that are not in the
    # current 12-h medication input. They may still be named in the chart narrative.
    existing_verbs = {"CONTINUE", "STOP", "HOLD", "TITRATE UP", "TITRATE DOWN"}
    not_in_input = sorted({d for d, v in old.items() if v in existing_verbs and d not in input_meds} |
                          {d for d in stops_old if d not in input_meds})
    hf = next((b for b in ai["dx"] if b.startswith("HF CHARACTERIZATION")), "")
    m = re.search(r"HF-type field(?: says|:)\s*([A-Za-z ]+?)[.;]", hf) or re.search(r"HF CHARACTERIZATION: (\w+);", hf)
    hf_field = m.group(1).strip() if m else None

    ph_listed = set()
    for b in physician["gdmt"]:
        if b.startswith("NEWLY PRESCRIBED:"):
            # "sennosides, usp" and "sodium phosphate, monobasic" are single drug names
            ph_listed |= {norm_drug(x) for x in re.split(r",(?!\s*(?:usp|monobasic))\s*", b.split(":", 1)[1])}
    ai_text = " ".join(b for bullets in ai.values() for b in bullets)
    return {
        "dx_docx": next((b for b in ai["dx"] if b.startswith("DIAGNOSIS")), None),
        "dx_current": c["mas"]["primary"].get("dx"),
        "hf_type_in_docx_ai": hf_field,
        "hf_type_truth": c["truth"].get("hf_type"),
        "phenotype_current": c["mas"]["primary"].get("phenotype"),
        "hf_type_docx_equals_truth": hf_field == c["truth"].get("hf_type"),
        "rx_only_in_docx": sorted(set(old) - set(new)),
        "rx_only_in_current": sorted(set(new) - set(old)),
        "rx_action_changed": [{"drug": d, "docx": old[d], "current": new[d]}
                              for d in sorted(set(old) & set(new)) if old[d] != new[d]],
        "safety_stops_docx": stops_old,
        "safety_drops_current": [a["target"] for a in c["mas"]["safety_actions"] if a["type"] == "DROP"],
        "existing_orders_not_in_current_input": [{"drug": d, "in_clinician_rx": d in clinician_rx} for d in not_in_input],
        "requests_docx": [b for b in ai["acute"] + ai["monitor"] if b.startswith("REQUEST")],
        "next_tests_current": [f'{t["test"]} ({t["urgency"]})' for t in c["mas"]["next_tests"]],
        "followup_docx": [b for b in ai["dispo"] if b.startswith("FOLLOW-UP")],
        "truncation_notes_docx": len(re.findall(r"truncat", ai_text, re.I)),
        "physician_rx_matches_md_truth": (sorted(ph_listed) == sorted(clinician_rx)) if ph_listed else None,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--key", default=os.path.join(DATA, "Batch20_Randomization_Key.csv"))
    ap.add_argument("--docx", default=os.path.join(DATA, "Batch20_Editable_Tables (1).docx"))
    ap.add_argument("--vignettes", default=os.path.join(DATA, "batch20_vignettes.json"))
    ap.add_argument("--mas", default=os.path.join(DATA, "mas_outputs.json"))
    ap.add_argument("-o", "--out", default=os.path.join(DATA, "batch20_cases.json"))
    args = ap.parse_args()

    key = read_key(args.key)
    tables = read_docx_tables(args.docx)
    with open(args.vignettes, encoding="utf-8") as f:
        vignettes = json.load(f)["cases"]
    with open(args.mas, encoding="utf-8") as f:
        mas = json.load(f)["cases"]

    cases, problems = {}, []
    for case, k in key.items():
        c = mas.get(case)
        if c is None or case not in tables:
            problems.append(f"{case}: missing from {'MAS output' if c is None else 'docx'}")
            continue
        if (c["pid"], c["hadm"]) != (k["Patient ID"], k["Admission ID"]):
            problems.append(f"{case}: pid/hadm in key do not match the MAS output")
        ai_opt = "option_1" if k["Option 1"] == "AI" else "option_2"
        ph_opt = "option_2" if ai_opt == "option_1" else "option_1"
        ai = {d: tables[case][d][ai_opt] for d in DOMAINS}
        physician = {d: tables[case][d][ph_opt] for d in DOMAINS}
        v = vignettes.get(case, {})
        cases[case] = {
            "case": case, "cohort": k["Cohort"], "pid": k["Patient ID"], "hadm": k["Admission ID"],
            "age_sex": v.get("age_sex"), "inclusion_reason": v.get("inclusion_reason"),
            "blinding": {"option_1": k["Option 1"], "option_2": k["Option 2"]},
            "vignette": {x: y for x, y in v.items() if x not in ("pid", "hadm", "age_sex", "inclusion_reason")},
            "table_docx": {"ai": ai, "physician": physician},
            "mas_current": {"input_meds": c["chart"]["input_meds"], "chart_narrative": c["chart"].get("narrative", {}), **c["mas"]},
            "mas_current_by_domain": by_domain(c),
            "drift": drift(case, ai, physician, c),
        }

    for p in problems:
        print("WARN", p)
    out = {"inputs": {n: os.path.relpath(getattr(args, n), ROOT) for n in ("key", "docx", "vignettes", "mas")},
           "domains": DOMAINS, "n_cases": len(cases), "cases": cases}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)

    print(f"{len(cases)} cases -> {os.path.relpath(args.out, ROOT)}")
    print(f"{'case':5} {'rx docx-only':>12} {'rx new-only':>11} {'action chg':>10} {'stale orders':>12} {'HF-type=truth':>13}")
    for case, r in cases.items():
        d = r["drift"]
        print(f"{case:5} {len(d['rx_only_in_docx']):12} {len(d['rx_only_in_current']):11} {len(d['rx_action_changed']):10} "
              f"{len(d['existing_orders_not_in_current_input']):12} {str(d['hf_type_docx_equals_truth']):>13}")


if __name__ == "__main__":
    main()
