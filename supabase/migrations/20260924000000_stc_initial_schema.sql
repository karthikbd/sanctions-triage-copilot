-- Sanctions Triage Copilot schema (applied to Supabase project sanctions-triage-copilot).
-- Private schema, not exposed through the Supabase Data API; the app connects server-side with a Postgres
-- role. RLS is enabled with no policies as defence in depth.
create schema if not exists stc;

create table stc.watchlist_entries (
  uid          text primary key,
  name         text not null,
  party_type   text not null,
  aliases      text[] not null default '{}',
  programs     text[] not null default '{}',
  dobs         text[] not null default '{}',
  countries    text[] not null default '{}',
  id_numbers   text[] not null default '{}',
  remarks      text,
  source       text not null,
  fingerprint  text not null,
  updated_at   timestamptz not null default now()
);

create table stc.watchlist_names (
  id          bigserial primary key,
  uid         text not null references stc.watchlist_entries(uid) on delete cascade,
  display     text not null,
  block_keys  text[] not null
);
create index watchlist_names_keys_gin on stc.watchlist_names using gin (block_keys);
create index watchlist_names_uid on stc.watchlist_names (uid);

create table stc.alerts (
  alert_id    text primary key,
  request_id  text not null,
  created_at  timestamptz not null,
  status      text not null,
  priority    text not null,
  origin      text not null default 'screening',
  dedupe_key  text,
  body        jsonb not null
);
create index alerts_status on stc.alerts (status, created_at desc);
create index alerts_dedupe on stc.alerts (dedupe_key, created_at desc);

create table stc.audit (
  seq        bigserial primary key,
  ts         text not null,
  actor      text not null,
  event      text not null,
  ref        text,
  payload    text not null,
  prev_hash  text not null,
  hash       text not null
);
create index audit_ref on stc.audit (ref);

create table stc.kv (k text primary key, v text not null);

create table stc.customers (
  customer_id  text primary key,
  seq          integer not null,
  data         jsonb not null,
  label        text not null default 'none',
  list_uid     text,
  method       text
);
create index customers_seq on stc.customers (seq);

create table stc.jobs (
  job_id       text primary key,
  kind         text not null,
  status       text not null,
  progress     integer not null default 0,
  total        integer not null default 0,
  started_at   text not null,
  finished_at  text,
  result       jsonb,
  error        text
);

alter table stc.watchlist_entries enable row level security;
alter table stc.watchlist_names   enable row level security;
alter table stc.alerts            enable row level security;
alter table stc.audit             enable row level security;
alter table stc.kv                enable row level security;
alter table stc.customers         enable row level security;
alter table stc.jobs              enable row level security;

revoke all on schema stc from anon, authenticated;
