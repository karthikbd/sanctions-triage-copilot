// Typed client for the FastAPI backend (same origin). Mirrors the Pydantic models in src/sanctions_copilot/models.py.

export type PartyType = "individual" | "entity" | "vessel" | "aircraft" | "unknown";
export type Verdict = "true_match" | "false_positive" | "escalate";
export type AlertStatus = "auto_closed" | "pending_review" | "confirmed_match" | "cleared";
export type Priority = "high" | "medium" | "low";
export type SignalOutcome = "exact" | "match" | "near" | "mismatch" | "missing" | "unknown";

export interface Party {
  name: string;
  party_type: PartyType;
  dob?: string | null;
  country?: string | null;
  nationality?: string | null;
  id_numbers: string[];
  address?: string | null;
  reference?: string | null;
  notes?: string | null;
}

export interface WatchlistEntry {
  uid: string;
  name: string;
  aliases: string[];
  party_type: PartyType;
  programs: string[];
  dobs: string[];
  countries: string[];
  id_numbers: string[];
  remarks?: string | null;
  source: string;
}

export interface Signals {
  dob: SignalOutcome; dob_detail: string;
  country: SignalOutcome; country_detail: string;
  id_number: SignalOutcome; id_detail: string;
  party_type: SignalOutcome; party_type_detail: string;
}

export interface Decision {
  verdict: Verdict;
  confidence: number;
  rationale: string;
  evidence: { factor: string; assessment: string; detail: string }[];
  adjudicator: string;
  next_steps: string[];
  suspected_injection: boolean;
  notes: string[];
  latency_ms?: number | null;
}

export interface Alert {
  alert_id: string;
  request_id: string;
  origin: string;
  created_at: string;
  party: Party;
  candidate: { entry: WatchlistEntry; matched_name: string; name_score: number; signals: Signals };
  decision: Decision;
  status: AlertStatus;
  priority: Priority;
  policy_notes: string[];
  injection_flags: string[];
  review?: { analyst: string; outcome: Verdict; comment: string; reviewed_at: string } | null;
}

export interface RepeatHit {
  alert_id: string; list_uid: string; list_name: string; previous_status: AlertStatus; action: string; detail: string;
}

export interface ScreeningResult {
  request_id: string;
  party: Party;
  list_source: string;
  list_size: number;
  alerts: Alert[];
  repeat_hits: RepeatHit[];
  injection_flags: string[];
  duration_ms: number;
  outcome: "clear" | "review" | "auto_closed" | "suppressed" | "blocked";
}

export interface Health {
  status: string;
  adjudicator: string;
  list_source: string;
  list_size: number;
  list_version: string;
  list_status: string;
  backend: string;
  serverless: boolean;
  admin_required: boolean;
  db_target?: string | null;
  db_error?: string | null;
}

export interface Metrics {
  alerts_total: number;
  by_status: Partial<Record<AlertStatus, number>>;
  by_origin: Record<string, number>;
  auto_close_rate: number;
  analyst_reviews: number;
  analyst_model_agreement: number | null;
  list_size: number;
}

export interface Dataset { name: string; entities: number; version?: string; source?: string; error?: string }

export interface ListsInfo {
  source: string; version: string; entities: number; datasets: Dataset[]; attribution: string; configured: string;
  backend: string; schedule: string; status: string; message: string; last_refresh: string | null;
  last_delta: null | {
    updated?: boolean; baseline?: boolean; added?: number; changed?: number; removed?: number;
    rescreen?: { customers: number; new_alerts: number } | null;
  };
}

export interface Scenario { title: string; description: string; party: Party }
export interface Country { code: string; name: string; aliases: string[]; historic: boolean }

export interface Customer {
  customer_id: string; name: string; party_type: PartyType; country: string; segment: string; risk_rating: string;
}

export interface BatchRun {
  customers: number; customers_with_hits: number; new_alerts: number; repeat_hits: number; auto_closed: number;
  pending_review: number; planted_true_matches: number; planted_found: number; planted_found_not_auto_closed: number;
  planted_recall: number | null; near_misses: number; near_miss_auto_closed: number; ms_per_customer: number;
  list_version: string; finished_at: string; missed: { name: string; list_uid: string; method: string }[];
}

export interface CustomersInfo {
  count: number; planted_true_matches: number; planted_near_misses: number; sample: Customer[]; last_batch: BatchRun | null;
}

export interface Job {
  job_id: string; kind: string; status: "running" | "done" | "failed"; progress: number; total: number;
  result?: Record<string, unknown> | null; error?: string | null;
}

export interface AuditRecord { event: string; actor: string; ts: string; hash: string; prev_hash: string; payload?: unknown }

// ---------------------------------------------------------------------------------------------------------------------

const PASS_KEY = "stc_admin";
export const passcode = {
  get(): string { try { return sessionStorage.getItem(PASS_KEY) || ""; } catch { return ""; } },
  set(v: string) { try { v ? sessionStorage.setItem(PASS_KEY, v) : sessionStorage.removeItem(PASS_KEY); } catch { /* private mode */ } },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

type AuthListener = (message: string) => void;
let onAuthError: AuthListener = () => {};
export function setAuthListener(fn: AuthListener) { onAuthError = fn; }

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  const pw = passcode.get();
  if (pw) headers["X-Admin-Passcode"] = pw;
  let r: Response;
  try {
    r = await fetch(path, { ...init, headers: { ...headers, ...(init.headers as Record<string, string>) } });
  } catch {
    throw new ApiError(0, "Network error: the server could not be reached.");
  }
  const text = await r.text();
  let body: unknown = null;
  try { body = text ? JSON.parse(text) : null; } catch { /* non-JSON (e.g. platform error page) */ }
  if (!r.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    const msg = typeof detail === "string" ? detail
      : detail ? JSON.stringify(detail)
      : `HTTP ${r.status}: ${(text.split("\n").find(Boolean) || r.statusText || "request failed").slice(0, 200)}`;
    if (r.status === 401 || r.status === 403) onAuthError(msg);
    throw new ApiError(r.status, msg);
  }
  return body as T;
}

export const post = <T,>(path: string, data?: unknown) =>
  api<T>(path, { method: "POST", body: data === undefined ? undefined : JSON.stringify(data) });

/** Serverless deployments finish jobs inside the request; locally they run in the background and are polled. */
export async function runJob(job: Job, onTick: (j: Job) => void): Promise<Job> {
  onTick(job);
  let j = job;
  while (j.status === "running") {
    await new Promise((res) => setTimeout(res, 800));
    j = await api<Job>(`/api/jobs/${j.job_id}`);
    onTick(j);
  }
  return j;
}
