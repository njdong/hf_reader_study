# HF reader study

Evaluators open a personal link, see their assigned cases one at a time, and every answer goes
straight to a Google Sheet. The cases, the assignments and the page are all generated from files,
so nothing is built by hand.

**Mode: whole-case comparison.** Each screen shows one case: a whole-admission chart summary
(stem), a 6-domain table comparing two management plans (the multi-agent system's plan and the
clinical-note plan from the record), a preference per domain, a 0–4 safety rating per option, a
0–4 completeness rating per option, and a comment. Option order is randomized per case per
evaluator.

## Data flow (bank v2)

```
data/cases_mas_review_100.md ─┐
mimic-iv-ext-cardiac-…/ ──────┴─ bank2_stage1.py ─▶ data/bank_v2/01_verbatim/C*.json  (spans + sha256)
                                      │ doer agents (validated 1:1 by independent agents)
                                      ▼
                             data/bank_v2/02_extracted/C*.json  (every item cites its source spans)
                                      │ bank2_align.py (deterministic rules, ALIGN_RULES.md)
                                      ▼
                             data/bank_v2/03_aligned/C*.json ── bank2_assemble.py ─▶ docs/cases.json
                                                                          │
docs/index.html ◀── docs/assignments.json ◀── schedule.py                 │
       │                                                                  ▼
       └────────────── POST per case ──▶ Apps Script (apps_script/Code.gs) ──▶ Google Sheet
```

| Path | What it is |
|---|---|
| `tools/bank2_stage1.py` | Verbatim spans per case (dataset + MAS markdown), sha256 + locator each |
| `tools/bank2_align.py` | Stage 3: deterministic language alignment (rules in `data/bank_v2/00_template/ALIGN_RULES.md`) |
| `tools/bank2_assemble.py` | Stage-3 files → `assembly/tables_v2.json` → `docs/cases.json`, with grep-guard and budget checks |
| `tools/build_study.py` | Reader of `assembly/tables_v2.json` (legacy entry point; `--cases-only` kept) |
| `tools/schedule.py` | Staged assignments (design: `data/bank_v2/schedule/DESIGN.md`): `--init`, incremental `--add`, replay-verified |
| `tools/check_deploy.py` | End-to-end deployment check (Pages, cases, assignments, backend GET/POST), stdlib only |
| `tools/import_offline.py` | "Download my answers" file → sheet rows (24 columns) |
| `tools/parse_mas.py` | MAS review markdown → `data/mas_outputs.json` (mechanical) |
| `data/case_selection.csv` | The 30 study cases |
| `docs/config.js` | Backend URL, title, intro text (cardiologist-persona reviewed), contact |
| `apps_script/Code.gs` | Receives answers, writes one row per domain |

Rebuild everything (deterministic; `docs/cases.json` is byte-identical given the same version):
```bash
python tools/bank2_stage1.py
# stage 2 is agent work recorded in data/bank_v2/02_extracted/ — do not regenerate casually
python tools/bank2_align.py && python tools/bank2_assemble.py --version <date>
python tools/schedule.py --init --evaluators 3 --per 20 --core 10 --seed 20261028 \
       --base-url https://njdong.github.io/hf_reader_study/     # or --add N later
python tools/check_deploy.py --live     # from a network that can reach script.google.com
```
Then paste the codes from `data/bank_v2/schedule/evaluators.csv` into the sheet's `evaluators` tab
and push `docs/`. After any `apps_script/Code.gs` edit: Deploy → Manage deployments → Edit →
Version: *New version* (same URL; a *New deployment* would change the URL).

## Not in git (never commit these)

- `data/` — everything under it, notably `data/bank_v2/` (the complete provenance record of the
  rebuild: template, spans, extractions, validations, manifest, schedule, instructions reviews,
  deployment logs) and `data/_prior_pilot/` (quarantined pilot artifacts, kept only for the
  recorded sanity check).
- `mimic-iv-ext-cardiac-disease-1.0.0/` — PhysioNet credentialed dataset: research use only, must
  not be shared or leave the machine.
- `out/` — scratch outputs.

`.gitignore` enforces all three; `git status` must never show anything under `data/` staged.
The provenance ceiling of the bank: medication orders (first 12 h) and the clinicians' new
prescriptions come from the MAS markdown's CHART/TRUTH blocks, which are second-hand extracts of
MIMIC-IV, because the public dataset carries no prescriptions table and no hospital course.

## One-time setup

1. **Sheet and backend**: create a Google Sheet → Extensions → Apps Script → paste
   `apps_script/Code.gs` → run `setup()` once → Deploy → New deployment → Web app
   (*Execute as* Me, *Who has access* Anyone) → copy the `/exec` URL into `docs/config.js`.
2. **Page**: push this repo; Settings → Pages → deploy branch `main`, folder `/docs`.
3. **Evaluators**: `python tools/schedule.py --init …`, push `docs/assignments.json`, paste codes
   into the `evaluators` tab, send each person their link from `evaluators.csv`.
4. **Test**: add `TEST-DEPLOY` to the `evaluators` tab, run
   `python tools/check_deploy.py --live`, then delete the TEST rows from `responses`.

## Day to day

- **Add evaluators** without touching existing queues: `python tools/schedule.py --add 2`
  (`--per 15` for a shorter queue). Push, paste the new codes into the sheet. The command prints
  the coverage plan and a budget line; keep the budget ≥ 90 if every case should reach 3 ratings
  at 50 % completion (see `data/bank_v2/schedule/DESIGN.md`).
- **Preview locally**: `python -m http.server -d docs 8000` → `http://localhost:8000/?r=DEMO`
  (with `endpoint: ""` the page runs in demo mode and shows every case).
- **Blocked networks**: hospital Wi-Fi often blocks `script.google.com`; the page stores answers
  on the device and uploads them from the next network, or the evaluator sends the
  "Download my answers" file and `tools/import_offline.py` converts it to sheet rows.

## Response columns (`responses` tab)

One row per domain per case. `choice` is as clicked (`strong_1` … `strong_2`); `score_A` maps it
to −2…+2 where **+2 = strongly prefers system A (the MAS)** — use `score_A` for analysis.
`safety_1/2` and `completeness_1/2` are per screen option; `safety_A/B` and `completeness_A/B`
are the same values mapped to systems. `left_system` says which system was Option 1.
`items_version` distinguishes question banks (bank v2 = `2026-10-28`). A resubmission adds new
rows; keep the latest per `evaluator` + `item_id`.

## Notes

- Don't change a case's text once it has ratings; rebuild with a new `--version` instead, which
  is recorded on every row as `items_version`.
- Pages needs a public repo on a free account, so `docs/` content is publicly readable. Codes
  gate submission, not reading; never publish `data/bank_v2/schedule/randomization_key.csv`.
- Pilot artifacts and tools live in `data/_prior_pilot/` and `tools/_prior_pilot/` and are not
  used by the v2 pipeline.
