"""Vercel entrypoint: exposes the FastAPI `app`.

On Vercel the app runs serverless. With STC_DATABASE_URL (or the Supabase integration's POSTGRES_URL) it uses
Supabase Postgres for lists, alerts, audit and customers. If no database is configured, or it cannot be reached,
TriageService falls back to a temporary demo (fictional sample list, /tmp SQLite) and reports why in
/api/health, so a bad setting never takes the site down. The React UI in public/ is served by Vercel's CDN.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
logging.basicConfig(level=logging.INFO)

from fastapi import FastAPI  # noqa: E402

from sanctions_copilot.api import create_app  # noqa: E402

app: FastAPI = create_app()
