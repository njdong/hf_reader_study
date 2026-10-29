"""Shared helpers for the bank-v2 rebuild tools (stage 1, align, assemble)."""

import csv
import datetime as dt
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
BANK = os.path.join(DATA, "bank_v2")
DATASET = os.path.join(ROOT, "mimic-iv-ext-cardiac-disease-1.0.0")
MAS_MD = os.path.join(DATA, "cases_mas_review_100.md")
MANIFEST = os.path.join(BANK, "MANIFEST.json")


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_selection():
    """The 30 selected cases: list of dicts with case, pid, hadm, cohort."""
    with open(os.path.join(DATA, "case_selection.csv"), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def manifest_update(entries, producer):
    """Record/refresh manifest rows. entries = {relpath_from_ROOT: {"stage":…, "case":…}}."""
    m = {"cases_json_version": None, "files": {}}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as f:
            m = json.load(f)
    for rel, meta in entries.items():
        m["files"][rel] = dict(meta, sha256=sha256_file(os.path.join(ROOT, rel)),
                               producer=dict(producer, date=dt.date.today().isoformat()))
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1, ensure_ascii=False, sort_keys=True)
    return m


def manifest_set_version(version):
    with open(MANIFEST, encoding="utf-8") as f:
        m = json.load(f)
    m["cases_json_version"] = version
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1, ensure_ascii=False, sort_keys=True)
