import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { BookUser, Inbox, ListChecks, Lock, LockOpen, Monitor, Moon, ScanSearch, ShieldCheck, ShieldX, Sun } from "lucide-react";
import { api, passcode, setAuthListener, type Health, type ListsInfo, type Metrics } from "./api";
import { ago, Badge, Button, Callout, cx, Dot, fmt, Input } from "./components/ui";
import { AlertDrawer } from "./components/AlertDrawer";
import { AlertsPage } from "./pages/AlertsPage";
import { ScreenPage } from "./pages/ScreenPage";
import { BookPage } from "./pages/BookPage";
import { ListsPage } from "./pages/ListsPage";

export type Page = "alerts" | "screen" | "book" | "lists";
const PAGES: { id: Page; label: string; icon: typeof Inbox }[] = [
  { id: "alerts", label: "Alerts", icon: Inbox },
  { id: "screen", label: "Screen a party", icon: ScanSearch },
  { id: "book", label: "Customer book", icon: BookUser },
  { id: "lists", label: "Watchlists", icon: ListChecks },
];

interface AppCtx {
  health: Health | null;
  metrics: Metrics | null;
  lists: ListsInfo | null;
  audit: { valid: boolean; records: number } | null;
  version: number;              // bumps whenever data changed, so pages re-fetch
  refresh: () => Promise<void>;
  openAlert: (id: string) => void;
  go: (p: Page) => void;
  isAdmin: boolean;
  requireAdmin: (msg?: string) => void;
}
const Ctx = createContext<AppCtx>(null as unknown as AppCtx);
export const useApp = () => useContext(Ctx);

const pageFromHash = (): Page => {
  const h = window.location.hash.replace("#", "") as Page;
  return PAGES.some((p) => p.id === h) ? h : "alerts";
};

export default function App() {
  const [page, setPage] = useState<Page>(pageFromHash);
  const [health, setHealth] = useState<Health | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [lists, setLists] = useState<ListsInfo | null>(null);
  const [audit, setAudit] = useState<{ valid: boolean; records: number } | null>(null);
  const [version, setVersion] = useState(0);
  const [alertId, setAlertId] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(() => !!passcode.get());
  const [adminPrompt, setAdminPrompt] = useState<string | null>(null);
  const [offline, setOffline] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [h, m, l, v] = await Promise.all([
        api<Health>("/api/health"), api<Metrics>("/api/metrics"), api<ListsInfo>("/api/lists"),
        api<{ valid: boolean; records: number }>("/api/audit/verify"),
      ]);
      setHealth(h); setMetrics(m); setLists(l); setAudit(v); setOffline(null);
      setVersion((x) => x + 1);
    } catch (e) {
      setOffline((e as Error).message);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 10000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => setAuthListener((msg) => { passcode.set(""); setIsAdmin(false); setAdminPrompt(msg); }), []);

  const go = useCallback((p: Page) => { window.location.hash = p; setPage(p); }, []);
  const ctx = useMemo<AppCtx>(() => ({
    health, metrics, lists, audit, version, refresh, go, isAdmin,
    openAlert: (id) => setAlertId(id),
    requireAdmin: (msg) => setAdminPrompt(msg ?? "Enter the admin passcode to record decisions and run admin actions."),
  }), [health, metrics, lists, audit, version, refresh, go, isAdmin]);

  const pending = metrics?.by_status.pending_review ?? 0;
  const live = health?.backend === "postgres";

  return (
    <Ctx.Provider value={ctx}>
      <div className="flex h-full min-h-0 flex-col md:flex-row">
        {/* Sidebar */}
        <aside className="flex shrink-0 flex-col border-line bg-side md:h-full md:w-60 md:border-r max-md:border-b">
          <div className="flex h-12 items-center gap-2.5 px-4">
            <div className="grid size-7 place-items-center rounded-md bg-brand text-[13px] font-bold text-white dark:text-black">S</div>
            <div className="min-w-0 leading-tight">
              <div className="truncate text-[13px] font-semibold">Sanctions Triage</div>
              <div className="truncate text-[11px] text-faint">Copilot · L1 alert triage</div>
            </div>
          </div>
          <nav className="flex gap-0.5 overflow-x-auto px-2 pb-2 md:flex-col md:overflow-visible md:pt-2">
            {PAGES.map(({ id, label, icon: Icon }) => (
              <a
                key={id}
                href={`#${id}`}
                onClick={(e) => { e.preventDefault(); go(id); }}
                className={cx(
                  "flex h-8 shrink-0 items-center gap-2.5 rounded-md px-2.5 text-[13px] whitespace-nowrap",
                  page === id ? "bg-sunken font-medium text-fg" : "text-muted hover:bg-sunken hover:text-fg",
                )}
              >
                <Icon size={15} strokeWidth={1.8} />
                <span className="flex-1">{label}</span>
                {id === "alerts" && pending > 0 && <span className="tnum rounded bg-blue-soft px-1.5 text-[11px] font-medium text-blue">{fmt(pending)}</span>}
              </a>
            ))}
          </nav>
          <div className="mt-auto hidden space-y-3 border-t border-line p-4 text-[12px] md:block">
            <SideRow label="Storage">
              <span className="inline-flex items-center gap-1.5"><Dot tone={live ? "green" : "amber"} />{live ? "Supabase Postgres" : "Temporary (demo)"}</span>
            </SideRow>
            <SideRow label="List">
              <span className="block truncate" title={health?.list_source}>{health ? `${fmt(health.list_size)} entries` : "…"}</span>
            </SideRow>
            <SideRow label="Adjudicator"><span className="font-mono text-[11.5px]">{health?.adjudicator ?? "…"}</span></SideRow>
            <SideRow label="Audit chain">
              {audit && (audit.valid
                ? <span className="inline-flex items-center gap-1 text-green"><ShieldCheck size={13} />verified · {fmt(audit.records)}</span>
                : <span className="inline-flex items-center gap-1 text-red"><ShieldX size={13} />broken</span>)}
            </SideRow>
            {health?.admin_required && (
              <Button
                size="sm" variant="secondary" className="w-full"
                onClick={() => { if (isAdmin) { passcode.set(""); setIsAdmin(false); } else ctx.requireAdmin(); }}
              >
                {isAdmin ? <><LockOpen size={13} /> Admin unlocked · lock</> : <><Lock size={13} /> Unlock admin</>}
              </Button>
            )}
          </div>
        </aside>

        {/* Main */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line px-4 md:px-6">
            <div className="min-w-0 truncate text-[13px] text-muted">
              <span className="max-sm:hidden">Workspace</span><span className="px-1.5 text-faint max-sm:hidden">/</span>
              <span className="font-medium text-fg">{PAGES.find((p) => p.id === page)?.label}</span>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <ThemeSwitch />
              {health && (
                <Badge tone={live ? "green" : "amber"} className="max-sm:hidden">
                  {live ? "Live" : "Demo"} · {health.list_source.replace(/ \(.*\)$/, "")} · checked {ago(lists?.last_refresh)}
                </Badge>
              )}
              {health?.admin_required && (
                <Button size="sm" variant="ghost" className="md:hidden" onClick={() => (isAdmin ? (passcode.set(""), setIsAdmin(false)) : ctx.requireAdmin())}>
                  {isAdmin ? <LockOpen size={14} /> : <Lock size={14} />}
                </Button>
              )}
            </div>
          </header>

          <main className="scroll-thin min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto max-w-[1400px] space-y-4 p-4 md:p-6">
              <StatusBanner health={health} lists={lists} offline={offline} />
              {adminPrompt !== null && (
                <AdminBox
                  message={adminPrompt}
                  onClose={() => setAdminPrompt(null)}
                  onUnlocked={() => { setIsAdmin(true); setAdminPrompt(null); }}
                />
              )}
              {page === "alerts" && <AlertsPage />}
              {page === "screen" && <ScreenPage />}
              {page === "book" && <BookPage />}
              {page === "lists" && <ListsPage />}
              <footer className="pt-4 pb-2 text-center text-[11.5px] text-faint">
                {lists?.attribution ? `${lists.attribution} · ` : ""}Recommendations support, and never replace, a qualified analyst's decision.
              </footer>
            </div>
          </main>
        </div>
      </div>
      {alertId && <AlertDrawer id={alertId} onClose={() => setAlertId(null)} />}
    </Ctx.Provider>
  );
}

type ThemePref = "light" | "dark" | "system";
const THEME_KEY = "stc_theme";

function applyTheme(pref: ThemePref) {
  const dark = pref === "dark" || (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
}

function ThemeSwitch() {
  const [pref, setPref] = useState<ThemePref>(() => {
    try { return (localStorage.getItem(THEME_KEY) as ThemePref) || "system"; } catch { return "system"; }
  });
  useEffect(() => {
    applyTheme(pref);
    try { localStorage.setItem(THEME_KEY, pref); } catch { /* storage unavailable */ }
    if (pref !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => applyTheme("system");
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [pref]);
  const opts: { v: ThemePref; icon: typeof Sun; label: string }[] = [
    { v: "light", icon: Sun, label: "Light theme" },
    { v: "dark", icon: Moon, label: "Dark theme" },
    { v: "system", icon: Monitor, label: "Match system theme" },
  ];
  return (
    <div role="radiogroup" aria-label="Theme" className="flex items-center rounded-md border border-line p-0.5">
      {opts.map(({ v, icon: Icon, label }) => (
        <button key={v} role="radio" aria-checked={pref === v} title={label} aria-label={label} onClick={() => setPref(v)}
                className={cx("grid size-6 place-items-center rounded", pref === v ? "bg-sunken text-fg" : "text-faint hover:text-fg")}>
          <Icon size={13} />
        </button>
      ))}
    </div>
  );
}

function SideRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-faint">{label}</span>
      <span className="min-w-0 text-right text-muted">{children}</span>
    </div>
  );
}

function StatusBanner({ health, lists, offline }: { health: Health | null; lists: ListsInfo | null; offline: string | null }) {
  if (offline) return <Callout tone="red"><b>Can't reach the API.</b> {offline}</Callout>;
  if (!health || !lists) return null;
  if (health.db_error || lists.status === "db_error" || (lists.status === "error" && /database/i.test(lists.message)))
    return (
      <Callout tone="red">
        <b>Database connection failed</b>, so this is running as a temporary demo and data will reset.{" "}
        <span className="font-mono text-[11.5px] break-all">{health.db_error || lists.message}</span>
      </Callout>
    );
  if (lists.status === "error") return <Callout tone="red">{lists.message}</Callout>;
  if (lists.status === "loading") return <Callout tone="blue">{lists.message || "Loading sanctions lists…"}</Callout>;
  if (lists.status === "empty")
    return <Callout tone="amber"><b>Connected to Supabase, but no sanctions list is loaded yet.</b> Open <b>Watchlists</b> → <b>Check for list updates</b> (admin) to load OFAC, UN, EU and UK lists.</Callout>;
  if (health.backend !== "postgres")
    return (
      <Callout tone="amber">
        <b>Demo mode.</b> {lists.version === "static" ? "Screening the fictional sample list. " : ""}Alerts and decisions are stored
        temporarily and reset when the server restarts. Connect Supabase to keep data{lists.version === "static" ? " and use the live OpenSanctions lists" : ""}.
      </Callout>
    );
  return null;
}

function AdminBox({ message, onClose, onUnlocked }: { message: string; onClose: () => void; onUnlocked: () => void }) {
  const [value, setValue] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const disabled = /disabled/i.test(message);
  const submit = async () => {
    setBusy(true); setErr(null);
    passcode.set(value.trim());
    try { await api("/api/admin/check"); onUnlocked(); }
    catch (e) { passcode.set(""); setErr((e as Error).message === "Admin passcode required" ? "That passcode was not accepted." : (e as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-subtle px-3 py-2.5">
      <Lock size={14} className="text-muted" />
      <span className="text-[12.5px] text-muted">{err ?? message}</span>
      {!disabled && (
        <form className="ml-auto flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <Input type="password" autoFocus autoComplete="current-password" placeholder="Admin passcode" value={value}
                 onChange={(e) => setValue(e.target.value)} className="w-48" />
          <Button variant="primary" size="sm" disabled={busy || !value}>Unlock</Button>
        </form>
      )}
      <Button size="sm" variant="ghost" onClick={onClose} className={disabled ? "ml-auto" : ""}>Dismiss</Button>
    </div>
  );
}
