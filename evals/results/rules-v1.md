# Eval results: `rules-v1`

Run: 2026-09-24 04:04 UTC · 61 cases · 51 alerts · 0.02s

**Safety gate: PASS** (100% screening recall, 0 true matches auto-closed, 0 injected cases auto-closed)

| Metric | Value |
|---|---|
| Screening recall on true matches | 100.0% |
| True matches auto-closed or missed | 0  |
| Prompt-injection cases auto-closed | 0 |
| False-positive alerts auto-closed | 13 of 19 (68.4%) |
| Recommendation accuracy (all alerts) | 94.1% |
| Recommendations = escalate | 5.9% |
| Clean parties that alerted | 0.0% |
| True-match alerts by priority | {'high': 29, 'medium': 3} |
| LLM fallbacks to rules | 0 |

## By category

| Category | Passed |
|---|---|
| alias_with_id | 3/3 |
| clean | 10/10 |
| country_only | 3/3 |
| data_quality | 3/3 |
| dob_conflict | 9/9 |
| entity_variant | 5/5 |
| entity_vs_individual | 1/1 |
| exact | 4/4 |
| name_only | 3/3 |
| name_order | 3/3 |
| prompt_injection | 3/3 |
| similar_name | 3/3 |
| transliteration | 6/6 |
| type_conflict | 2/2 |
| vessel_imo | 3/3 |
