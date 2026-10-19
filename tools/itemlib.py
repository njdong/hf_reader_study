"""Shared item schema and validation for the HF reader study.

An item is one case x one domain. Text markup used in lead, facts and rows:
  {{text}}  key value from the fixed key set (EF, valve disease, BNP, troponin, Cr, K, Hb, QTc)
  [[text]]  part of an option that differs from the other option
Row format: [slot, system_A_text, system_B_text]
  null  -> option does not address this slot (shown as an em dash)
  "="   -> (system B only) identical to system A, shown as one merged cell
"""

import json
import re

DOMAINS = {
    "dx": "Diagnosis and HF characterization",
    "causes": "Decompensation causes and other active problems",
    "acute": "Acute treatment and decongestion",
    "gdmt": "Ongoing medication / GDMT decisions",
    "monitor": "Monitoring and further workup",
    "dispo": "Disposition and follow-up",
}

# Core slots per domain. Items may add case-specific rows, but should use these names when they apply.
CORE_SLOTS = {
    "dx": ["Diagnosis", "Etiology", "Phenotype / EF", "Hemodynamic profile"],
    "causes": ["Precipitant", "Structural", "Complications", "Comorbidities", "Other"],
    "acute": ["Diuretic", "Rate control", "Potassium", "Fluids", "Respiratory", "Antibiotics"],
    "gdmt": ["Beta-blocker", "Rate / rhythm", "ARNI / ACEi / ARB", "MRA", "SGLT2i",
             "Anticoagulation", "Potassium", "Other"],
    "monitor": ["ECG", "Labs", "Volume status", "Imaging", "Workup", "Med safety", "Procedures"],
    "dispo": ["Level of care", "Discharge criteria", "Follow-up"],
}

ID_RE = re.compile(r"^[A-Za-z0-9_]+-(dx|causes|acute|gdmt|monitor|dispo)$")


def _check_markup(text, where, errors):
    for open_, close in (("{{", "}}"), ("[[", "]]")):
        if text.count(open_) != text.count(close):
            errors.append(f"{where}: unbalanced {open_}{close} in {text!r}")
    if "{{" in re.sub(r"\{\{.+?\}\}", "", text) or "[[" in re.sub(r"\[\[.+?\]\]", "", text):
        errors.append(f"{where}: malformed markup in {text!r}")


def validate_item(it, errors):
    where = it.get("id", "<no id>")
    for key in ("id", "case", "domain", "lead", "facts", "q", "rows"):
        if key not in it:
            errors.append(f"{where}: missing '{key}'")
    if errors and errors[-1].startswith(f"{where}: missing"):
        return
    if not ID_RE.match(it["id"]):
        errors.append(f"{where}: id must look like C01-gdmt")
    if it["domain"] not in DOMAINS:
        errors.append(f"{where}: unknown domain {it['domain']!r}")
    if not it["id"].startswith(it["case"] + "-") or not it["id"].endswith("-" + it["domain"]):
        errors.append(f"{where}: id does not match case/domain")
    _check_markup(it["lead"], f"{where}.lead", errors)
    if "[[" in it["lead"]:
        errors.append(f"{where}.lead: diff markup [[ ]] is only for options")
    if not isinstance(it["facts"], list) or not it["facts"]:
        errors.append(f"{where}: facts must be a non-empty list")
    for i, f in enumerate(it["facts"]):
        if not (isinstance(f, list) and len(f) == 2 and all(isinstance(x, str) for x in f)):
            errors.append(f"{where}.facts[{i}]: must be [label, text]")
            continue
        _check_markup(f[1], f"{where}.facts[{i}]", errors)
        if "[[" in f[1]:
            errors.append(f"{where}.facts[{i}]: diff markup [[ ]] is only for options")
    if not isinstance(it["rows"], list) or not it["rows"]:
        errors.append(f"{where}: rows must be a non-empty list")
        return
    slots = set()
    for i, r in enumerate(it["rows"]):
        w = f"{where}.rows[{i}]"
        if not (isinstance(r, list) and len(r) == 3 and isinstance(r[0], str)):
            errors.append(f"{w}: must be [slot, A, B]")
            continue
        slot, a, b = r
        if slot in slots:
            errors.append(f"{w}: duplicate slot {slot!r}")
        slots.add(slot)
        if a == "=":
            errors.append(f"{w}: '=' is only allowed in the B column")
        if a is None and b is None:
            errors.append(f"{w}: both options empty; drop the row")
        if b == "=" and a is None:
            errors.append(f"{w}: '=' needs text in A")
        for label, v in (("A", a), ("B", b)):
            if v is None or v == "=":
                continue
            if not isinstance(v, str) or not v.strip():
                errors.append(f"{w}.{label}: must be text, null, or '='")
                continue
            _check_markup(v, f"{w}.{label}", errors)
            if "{{" in v:
                errors.append(f"{w}.{label}: key markup {{{{ }}}} is only for the case facts")
        if b == "=" and a and "[[" in a:
            errors.append(f"{w}: identical options should not carry diff markup")


def validate(doc):
    errors = []
    items = doc.get("items")
    if not isinstance(items, list) or not items:
        return ["items.json: 'items' must be a non-empty list"]
    seen = set()
    for it in items:
        if it.get("id") in seen:
            errors.append(f"{it.get('id')}: duplicate id")
        seen.add(it.get("id"))
        validate_item(it, errors)
    return errors


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(doc, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "docs/items.json"
    errs = validate(load(path))
    if errs:
        print("\n".join(errs))
        sys.exit(1)
    print(f"{path}: OK ({len(load(path)['items'])} items)")
