# Case study: taking L1 sanctions alert triage from manual to AI-assisted, without weakening controls

*Written the way a forward deployed engineer would write up a customer engagement. The customer here is a composite based on my experience in AML and sanctions operations; figures from the project are measured, while industry context is labelled as such.*

## 1. The customer problem

A mid-size bank screens its customer base nightly and every cross-border payment in real time. The screening system is tuned for recall, as regulators expect, so it produces a large volume of alerts. Across the industry, the great majority of sanctions alerts turn out to be false positives.

Each alert is worked by an L1 analyst, who:
1. opens the customer record and the list entry side by side
2. compares date of birth, nationality, ID numbers and entity type
3. writes a disposition note for the audit file
4. closes it or escalates it to L2

The work is repetitive and slow, and consistency varies by analyst and by shift. It is also where the institution's risk sits: an analyst who clears a real hit on a busy night creates a sanctions breach.

**What the customer asked for:** "Use AI to close false positives."
**What they actually needed:** fewer analyst minutes per alert, *with no increase in the risk of clearing a true match*, and an audit trail they can defend to an examiner.

## 2. Discovery: what I would validate on-site

| Question | Why it matters | How it shaped the build |
|---|---|---|
| Which evidence do L2 reviewers accept for closing an alert? | Defines "hard contradiction" | DOB conflict and person-vs-vessel only; country alone is never enough |
| Where do false positives come from? | Tells us what to automate first | Common names + DOB conflicts are the bulk and the safest to automate |
| What does model risk management (SR 11-7) require? | Decides whether the tool can go live | Versioned adjudicators, fixed eval set, CI gate, logged fallbacks |
| Where does untrusted text enter? | Attack surface | Payment remittance info and KYC notes are handled as untrusted input |
| What can't leave the bank? | Deployment model | Deterministic core runs fully on-prem; the LLM is optional and swappable |

## 3. The solution

The central decision: **the LLM recommends, a deterministic policy decides.**

- **Screening** normalises names (transliteration, name order, legal forms) and scores with fuzzy and phonetic matching. It is tuned for 100% recall.
- **Signals** such as DOB, country, ID and party type are compared in code, so every fact an alert is closed on can be reproduced.
- **Adjudicator**: Claude receives the record, list entry and signals, and returns a structured recommendation plus a draft disposition narrative. Forced tool use and schema validation mean malformed output is retried, then falls back to rules.
- **Policy** auto-closes only when a hard contradiction exists *and* no ID matched *and* no injection was detected. True matches always go to a human with high priority.
- **Audit**: every step is written to a hash-chained log, and `/api/audit/verify` proves nothing was edited afterwards.
- **Workflow**: an analyst UI, a batch CSV mode for nightly files, a REST API for the payment hub, and an MCP server so analysts can work the queue from Claude.

## 4. Results on the evaluation set

61 labelled cases across 15 failure modes, including 3 adversarial prompt-injection cases.

| Metric | Rules baseline |
|---|---|
| Screening recall on true matches | 100% |
| True matches auto-closed | 0 |
| Injection cases auto-closed | 0 |
| False-positive alerts auto-closed | 68% |
| Screening latency (18k-entry list) | ~10 ms |

Run `python evals/run_evals.py --adjudicator claude` to add the Claude column. The comparison worth making is *recommendation accuracy on the alerts that still need a human*, and the quality of the drafted disposition narrative, because that is where analyst time goes after auto-closure.

**Caveat:** I wrote the golden set myself against a fictional list. In a real engagement, week one is rebuilding it from the bank's historical dispositions.

## 5. What I would do next with the customer

1. **Shadow mode (4 weeks):** run alongside analysts with no auto-closure and measure agreement per alert category.
2. **Turn on auto-closure for DOB-conflict alerts only**, with a 10% QA sample.
3. **Expand** to the other categories that meet the agreement threshold, category by category, with the compliance officer signing off each one.
4. Add **ownership graph** data (50% rule) and **ISO 20022 payment parsing**.

## 6. What this demonstrates

- **Domain knowledge:** sanctions operations, examiner expectations, model risk, and the real failure modes of name screening.
- **Engineering:** production Python, API design, persistence, CI, Docker and an MCP integration.
- **Applied AI:** structured output, fallbacks, prompt-injection defence, and evals that gate releases on safety metrics rather than accuracy alone.
- **FDE judgement:** reframing "close false positives" as "save analyst time without raising breach risk", and building the controls that make an AI tool deployable in a regulated bank.
