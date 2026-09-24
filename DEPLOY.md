# Deploying: Vercel + Supabase + Docker worker

Live demo: https://sanctions-triage-copilot.vercel.app

```
Browser ──> Vercel (React UI + FastAPI as a Python serverless function, index.py)
                │  reads/writes
                ▼
        Supabase Postgres (schema `stc`, RLS on, GIN index on block_keys)
                ▲
                │  heavy jobs: OpenSanctions sync, SDV book generation, full-book screening
        Docker worker image  ── run on a schedule by GitHub Actions (.github/workflows/worker.yml)
```

**UI:** React + TypeScript + Tailwind in `web/`. `npm run build` writes the bundle into `src/sanctions_copilot/webui/`
and FastAPI serves it (locally, in Docker and on Vercel, where `vercel.json` runs the build). If the bundle is missing,
FastAPI falls back to the single-file page at `/legacy`. Develop with `cd web && npm install && npm run dev` (proxies `/api`
to a local `stc serve` on port 8000).

**Why the API also runs on Vercel:** Vercel hosts the UI and the lightweight API calls: screening one party, the review queue and audit. Anything slow or memory-heavy (SDV + torch, a multi-thousand-row list sync) runs in the Docker worker instead, which is why serverless caps inline jobs (`max_customers_inline`).

The app tries `STC_DATABASE_URL`, then `DATABASE_URL`, then the Supabase integration's `POSTGRES_URL`. URLs pasted with
a raw `#`/`@` in the password, `[brackets]`, or extra query parameters (`supa=`, `pgbouncer=`) are cleaned up
automatically. If none connects, the site does **not** crash: it runs the temporary demo and shows the exact
(password-free) error in the UI banner and `/api/health`.

Without a database, the deployment runs in **demo mode**: SQLite in `/tmp` with the fictional sample list. Data resets whenever the function cold-starts.

## 1. Supabase
1. Apply the schema in `supabase/migrations/20260924000000_stc_initial_schema.sql`. It is already applied to the project used for the live demo.
2. Settings → Database: reset the database password, then copy the **Transaction pooler** connection string (port 6543).

## 2. Vercel environment variables
Set these under Project → Settings → Environment Variables, then redeploy:

| Variable | Value |
|---|---|
| `STC_DATABASE_URL` | Supabase transaction-pooler URI |
| `STC_ADMIN_PASSCODE` | Passcode for analyst decisions and admin buttons |
| `CRON_SECRET` | Any long random string; Vercel cron sends it to `/api/cron/daily` |
| `ANTHROPIC_API_KEY` | Optional. Enables the Claude adjudicator; otherwise the rules adjudicator is used |
| `STC_WATCHLIST` | `opensanctions` (default datasets) |
| `STC_NIGHTLY_RESET` | Optional. `true` clears the alert queue in the daily cron (off by default, so decisions persist) |

## 3. GitHub + worker
1. Push this folder to a GitHub repo (this project: `karthikbd/sanctions-triage-copilot`).
2. Repo → Settings → Secrets → Actions: add `STC_DATABASE_URL` (and optionally `ANTHROPIC_API_KEY`).
3. Actions → **worker** → Run workflow, with task `refresh`, to load the first OpenSanctions snapshot. After that it runs every 6 hours. Other tasks are `synth`, `screen-book`, `reset-queue` and `status`.
4. Connect the repo to the Vercel project (Settings → Git). This project is connected: pushes to `main` deploy to production, and other branches and pull requests get preview URLs.

## Local Docker
```
docker compose up app                      # UI at http://localhost:8000
docker compose --profile worker run worker refresh-lists
```
