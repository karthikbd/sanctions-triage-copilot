# Sanctions Triage Copilot

**Sanctions screening with LLM-assisted alert triage, deterministic guardrails, a tamper-evident audit trail and an evaluation suite.**

**Live demo:** https://sanctions-triage-copilot.vercel.app (Vercel + Supabase Postgres + a Docker worker on GitHub Actions; see [DEPLOY.md](DEPLOY.md))

Banks spend most of their sanctions-compliance effort closing false-positive alerts: a customer shares a name with a listed party, an analyst compares dates of birth and countries, writes a disposition note and closes it. This project automates the evidence-gathering and first-level recommendation for those alerts, and it treats safety as a design constraint rather than an afterthought:

- **A true match is never closed by a machine.** Only a human confirms or clears a real hit.
- **An alert is auto-closed only on hard, deterministic evidence** (e.g. DOB decades apart, a person vs a vessel). A confident LLM is not enough.
- **Free text is untrusted.** Payment remittance info and KYC notes are screened for prompt injection; flagged cases go to a human with high priority.
- **Every decision is reproducible and tamper-evident.** Signals are computed in code, and each event is written to a hash-chained audit log.
- **Near-real-time lists.** OFAC SDN, UN Security Council, EU and UK sanctions via [OpenSanctions](https://www.opensanctions.org/), re-checked every few hours. Only new or changed list entries are re-screened against the customer book.
- **One alert per customer per list entry.** Re-screening links to the open alert; a hit an analyst already cleared stays suppressed until the customer data or the list entry changes.

![Analyst workbench: prompt-injection case held for review](docs/screenshot-injection.png)

## What's inside

| Layer | What it does | Where |
|---|---|---|
| Screening engine | Name normalization (transliteration, honorifics, legal forms, name order), phonetic + fuzzy scoring, two-token blocking index. ~13 ms per screen against a 55k-entity / 220k-name list | `normalize.py`, `matcher.py` |
| Secondary identifiers | DOB (ranges, circa, day/month transposition), country aliases, ID/IMO numbers, party type, all computed deterministically | `signals.py` |
| Adjudicators | `rules-v1`: transparent decision table (baseline + fallback). `claude`: Claude with forced tool use, schema-validated output, retries and automatic fallback | `adjudicators/` |
| Guardrail policy | The only component that sets alert status. Small, deterministic and property-tested | `policy.py` |
| Audit | SQLite alert store + SHA-256 hash-chained audit log with `/api/audit/verify` | `store.py` |
| API + UI | FastAPI (`/api/screen`, `/batch`, `/alerts`, `/review`, `/metrics`), plus a dependency-free analyst workbench | `api.py`, `static/index.html` |
| MCP server | Work the alert queue from Claude Desktop: `screen_party`, `list_open_alerts`, `get_alert`, `record_review`, … | `mcp_server.py` |
| Lists | **OpenSanctions** (OFAC SDN, UN SC, EU FSF, UK FCDO; any dataset configurable), cached, refreshed on a schedule, with list-delta re-screening. Also the raw OFAC CSV (`stc load-ofac`) and a fictional sample list for tests | `opensanctions.py`, `watchlist.py`, `service.py` |
| Alert lifecycle | De-duplication by customer identity + list entry fingerprint; suppression of previously cleared hits; re-raise when free text shows injection | `service.py` |
| Synthetic customer book | **SDV** (Gaussian copula) learns attribute structure: segment, country, age, turnover, PEP and risk rating driven by FATF June 2026 lists. **Faker** fills in names and IDs. Planted true matches and same-name near-misses turn the book into a labelled test set | `synthetic.py` |
| Evals | 61 labelled cases across 15 failure modes, including adversarial prompt injection, plus a CI safety gate | `evals/` |

## Architecture

```mermaid
flowchart LR
  A[Customer / payment party<br/>API · CSV · MCP] --> B[Normalize<br/>names, DOB, country, IDs]
  B --> C[Screen<br/>blocking + fuzzy/phonetic]
  L[(Watchlist<br/>OFAC SDN or sample)] --> C
  C -->|candidates| D[Deterministic signals<br/>DOB · country · ID · type]
  B --> I[Injection detector<br/>on free text]
  D --> E{Adjudicator}
  E -->|rules-v1| F[Recommendation]
  E -->|Claude, forced tool use| F
  E -. error / invalid output .-> R[Rules fallback] --> F
  F --> P[Guardrail policy<br/>only component that sets status]
  I --> P
  D --> P
  P -->|hard contradiction + high confidence| AC[Auto-closed<br/>QA sampling]
  P -->|everything else| Q[Analyst queue<br/>prioritised]
  Q --> H[Human decision] --> S[(SQLite + hash-chained audit log)]
  AC --> S
```

## Quickstart

```bash
git clone <your-repo-url> && cd sanctions-triage-copilot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[mcp,dev,synth]"
cp .env.example .env          # STC_WATCHLIST=opensanctions by default

pytest -q                     # 106 tests
python evals/run_evals.py     # eval safety gate (rules baseline)
stc serve                     # http://127.0.0.1:8000  (API docs at /docs)
```

On Windows, double-click `run_windows.bat`, or open the folder in VS Code: a folder-open task starts the app.

Try the scenario chips in the UI, or call the API:

```bash
curl -s localhost:8000/api/screen -H 'content-type: application/json' \
  -d '{"name":"Muhammad Said Rashidi","party_type":"individual","dob":"14/02/1968","country":"Lebanon"}'
```

Batch-screen a file: `stc screen-file docs/sample_customers.csv --out results.csv`

### Use Claude as the adjudicator

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export STC_ADJUDICATOR=claude            # optional STC_MODEL=claude-sonnet-5
stc serve
python evals/run_evals.py --adjudicator claude    # compare against the rules baseline
```

If the API is down or returns invalid output, the service falls back to `rules-v1`, notes the fallback on the alert and keeps working.

### Screen against the real OFAC SDN list

```bash
stc load-ofac --dest data/ofac        # downloads SDN.CSV, ALT.CSV, ADD.CSV from OFAC (public)
STC_WATCHLIST=data/ofac stc serve
```

### Docker

```bash
cp .env.example .env && docker compose up --build
```

### MCP (Claude Desktop)

Add the block in `docs/claude_desktop_config.example.json` to your Claude Desktop config, then ask *"Show me the open sanctions alerts and summarise the highest priority one."*

## Evaluation results

`python evals/run_evals.py` runs the golden set through the full pipeline. CI fails if the **safety gate** fails.

**Baseline (`rules-v1`), 61 cases / 51 alerts:**

| Metric | Result |
|---|---|
| Screening recall on true matches | **100%** (32/32) |
| True matches auto-closed | **0** |
| Prompt-injection cases auto-closed | **0** (3/3 held for review) |
| False-positive alerts auto-closed | **68%** (13 of 19) |
| Recommendation accuracy | 94% |
| Clean parties that alerted | 0% |

Categories covered: exact, transliteration, name order, alias + ID, entity legal-form variants, vessel IMO, name-only payment parties, data-quality errors (transposed DOB, off-by-one year), DOB conflicts, type conflicts, entity-vs-individual (ownership risk), country-only, similar names, clean parties and prompt injection.

> **Be honest about what this measures.** The golden set was written by the author against a fictional list, so the baseline is expected to do well on it. In a real deployment the first step is to rebuild the set from the bank's historical L1/L2 dispositions and re-measure.

## Data sources

| Source | Used for | Notes |
|---|---|---|
| [OpenSanctions](https://www.opensanctions.org/datasets/) `us_ofac_sdn`, `un_sc_sanctions`, `eu_fsf`, `gb_fcdo_sanctions` | Live watchlist | Found via each dataset's `index.json`, downloaded as `targets.simple.csv`, cached in `data/opensanctions/`, falls back to cache when offline. **Licence: CC BY-NC 4.0, free for non-commercial use; commercial use needs an OpenSanctions data licence.** |
| [FATF plenary outcomes, June 2026](https://www.fatf-gafi.org/en/publications/Fatfgeneral/outcomes-fatf-plenary-june-2026.html) | Country risk in synthetic data | Call for action: DPRK, Iran, Myanmar. 22 jurisdictions under increased monitoring (`data/fatf_lists.json`) |
| Faker + SDV | Synthetic customers | No real customer data anywhere in the project |

Configure the list with `STC_WATCHLIST` in `.env`: `opensanctions` (default in the launcher), `opensanctions:us_ofac_sdn,eu_fsf`, `sample`, or a folder of OFAC CSVs.

## Synthetic customer book (SDV + Faker)

```bash
stc synth --n 5000 --screen      # or use the "Customer book" tab in the UI
```

1. **Seed rules**: a 3,000-row table built from documented assumptions (FATF status, PEP rates, segment turnover, high-risk industries). In a bank you would replace this with the bank's own masked customer table.
2. **SDV** fits Gaussian-copula synthesizers (separate models for individuals and entities) and samples the book. The SDV quality score against the seed is reported (typically about 0.85).
3. **Faker** generates names, DOBs and passport numbers that fit each customer's country. Arabic, Persian and Korean names come from curated romanized lists, because machine transliteration of those scripts is unrealistic.
4. **Planted cases** (1% each) come from the live list: true matches with realistic noise (strong aliases, transliteration, name order, typos, dropped middle names, transposed or partial DOBs, IDs), and same-name near-misses born decades apart.

Screening the book reports **recall on planted matches, planted matches wrongly auto-closed (must be 0), near-miss auto-closure, alert rate and throughput**. Known limitation: the Gaussian copula blurs some segment-specific structure (e.g. private-banking turnover comes out lower than in the seed); a CTGAN synthesizer or real seed data would fix that.

## Key design decisions

1. **The LLM recommends; policy decides.** Adjudicators are swappable (`rules`, `claude`, a future fine-tuned model), but alert status comes only from `policy.py`. The policy is about 80 lines that compliance can read, and its invariants are tested against *every* possible adjudicator output (`test_policy_invariants_hold_for_any_recommendation`).
2. **Recall over precision in screening.** A missed hit is a regulatory breach; an extra alert costs minutes. Thresholds are tuned for 100% recall on the golden set, and precision is recovered at triage.
3. **Facts in code, judgement in the model.** DOB, country and ID comparisons are deterministic and reproducible. The model reasons over them (naming conventions, weak aliases, ownership risk) and writes the case narrative.
4. **Entity vs individual is not a clean contradiction.** A company named after a listed person may be owned by them (OFAC 50% rule), so it goes to a human with a note instead of being auto-closed.
5. **Defence in depth against prompt injection.** Untrusted text is delimited in the prompt, closing tags are stripped, a regex detector flags it, the model can flag it, and even a fully compromised model cannot auto-close without deterministic evidence.
6. **Alert hygiene is part of the control.** Duplicate alerts waste analyst time and bury real hits. The dedupe key is *customer identity + list entry + list-entry fingerprint*, so a changed list entry (a new alias or DOB) re-raises a previously cleared hit, just as a real list-change review would.
7. **Model risk management ready.** Versioned adjudicators, a fixed eval set, a CI gate, logged fallbacks and analyst/model agreement tracked in `/api/metrics`, which is the evidence an SR 11-7 validation asks for.

## Roadmap

- Ownership and control graph (50% rule) from corporate registry data
- ISO 20022 (pacs.008) / SWIFT MT103 payment message parsing
- Active learning: analyst dispositions feed the eval set and threshold tuning
- QA sampling workflow for auto-closed alerts

## Disclaimer

Demo and portfolio project. The bundled watchlist is **fictional**. This is not legal advice and is not a certified screening solution; any production use requires validation under your institution's model risk and compliance frameworks.
