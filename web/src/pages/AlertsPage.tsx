import { useEffect, useState } from "react";
import { RotateCcw, ScanSearch, TriangleAlert } from "lucide-react";
import { api, post, type Alert } from "../api";
import { useApp } from "../App";
import {
  Badge, Button, Empty, fmt, humanize, priorityTone, shortTime, StatStrip, StatusText, statusTone, Tabs, verdictTone,
} from "../components/ui";

type Filter = "pending_review" | "auto_closed" | "decided" | "all";

export function AlertsPage() {
  const { metrics, lists, version, openAlert, refresh, go, isAdmin, requireAdmin, health } = useApp();
  const [filter, setFilter] = useState<Filter>("pending_review");
  const [rows, setRows] = useState<Alert[] | null>(null);
  const [armed, setArmed] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let dead = false;
    const q = filter === "decided"
      ? Promise.all([api<Alert[]>("/api/alerts?status=confirmed_match"), api<Alert[]>("/api/alerts?status=cleared")]).then(([a, b]) => a.concat(b))
      : api<Alert[]>(`/api/alerts${filter === "all" ? "" : `?status=${filter}`}`);
    q.then((r) => { if (!dead) setRows(r); }).catch(() => { if (!dead) setRows([]); });
    return () => { dead = true; };
  }, [filter, version]);

  const s = metrics?.by_status ?? {};
  const reset = async () => {
    if (health?.admin_required && !isAdmin) return requireAdmin();
    if (!armed) { setArmed(true); setTimeout(() => setArmed(false), 4000); return; }
    setArmed(false);
    try { const r = await post<{ removed: number }>("/api/admin/reset-queue"); setNote(`${fmt(r.removed)} alerts removed. The audit log keeps the history.`); await refresh(); }
    catch (e) { setNote((e as Error).message); }
  };

  return (
    <div className="space-y-4">
      <StatStrip items={[
        { label: "Awaiting analyst", value: fmt(s.pending_review) },
        { label: "Auto-closed on hard evidence", value: fmt(s.auto_closed) },
        { label: "Auto-close rate", value: `${Math.round((metrics?.auto_close_rate ?? 0) * 100)}%` },
        { label: "Analyst decisions", value: fmt((s.confirmed_match ?? 0) + (s.cleared ?? 0)),
          sub: metrics?.analyst_reviews ? `${fmt(metrics.analyst_reviews)} reviews · ${Math.round((metrics.analyst_model_agreement ?? 0) * 100)}% agree with model` : undefined },
        { label: "Sanctions list entries", value: fmt(lists?.entities ?? metrics?.list_size), sub: lists?.source?.replace(/ \(.*\)$/, "") },
      ]} />

      <section className="overflow-hidden rounded-lg border border-line bg-bg">
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
          <Tabs<Filter> value={filter} onChange={setFilter} items={[
            { value: "pending_review", label: "Awaiting analyst", count: s.pending_review ?? 0 },
            { value: "auto_closed", label: "Auto-closed", count: s.auto_closed ?? 0 },
            { value: "decided", label: "Analyst decided", count: (s.confirmed_match ?? 0) + (s.cleared ?? 0) },
            { value: "all", label: "All", count: metrics?.alerts_total ?? 0 },
          ]} />
          <div className="ml-auto flex items-center gap-2">
            {note && <span className="text-[12px] text-muted">{note}</span>}
            <Button size="sm" variant="danger" onClick={reset}><RotateCcw size={13} />{armed ? "Click again to confirm" : "Reset queue"}</Button>
          </div>
        </div>

        {rows === null ? (
          <div className="px-4 py-10 text-center text-[12.5px] text-muted">Loading…</div>
        ) : rows.length === 0 ? (
          <Empty title="No alerts in this view">
            Screen a party or run a demo scenario to create alerts.
            <div className="mt-3"><Button size="sm" onClick={() => go("screen")}><ScanSearch size={13} /> Screen a party</Button></div>
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-[12.5px]">
              <thead className="bg-subtle text-[11.5px] text-muted">
                <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:font-medium">
                  <th>Priority</th><th>Customer</th><th>Listed party</th><th>Programs</th>
                  <th className="text-right">Score</th><th>Recommendation</th><th>Status</th><th>Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((a) => (
                  <tr key={a.alert_id} onClick={() => openAlert(a.alert_id)}
                      className="cursor-pointer hover:bg-subtle [&>td]:px-3 [&>td]:py-2.5 [&>td]:align-top">
                    <td>
                      <StatusText tone={priorityTone(a.priority)}>{a.priority}</StatusText>
                      {a.injection_flags.length > 0 && <div className="mt-1"><Badge tone="red"><TriangleAlert size={11} />injection</Badge></div>}
                    </td>
                    <td className="max-w-56">
                      <div className="truncate font-medium">{a.party.name}</div>
                      <div className="truncate text-[11.5px] text-faint">
                        {humanize(a.party.party_type)}{a.party.dob ? ` · ${a.party.dob}` : ""}{a.party.reference ? ` · ${a.party.reference}` : ""}
                      </div>
                    </td>
                    <td className="max-w-56">
                      <div className="truncate">{a.candidate.entry.name}</div>
                      <div className="truncate font-mono text-[11px] text-faint">{a.candidate.entry.uid}</div>
                    </td>
                    <td className="max-w-44 text-muted"><div className="truncate">{a.candidate.entry.programs.slice(0, 3).join(", ") || "–"}</div></td>
                    <td className="tnum text-right font-medium">{a.candidate.name_score.toFixed(1)}</td>
                    <td>
                      <Badge tone={verdictTone(a.decision.verdict)}>{humanize(a.decision.verdict)}</Badge>
                      <span className="tnum ml-1.5 text-[11.5px] text-faint">{Math.round(a.decision.confidence * 100)}%</span>
                    </td>
                    <td>
                      <StatusText tone={statusTone(a.status)}>{humanize(a.status)}</StatusText>
                      {a.origin !== "screening" && <div className="mt-0.5 text-[11px] text-faint">{humanize(a.origin)}</div>}
                    </td>
                    <td className="whitespace-nowrap text-faint">{shortTime(a.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
