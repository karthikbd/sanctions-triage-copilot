# LinkedIn kit: Sanctions Triage Copilot

Two videos, both with captions burned in (most people watch LinkedIn videos muted):

| File | Length | Use |
|---|---|---|
| `architecture.mp4` | 0:52 | How it's built end to end. Best as the **first post** (short, grabs attention). |
| `walkthrough.mp4` | 2:25 | Every feature, one by one, on the real sanctions list. Best as a **second post** a few days later, or linked in the first comment. |

LinkedIn allows one video per post. Upload the MP4 directly rather than as a YouTube link, because native video gets far more reach.

---

## Post 1: architecture video

I come from AML and sanctions in banking. This project turns that domain knowledge into a working product.

Sanctions Triage Copilot screens customers against the real OFAC, UN, EU and UK sanctions lists and does the first-level triage an L1 analyst does every day: gather the evidence, recommend a disposition, and route the alert.

What I cared about most is what an analyst or a regulator would ask:

🔹 A true match is never closed by a machine. Only hard, deterministic evidence (a date of birth decades apart, a person vs a vessel) can auto-close an alert.
🔹 The evidence is computed in code, not by the model. DOB, country, ID and party-type signals are deterministic and shown side by side.
🔹 Free text is untrusted. Payment remittance info telling the AI to "clear this alert" is detected, flagged and held for a human.
🔹 Every decision is explainable and tamper-evident, recorded in a SHA-256 hash-chained audit trail.
🔹 It's measured, not assumed. Real listed names are planted in a synthetic customer book (SDV + Faker) with typos and transliterations, and every batch run reports recall. Misses are listed so they can be tuned.

How it's built:
• Data: OpenSanctions (32,704 entities across 4 official lists), refreshed by a Docker worker on GitHub Actions. Only new or changed entries are re-screened.
• Engine: Python, fuzzy + phonetic matching, a rules or Claude adjudicator, and a guardrail policy layer.
• App: React + TypeScript UI and a FastAPI API on Vercel, with Supabase Postgres for alerts, decisions and audit.
• Quality: 113 automated tests, an evaluation gate, and Playwright end-to-end tests.

Screening one customer against the full list takes about 9 ms.

Live demo: https://sanctions-triage-copilot.vercel.app

#AML #Sanctions #FinancialCrime #Compliance #RegTech #AppliedAI #LLM #Python #React #FastAPI

---

## Post 2: walkthrough video (a few days later)

A 2-minute walkthrough of Sanctions Triage Copilot on the real OFAC, UN, EU and UK lists. Each test case covers one alert type an L1 analyst sees every day:

1. Exact hit → true match, routed to a human
2. Spelling variant → still caught (fuzzy + phonetic matching)
3. Same name, different person → auto-closed on a DOB contradiction
4. Prompt injection in payment text → flagged and held for a human
5. Name-only payment beneficiary → escalated, never auto-cleared
6. Vessel matched by IMO number
7. Re-screening → linked to the open alert, no duplicates

Then the analyst decision (recorded to a hash-chained audit trail), and a 1,000-customer batch where recall on planted matches is measured, not assumed.

Architecture post: [link to post 1]
Live demo: https://sanctions-triage-copilot.vercel.app

#AML #Sanctions #FinancialCrime #RegTech #AppliedAI #HumanInTheLoop

---

## If you'd rather record it yourself with your own voice

A narrated version in your own voice builds the most trust. Use Windows Game Bar (`Win + Alt + R` to start and stop, in Chrome at full screen) or OBS. Follow the same order as `walkthrough.mp4`:

| # | Screen | What to say (roughly) |
|---|---|---|
| 1 | Watchlists | "These are the real OFAC, UN, EU and UK lists, 32,704 entities, refreshed automatically. Only new or changed entries get re-screened." |
| 2 | Screen a party → Exact hit | "A listed person with the same name and date of birth. It's a true match, so it goes to a human. A machine never closes it." |
| 3 | Open the alert → Evidence tab | "The evidence is computed in code: date of birth, country, ID, party type. The model recommends; it doesn't decide the facts." |
| 4 | Audit trail tab | "Every event is hash-chained, so any edit to history breaks the chain." |
| 5 | Spelling variant | "Transliterations are the everyday problem in sanctions screening, and fuzzy plus phonetic matching catches them." |
| 6 | Same name, different person | "Same name, born decades later. That's a hard contradiction, so it closes automatically and is sampled for QA." |
| 7 | Prompt injection | "The payment text tells the AI to clear the alert. It's detected, auto-closure is switched off, and it goes to a human." |
| 8 | Name only (payment) | "No date of birth or ID means it can't be cleared safely, so it's escalated." |
| 9 | Exact hit again | "Screening the same customer again links to the open alert, with no duplicates." |
| 10 | Alerts → open one → Confirm match | "The analyst makes the call, and the decision, comment and agreement with the model go into the audit trail." |
| 11 | Customer book → Generate → Screen entire book | "The customer book is synthetic, because real bank data is confidential. Real listed names are planted with typos so I can measure recall on every run." |
| 12 | Last batch run | "Recall on planted matches, zero true matches auto-closed, and any misses listed for tuning." |

Tips:
- Unlock admin before you start recording so the passcode doesn't appear on screen.
- Use the light or dark theme switch in the top bar to pick your look.
- Keep it under 3 minutes and add captions (LinkedIn can generate them, or burn them in with CapCut).

## Accuracy notes (so every claim holds up)

- **32,704**: entity count across the four OpenSanctions datasets (overlaps merge to 23,707 unique entries in the database).
- **~9 ms per customer**: measured on Postgres during the recorded 1,000-customer batch (8.7–8.9 ms).
- **Recall**: 90% (9/10) in the recorded run and 100% (10/10) in the previous run. Planted names differ per run, which is why the post says "measured every run" rather than quoting one number.
- **0 planted true matches auto-closed**, in both runs.
- The walkthrough was recorded on a local mirror of the live app: the same code, the same Postgres schema and the full real list copied from Supabase. The live site behaves the same way.
