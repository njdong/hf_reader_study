"""Write the batch-20 cases in the pipeline's input format, with full text and no condensing.

Input:  data/batch20_cases.json  (from tools/build_batch.py)
Output: data/cases/C<case>.json   one per case, the format make_items.py reads:
          case_id, case_text, system_a (multi-agent system), system_b (physician/reference), meta
        data/batch20_raw.md       the same content as one readable document: stem, then a
                                  6-domain table per case with MAS and physician side by side

What goes where
  case_text  the vignette from "Case Formatting (1).pdf", verbatim, in the PDF's section order, followed by
             the admission note (HPI) verbatim and the complete first-12 h medication order list, both exactly
             as the systems received them (IV fluids, flushes and vaccines left out of the list)
  system_a   the current MAS output, one line per fact (every prescription keeps dose, route,
             frequency, indication and contingency; every safety action and test keeps its rationale)
  system_b   the physician/reference column of the docx, verbatim

Domain mapping for system_a is the mechanical one from build_batch.py. The MAS has no output for
"Disposition and follow-up", so system_a.dispo is null; make_items.py still builds that item from
system_b and shows "(nothing for this domain)" for the MAS.

Condensing and highlighting happen later, in make_items.py.

Examples
  python tools/build_cases.py
  python tools/make_items.py data/cases/C0*.json --dry-run
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from itemlib import DOMAINS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

VIGNETTE_ORDER = [
    ("presentation", None),
    ("home_meds", "Patient home medications"),
    ("vitals", "Vitals"),
    ("presentation_labs", "Presentation labs"),
    ("labs", "Labs"),
    ("exam", "Physical exam"),
    ("echo", "Echo"),
    ("ecg", "ECG"),
    ("imaging", "Imaging"),
    ("cath_procedure", "Cardiac catheterization / procedure"),
]
FLUID_RE = re.compile(r"flush|dextrose|d5w|\bns\b|\b1/2 ns\b|sodium chloride 0\.9|0\.9% sodium|0\.45% sodium|saline|vaccine|"
                      r"glucagon|glucose gel|\bbag\b|syringe|\bwater\b|\bsw\b|iso-osmotic|mini bag|magnesium sulfate", re.I)
ROLE_LABEL = {"contributing": "CONTRIBUTORS", "complication": "COMPLICATIONS", "comorbidity": "COMORBIDITIES",
              "history": "HISTORY", "secondary": "SECONDARY"}


def chart_text(mas):
    """HPI verbatim plus the first-12 h order list: the common ground both plans were built on."""
    parts = []
    hpi = (mas.get("chart_narrative") or {}).get("hpi")
    if hpi:
        parts.append("Admission note (HPI), verbatim as given to both systems:\n" + hpi)
    meds = [m for m in mas["input_meds"] if not FLUID_RE.search(m["medication"])]
    if meds:
        rows = []
        for m in meds:
            rows.append("- " + " ".join(x for x in (m["medication"], m["dose"], m["route"], m["frequency"]) if x))
        parts.append("Medication orders in the first 12 h, as given to both systems (IV fluids, flushes and vaccines omitted):\n"
                     + "\n".join(rows))
    return "\n\n".join(parts)


def vignette_text(v):
    parts = []
    for key, label in VIGNETTE_ORDER:
        val = v.get(key)
        if not val:
            continue
        if isinstance(val, list):
            val = "\n".join(f"- {x}" for x in val)
        parts.append(val if label is None else f"{label}: {val}")
    return "\n\n".join(parts)


def rx_line(p):
    regimen = " ".join(x for x in (p["dose"], p["route"], p["freq"]) if x)
    line = f"{p['verb']}: {p['drug']}"
    if regimen:
        line += f" {regimen}"
    if p["indication"]:
        line += f" — {p['indication']}"
    if p["contingency"]:
        line += f" Contingency: {p['contingency']}"
    return line


def mas_text(bd, mas):
    """system_a: one string per domain from mas_current_by_domain (bd) and mas_current (mas)."""
    out = {}
    dx = bd["dx"]
    lines = [f"DIAGNOSIS: {dx['dx']}" + (f" (confidence: {dx['confidence']})" if dx.get("confidence") else "")]
    if dx.get("phenotype"):
        lines.append(f"HF PHENOTYPE: {dx['phenotype']}")
    if dx.get("etiology"):
        lines.append(f"ETIOLOGY: {dx['etiology']}")
    out["dx"] = "\n".join(lines)

    by_role = {}
    for x in bd["causes"]:
        by_role.setdefault(x["role"], []).append(f"{x['dx']} ({x['icd']})")
    out["causes"] = "\n".join(f"{ROLE_LABEL.get(role, role.upper())}: " + "; ".join(v) + "."
                              for role, v in by_role.items()) or None

    out["acute"] = "\n".join(rx_line(p) for p in bd["acute"]) or None
    out["gdmt"] = "\n".join(rx_line(p) for p in bd["gdmt"]) or None

    mon = []
    for a in bd["monitor"]["safety_actions"]:
        mon.append(f"SAFETY {a['type']} ({a['severity']}): {a['target']} — {a['rationale']}")
    for t in bd["monitor"]["next_tests"]:
        mon.append(f"REQUEST ({t['urgency']}): {t['test']} — {t['rationale']}")
    if bd["monitor"]["audit_additions"]:
        mon.append("GDMT AUDIT ADDED: " + ", ".join(bd["monitor"]["audit_additions"]) + ".")
    out["monitor"] = "\n".join(mon) or None
    out["dispo"] = None
    return out


def physician_text(table):
    return {d: ("\n".join(table[d]) or None) for d in DOMAINS}


def md_cell(text):
    return "—" if not text else text.replace("|", "\\|").replace("\n", "<br>")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--batch", default=os.path.join(DATA, "batch20_cases.json"))
    ap.add_argument("--out-dir", default=os.path.join(DATA, "cases"))
    ap.add_argument("--md", default=os.path.join(DATA, "batch20_raw.md"))
    args = ap.parse_args()

    with open(args.batch, encoding="utf-8") as f:
        batch = json.load(f)["cases"]
    os.makedirs(args.out_dir, exist_ok=True)

    md = ["# Batch 20 — raw stems and comparison tables (current MAS output)", "",
          "Stem = vignette from the case-formatting PDF, verbatim. MAS = current multi-agent output, "
          "uncondensed. Physician = reference column of the editable-tables docx, verbatim. "
          "Generated by `tools/build_cases.py`; the per-case JSON is in `data/cases/`.", ""]
    for case, c in batch.items():
        case_id = f"C{case}"
        rec = {
            "case_id": case_id,
            "case_text": vignette_text(c["vignette"]) + "\n\n" + chart_text(c["mas_current"]),
            "system_a": mas_text(c["mas_current_by_domain"], c["mas_current"]),
            "system_b": physician_text(c["table_docx"]["physician"]),
            "meta": {
                "case": case, "cohort": c["cohort"], "pid": c["pid"], "hadm": c["hadm"],
                "age_sex": c["age_sex"], "inclusion_reason": c["inclusion_reason"],
                "system_a": "multi-agent system, data/cases_mas_review_100.md",
                "system_b": "physician/reference, Batch20_Editable_Tables (1).docx",
            },
        }
        path = os.path.join(args.out_dir, f"{case_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
            f.write("\n")

        md += [f"## {case_id} — {c['cohort']} — {c['age_sex']} — pid {c['pid']} / hadm {c['hadm']}", "",
               f"*Included for:* {c['inclusion_reason']}", "", "### Stem", "",
               rec["case_text"], "", "### Table", "",
               "| Domain | MAS (system A) | Physician / reference (system B) |", "|---|---|---|"]
        for d, label in DOMAINS.items():
            md.append(f"| {label} | {md_cell(rec['system_a'][d])} | {md_cell(rec['system_b'][d])} |")
        md += ["", "---", ""]

    with open(args.md, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"{len(batch)} cases -> {os.path.relpath(args.out_dir, ROOT)}/C*.json and {os.path.relpath(args.md, ROOT)}")


if __name__ == "__main__":
    main()
