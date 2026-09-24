# LinkedIn post: Sanctions Triage Copilot (single post)

**Video:** `sanctions-triage-copilot-linkedin.mp4` (4:40, 1080p, AI narration, captions burned in)
**Thumbnail:** `thumbnail.png` (upload it as the video's cover in LinkedIn's video settings)

Upload the MP4 directly to LinkedIn rather than as a link, then paste the text below.

---

Most of a sanctions analyst's day goes into clearing false-positive alerts. I've worked on that side of the queue in AML and sanctions in banking, so I built the copilot I always wanted, end to end.

🎥 The video covers the architecture first, then every feature running live on the real OFAC, UN, EU and UK sanctions lists.

𝗪𝗵𝗮𝘁 𝘁𝗵𝗲 𝗯𝗮𝗻𝗸𝗶𝗻𝗴 𝗱𝗼𝗺𝗮𝗶𝗻 𝘁𝗮𝘂𝗴𝗵𝘁 𝗺𝗲 𝘁𝗼 𝗯𝘂𝗶𝗹𝗱
• A true match is never closed by a machine. Only hard evidence, like a date of birth decades apart or a person vs a vessel, can auto-close an alert.
• Transliterations and aliases are the everyday problem, so matching is fuzzy and phonetic across every alias.
• Payment remittance text is untrusted. When it tells the AI to "clear this alert", that's detected, flagged and held for a human.
• Regulators ask "why?", so the evidence is computed in code and every decision goes into a hash-chained audit trail.
• Duplicate alerts waste analyst time, so re-screening links to the open alert.

𝗪𝗵𝗮𝘁 𝗳𝗼𝗿𝘄𝗮𝗿𝗱-𝗱𝗲𝗽𝗹𝗼𝘆𝗲𝗱 𝗲𝗻𝗴𝗶𝗻𝗲𝗲𝗿𝗶𝗻𝗴 𝗯𝗿𝗼𝘂𝗴𝗵𝘁
• Real data, not a toy: the official lists come through OpenSanctions (32,704 entities), synced by a Docker worker on GitHub Actions, with only changed entries re-screened.
• A real deployment: a React + TypeScript UI and a FastAPI service on Vercel, Supabase Postgres for alerts, decisions and audit, and admin controls for the public demo.
• Built to fail safely: a bad database setting falls back to a demo mode and reports the error instead of taking the site down.

𝗪𝗵𝗲𝗿𝗲 𝗔𝗜/𝗠𝗟 𝗳𝗶𝘁𝘀, 𝗮𝗻𝗱 𝘄𝗵𝗲𝗿𝗲 𝗶𝘁 𝗱𝗼𝗲𝘀𝗻'𝘁
• An LLM adjudicator (Claude with forced tool use, or a rules engine) recommends a verdict. Guardrails outside the model decide what's allowed.
• Synthetic customers from SDV + Faker, with real sanctioned names planted using typos and transliterations, so recall is measured on every batch run, not assumed.
• An evaluation gate plus 113 automated tests and browser end-to-end tests.

𝗥𝗲𝘀𝘂𝗹𝘁𝘀
~9 ms to screen a customer against the full list · 0 planted true matches auto-closed · 90–100% recall on planted matches across runs, with every miss listed for tuning.

Domain knowledge decides what "correct" means. Engineering makes it real.

🔗 Live demo: https://sanctions-triage-copilot.vercel.app

(Narration in the video is AI-generated.)

#AML #Sanctions #FinancialCrime #Compliance #RegTech #ForwardDeployedEngineering #AppliedAI #LLM #MachineLearning #Python #React

---

## Notes

- **Length:** the text is about 2,300 characters, under LinkedIn's 3,000 limit. Only the first two lines show before "…see more", so the hook is at the top.
- **The bold headings** use Unicode bold characters, which is how bold text shows up on LinkedIn. If you'd rather keep it plain, swap them for normal text.
- **Every figure is from the recorded runs.** 32,704 is the OpenSanctions entity count. About 9 ms per customer was measured on Postgres (8.5–8.9 ms). Recall was 100% (10/10) in the narrated run and 90% (9/10) in an earlier run. No planted true matches were auto-closed in any run.
- **Voice:** "Eric", from your vidIQ voices. The narration used about 56 credits, and the two short tests used 28 more.
