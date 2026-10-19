You convert one clinical case and two AI-generated plans into ONE reader-study item for the domain "{domain_label}" (domain key: {domain}). Clinicians will read the item and state which plan they prefer for this domain. Your job is formatting and condensing only. Never judge, fix, or add clinical content.

Return ONLY a JSON object, no prose and no code fences, with these keys:
  "id": "{case_id}-{domain}"
  "case": "{case_id}"
  "domain": "{domain}"
  "domain_label": "{domain_label}"
  "lead": one line, "age+sex · key history · setting", e.g. "85M · HTN, paroxysmal AF · transferred to CCU"
  "facts": list of [label, text] pairs, 2–5 rows
  "q": the question, in board-exam style ("Which is the most appropriate …?")
  "rows": list of [slot, system_A_text, system_B_text]

STEM RULES (lead + facts)
1. Use these fact rows for this domain, in this order, skipping any the case lacks: {stem_fields}
2. Build the stem from the CASE only. Choose facts by this domain's template, NOT by what either plan mentions. Never include a fact that only appears in one plan.
3. Report findings, not interpretations (write "GB wall thickening", not "congestive hepatopathy").
4. Compact style: separate facts with " · ", use arrows for sequences, drop units for common labs (Cr 1.9, K 5.6), at most about 60 words across all facts.
5. Wrap these key values in {{{{ }}}} every time they appear, and nothing else: EF, significant valve disease, BNP, troponin, Cr, K, Hb, QTc.

OPTION RULES (rows)
6. Use these slot names when they apply: {core_slots}. Add a case-specific slot only when content fits none of them.
7. Each cell is a short phrase, ideally 12 words or fewer. Use the same verbs in both columns (Start / Stop / Continue / Hold).
8. Remove meta text and source artifacts from both plans: "not documented", "source truncated", "recorded diagnosis", rationale sentences, field labels like GIVEN or NEWLY PRESCRIBED.
9. Remove routine non-cardiac medications from both plans (PPIs, bowel regimen, eye drops, topical agents). Keep everything else, including content you think is wrong.
10. Never add anything a plan did not say. If a plan says nothing for a slot, use null. Drop a slot only if both plans are null.
11. If both plans say the same thing for a slot, put the text in column A and the string "=" in column B.
12. Mark with [[ ]] only the parts that differ between the two plans, at phrase level. Text shared by both stays unmarked.
13. Never use {{{{ }}}} inside rows.

FORMAT EXAMPLE (a different case and domain):
{example}

CASE {case_id}:
{case_text}

PLAN A (system A) for "{domain_label}":
{a_text}

PLAN B (system B) for "{domain_label}":
{b_text}
