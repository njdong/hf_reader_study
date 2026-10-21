# HF reader study

Evaluators open a personal link, see their assigned items one at a time, and every answer goes straight to a Google Sheet. The question bank, the assignments and the page are all generated from files, so nothing is built by hand.

```
data/cases/*.json ──make_items.py (LLM)──▶ docs/items.json ──make_assignments.py──▶ docs/assignments.json
                                                   │                                        │
                                                   └──────────── docs/index.html ◀──────────┘
                                                                 (GitHub Pages)
                                                                       │  POST per item
                                                                       ▼
                                                        Apps Script ──▶ Google Sheet
```

| Path | What it is |
|---|---|
| `docs/index.html` | Evaluator page (served by GitHub Pages) |
| `docs/config.js` | Backend URL, title, intro text, contact line |
| `docs/items.json` | Question bank: one item = one case × one domain |
| `docs/assignments.json` | Which items each evaluator sees, and which system appears as Option 1 |
| `apps_script/Code.gs` | Receives answers and writes them to the sheet |
| `tools/make_items.py` | Case + two system outputs → items, via any OpenAI-compatible LLM endpoint |
| `tools/make_assignments.py` | Balanced assignments and personal links |
| `tools/itemlib.py` | Item schema and validator (`python tools/itemlib.py`) |
| `prompts/item_prompt.md` | The LLM prompt (stem template, condensing and highlighting rules) |
| `data/cases/C01.json` | Example of the case input format |
| `tools/parse_mas.py` | MAS review markdown (`data/cases_mas_review_100.md`) → `data/mas_outputs.json`, one structured record per case |
| `tools/build_batch.py` | Joins the batch-20 key, docx tables, vignettes and MAS output → `data/batch20_cases.json`, and reports where the docx AI column has drifted from the MAS output |
| `tools/build_cases.py` | `batch20_cases.json` → `data/cases/C<case>.json` (pipeline input, full text) and `data/batch20_raw.md` (readable stems + tables) |
| `data/batch20_ai_update_report.md` | Findings from the 2026-10-21 drift check |

Run all commands from the repo root.

## One-time setup (about 15 minutes)

**1. Google Sheet and backend**
1. Create a new Google Sheet. Open Extensions → Apps Script, replace the contents of `Code.gs` with `apps_script/Code.gs`, and save.
2. Pick `setup` in the function menu, click Run, and approve the permissions. This creates the `responses` and `evaluators` tabs.
3. Deploy → New deployment → Select type: Web app. Set *Execute as* to **Me** and *Who has access* to **Anyone**. Deploy and copy the URL ending in `/exec`.

**2. Page**
1. Paste that URL into `docs/config.js` as `endpoint`. Edit `intro` and `contact` if you like.
2. Push this folder to a GitHub repo. In the repo, open Settings → Pages, set Source to *Deploy from a branch*, choose branch `main` and folder `/docs`, and save. After about a minute the site is live at `https://USERNAME.github.io/hf_reader_study/`.

**3. Evaluators**
```bash
python tools/make_assignments.py --evaluators 12 --per 10 --base-url https://USERNAME.github.io/hf_reader_study/
```
Commit and push `docs/assignments.json`. Then paste the `code` column of `out/evaluators.csv` into column A of the `evaluators` tab. Each evaluator gets their `link` from that CSV.

**4. Test.** Open one link, submit an item, and check that a row appears in `responses`. Then delete the test row.

## Day to day

**Add cases.** Put each case in `data/cases/` in the same format as `C01.json`: the case text plus both systems' outputs, split by domain. Then run:
```bash
export LLM_BASE_URL=https://api.openai.com/v1 LLM_API_KEY=... LLM_MODEL=...   # or your own endpoint
python tools/make_items.py data/cases/*.json
```
Items are validated, and anything invalid is sent back to the LLM once with the errors. Spot-check the clinical content in `docs/items.json` before you push. To inspect the prompts without calling an LLM, use `--dry-run`, which writes them to `out/prompts/`.

**Add evaluators** without changing anyone's existing assignment:
```bash
python tools/make_assignments.py --add 3 --per 10
```
Push, and add the new codes to the `evaluators` tab.

**Preview locally:**
```bash
python -m http.server -d docs 8000      # then open http://localhost:8000/?r=DEMO
```
When `endpoint` is empty the page runs in demo mode: it shows every item, and the end screen lists the rows that would have been sent.

## Response columns (`responses` tab)

| Column | Meaning |
|---|---|
| `evaluator`, `item_id`, `case_id`, `domain` | Who rated what |
| `position` | Where the item fell in that evaluator's queue (for order effects) |
| `left_system` | Which system was shown as Option 1 (`A` = multi-agent, `B` = baseline) |
| `choice` | As clicked on screen: `strong_1` … `neutral` … `strong_2` |
| `score_A` | Same answer from −2 to +2, where **+2 = strongly prefers system A**. Use this for analysis. |
| `comment`, `seconds_on_item` | Free text; seconds the item was on screen |
| `items_version`, `page_version`, `submitted_at`, `received_at` | Provenance |

A second submission for the same item from the same evaluator adds a new row. For analysis, keep the latest row per `evaluator` + `item_id`.

## Notes

- **Option B in `docs/items.json` and `data/cases/C01.json` is placeholder text.** Replace it with real baseline output and rerun `make_items.py`.
- On a free GitHub account, Pages needs a **public** repo, so `items.json` will be publicly readable. Evaluator codes only gate who can submit; they don't hide content.
- Don't change an item's text once it has ratings. Add a new item id instead, or bump `version` in `items.json`, which is recorded with every row.
- After editing `Code.gs`, use Deploy → Manage deployments → Edit → Version: *New version*. That keeps the same URL. Creating a *New deployment* would produce a new URL.
