"""Postgres URL clean-up shared by the service (no psycopg import needed)."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, quote, unquote, urlencode

# libpq accepts only these URI query parameters; hosting integrations add others (e.g. Supabase's
# "supa=base-pooler.x", Prisma's "pgbouncer=true") that make psycopg refuse the whole URL.
_LIBPQ_PARAMS = {"sslmode", "sslrootcert", "sslcert", "sslkey", "connect_timeout", "application_name", "options",
                 "target_session_attrs", "host", "port", "dbname", "user", "password", "keepalives", "keepalives_idle", "channel_binding", "gssencmode"}
_URL_RE = re.compile(r"^(postgres(?:ql)?://)([^:/@]+)(?::(.*))?@([^@/?#]+)(/[^?#]*)?(?:\?(.*))?$", re.S)


class DatabaseURLError(ValueError):
    pass


def clean_db_url(url: str) -> str:
    """Normalise a Postgres URL pasted from a dashboard: trim quotes/whitespace, percent-encode a password that
    contains special characters (#, @, /, ...), drop query parameters libpq rejects, and require TLS."""
    u = (url or "").strip().strip('"').strip("'").strip()
    if not u:
        raise DatabaseURLError("empty database URL")
    if "[YOUR-PASSWORD]" in u.upper() or "YOUR-PASSWORD" in u.upper():
        raise DatabaseURLError("the URL still contains the [YOUR-PASSWORD] placeholder")
    if not u.startswith(("postgres://", "postgresql://")):
        raise DatabaseURLError("it should start with postgresql:// (copy the URI, not the individual fields)")
    m = _URL_RE.match(u)
    if not m:
        return u  # e.g. unix-socket URLs without a host (postgresql://user@/db?host=/tmp): leave as-is
    scheme, user, pw, host, path, query = m.groups()
    if pw and pw.startswith("[") and pw.endswith("]"):
        pw = pw[1:-1]  # pasted with the brackets from the placeholder still around the password
    pw_enc = quote(unquote(pw), safe="") if pw is not None else None
    params = [(k, v) for k, v in parse_qsl(query or "", keep_blank_values=True) if k in _LIBPQ_PARAMS]
    if "supabase" in host and not any(k == "sslmode" for k, _ in params):
        params.append(("sslmode", "require"))
    out = f"{scheme}{user}{':' + pw_enc if pw_enc is not None else ''}@{host}{path or '/postgres'}"
    return out + (("?" + urlencode(params)) if params else "")


def describe_db_url(url: str) -> str:
    """user@host:port/db with the password removed, safe to show in the UI and logs."""
    m = _URL_RE.match((url or "").strip().strip('"').strip("'"))
    if not m:
        return "(unparseable URL)"
    _, user, _, host, path, _ = m.groups()
    return f"{user}@{host}{path or ''}"
