import { useEffect, useState } from "react";
import { Check, CircleAlert, Link2, TriangleAlert, X } from "lucide-react";
import { api, post, type Alert, type AuditRecord, type Verdict } from "../api";
import { useApp } from "../App";
import {
  Badge, Button, Callout, cx, Field, humanize, Input, priorityTone, Progress, shortTime, signalTone, StatusText, statusTone,
  Tabs, verdictTone,
} from "./ui";

type Tab = "overview" | "evidence" | "audit";

export function AlertDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { refresh, isAdmin, requireAdmin, health } = useApp();
  const [a, setA] = useState<Alert | null>(null);
  const [trail, setTrail] = useState<AuditRecord[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [err, setErr] = useState<string | null>(null);

  const load = async () => {
    try {
      const [alert, t] = await Promise.all([api<Alert>(`/api/alerts/${id}`), api<AuditRecord[]>(`/api/alerts/${id}/audit`)]);
      setA(alert); setTrail(t); setErr(null);
    } catch (e) { setErr((e as Error).message); }
  };
  useEffect(() => { setA(null); setTab("overview"); load(); /* eslint-disable-next-line */ }, [id]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  const needAdmin = !!health?.admin_required && !isAdmin;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-black/20 dark:bg-black/50" onClick={onClose} />
      <aside role="dialog" aria-label={`Alert ${id}`}
             className="animate-slide-in relative flex h-full w-full max-w-[860px] flex-col border-l border-line bg-bg shadow-2xl">
        <header className="flex shrink-0 items-start gap-3 border-b border-line px-5 py-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[12px] text-muted">{id}</span>
              {a && <StatusText tone={statusTone(a.status)}>{humanize(a.status)}</StatusText>}
              {a && <Badge tone={priorityTone(a.priority)}>{a.priority} priority</Badge>}
              {a && a.origin !== "screening" && <Badge>{humanize(a.origin)}</Badge>}
            </div>
            <h2 className="mt-1 truncate text-[15px] font-semibold">
              {a ? <>{a.party.name} <span className="font-normal text-faint">vs</span> {a.candidate.entry.name}</> : "Loading…"}
            </h2>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close"><X size={16} /></Button>
        </header>

        {err && <div className="p-5"><Callout tone="red">{err}</Callout></div>}
        {a && (
          <>
            <div className="shrink-0 border-b border-line px-4 py-2">
              <Tabs<Tab> value={tab} onChange={setTab} items={[
                { value: "overview", label: "Overview" },
                { value: "evidence", label: "Evidence" },
                { value: "audit", label: "Audit trail", count: trail.length },
              ]} />
            </div>
            <div className="scroll-thin min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
              {(a.injection_flags.length > 0 || a.decision.suspected_injection) && (
                <Callout tone="red">
                  <span className="inline-flex items-center gap-1.5 font-semibold"><TriangleAlert size={14} />Possible prompt injection in the free text</span>
                  <div className="mt-0.5">{a.injection_flags.length ? `${a.injection_flags.join(" | ")}.` : "Flagged by the model."} Automatic closure is disabled for this alert.</div>
                </Callout>
              )}
              {tab === "overview" && <Overview a={a} needAdmin={needAdmin} onAdmin={() => requireAdmin()} onDone={async () => { await load(); await refresh(); }} />}
              {tab === "evidence" && <Evidence a={a} />}
              {tab === "audit" && <Audit trail={trail} />}
            </div>
          </>
        )}
      </aside>
    </div>
  );
}

function Section({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[11.5px] font-semibold uppercase tracking-wide text-faint">{title}</h3>{aside}
      </div>
      {children}
    </section>
  );
}

function Overview({ a, needAdmin, onAdmin, onDone }: { a: Alert; needAdmin: boolean; onAdmin: () => void; onDone: () => Promise<void> }) {
  const d = a.decision;
  const [analyst, setAnalyst] = useState("analyst.1");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<Verdict | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const decide = async (outcome: Verdict) => {
    if (needAdmin) return onAdmin();
    setBusy(outcome); setErr(null);
    try { await post(`/api/alerts/${a.alert_id}/review`, { analyst: analyst.trim() || "analyst", outcome, comment: comment.trim() }); await onDone(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(null); }
  };
  return (
    <>
      <Section title="Recommendation" aside={<span className="text-[11.5px] text-faint">{d.adjudicator}{d.latency_ms ? ` · ${Math.round(d.latency_ms)} ms` : ""}</span>}>
        <div className="rounded-lg border border-line p-4">
          <div className="flex items-center gap-3">
            <Badge tone={verdictTone(d.verdict)} className="text-[12.5px]">{humanize(d.verdict)}</Badge>
            <div className="flex-1"><Progress value={d.confidence * 100} /></div>
            <span className="tnum text-[12px] text-muted">{Math.round(d.confidence * 100)}% confidence</span>
          </div>
          <p className="mt-3 text-[13px] leading-relaxed">{d.rationale}</p>
          {d.next_steps.length > 0 && (
            <ul className="mt-2 list-disc space-y-0.5 pl-5 text-[12.5px] text-muted">{d.next_steps.map((x, i) => <li key={i}>{x}</li>)}</ul>
          )}
          {d.notes.length > 0 && <div className="mt-2 space-y-0.5 text-[12px] text-faint">{d.notes.map((n, i) => <div key={i}>{n}</div>)}</div>}
        </div>
      </Section>

      <Section title="Policy">
        <ul className="space-y-1.5 text-[12.5px]">
          {a.policy_notes.map((n, i) => <li key={i} className="flex gap-2"><CircleAlert size={14} className="mt-0.5 shrink-0 text-faint" />{n}</li>)}
        </ul>
      </Section>

      <Section title="Analyst decision">
        {a.review ? (
          <div className="rounded-lg border border-line bg-subtle p-4 text-[12.5px]">
            <div className="flex flex-wrap items-center gap-2">
              <Check size={14} className="text-green" />
              <Badge tone={verdictTone(a.review.outcome)}>{humanize(a.review.outcome)}</Badge>
              <span className="text-muted">by <b className="text-fg">{a.review.analyst}</b> · {shortTime(a.review.reviewed_at)}</span>
            </div>
            {a.review.comment && <p className="mt-2">{a.review.comment}</p>}
          </div>
        ) : (
          <div className="space-y-3 rounded-lg border border-line p-4">
            <div className="grid gap-3 sm:grid-cols-[200px_1fr]">
              <Field label="Analyst ID"><Input value={analyst} onChange={(e) => setAnalyst(e.target.value)} /></Field>
              <Field label="Comment for the case file"><Input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="e.g. DOB mismatch confirmed against passport copy" /></Field>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button disabled={!!busy} onClick={() => decide("true_match")} className="border-red/40 text-red hover:bg-red-soft">Confirm match</Button>
              <Button disabled={!!busy} onClick={() => decide("false_positive")} className="border-green/40 text-green hover:bg-green-soft">Clear as false positive</Button>
              <Button disabled={!!busy} onClick={() => decide("escalate")}>Escalate to L2</Button>
            </div>
            {needAdmin && <div className="text-[12px] text-faint">Recording a decision needs the admin passcode.</div>}
            {err && <Callout tone="red">{err}</Callout>}
          </div>
        )}
      </Section>
    </>
  );
}

function Evidence({ a }: { a: Alert }) {
  const p = a.party, e = a.candidate.entry, s = a.candidate.signals;
  const rows: [string, React.ReactNode, React.ReactNode][] = [
    ["Name", p.name, <>{e.name}{a.candidate.matched_name !== e.name && <div className="text-[11.5px] text-faint">matched alias: {a.candidate.matched_name}</div>}</>],
    ["Type", humanize(p.party_type), humanize(e.party_type)],
    ["Date of birth", p.dob || "–", e.dobs.join("; ") || "–"],
    ["Country", [p.country, p.nationality].filter(Boolean).join(" / ") || "–", e.countries.join(", ") || "–"],
    ["IDs", p.id_numbers.join(", ") || "–", e.id_numbers.slice(0, 6).join(", ") || "–"],
    ["Programs", "", e.programs.join(", ") || "–"],
  ];
  const sig: [string, string, string][] = [
    ["Date of birth", s.dob, s.dob_detail], ["Country", s.country, s.country_detail],
    ["Identifier", s.id_number, s.id_detail], ["Party type", s.party_type, s.party_type_detail],
  ];
  return (
    <>
      <Section title="Customer vs listed party" aside={<span className="text-[11.5px] text-faint">name similarity <b className="tnum text-fg">{a.candidate.name_score}</b>/100</span>}>
        <div className="overflow-hidden rounded-lg border border-line">
          <table className="w-full text-[12.5px]">
            <thead className="bg-subtle text-[11.5px] text-muted">
              <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:text-left [&>th]:font-medium"><th className="w-32"></th><th>Customer</th><th>Listed ({e.source})</th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map(([k, c, l]) => (
                <tr key={k} className="[&>td]:px-3 [&>td]:py-2 [&>td]:align-top"><td className="text-muted">{k}</td><td>{c}</td><td>{l}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-1.5 flex items-center gap-1.5 font-mono text-[11px] text-faint"><Link2 size={12} />{e.uid}</div>
      </Section>

      <Section title="Deterministic signals">
        <div className="grid gap-2 sm:grid-cols-2">
          {sig.map(([name, out, detail]) => (
            <div key={name} className={cx("rounded-lg border border-line p-3")}>
              <div className="flex items-center justify-between">
                <span className="text-[12px] text-muted">{name}</span>
                <Badge tone={signalTone(out)}>{humanize(out)}</Badge>
              </div>
              <div className="mt-1 text-[12px] text-faint">{detail || "–"}</div>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[11.5px] text-faint">Computed in code, never by the model. Red supports a match, green contradicts it.</p>
      </Section>

      {d(a).length > 0 && (
        <Section title="Model evidence">
          <ul className="space-y-1 text-[12.5px]">
            {d(a).map((x, i) => <li key={i}><b>{x.factor}</b> <span className="text-faint">({humanize(x.assessment)})</span>: {x.detail}</li>)}
          </ul>
        </Section>
      )}
      {e.remarks && <Section title="List remarks"><p className="text-[12.5px] text-muted">{e.remarks}</p></Section>}
      {p.notes && (
        <Section title="Free text (untrusted)">
          <pre className="whitespace-pre-wrap rounded-lg bg-sunken p-3 font-mono text-[11.5px]">{p.notes}</pre>
        </Section>
      )}
    </>
  );
}
const d = (a: Alert) => a.decision.evidence ?? [];

function Audit({ trail }: { trail: AuditRecord[] }) {
  return (
    <Section title="Hash-chained events">
      <ol className="relative space-y-3 border-l border-line pl-4">
        {trail.map((t, i) => (
          <li key={i} className="relative">
            <span className="absolute -left-[21px] top-1.5 size-2.5 rounded-full border-2 border-bg bg-brand" />
            <div className="flex flex-wrap items-baseline gap-x-2 text-[12.5px]">
              <b>{humanize(t.event)}</b><span className="text-muted">by {t.actor}</span><span className="text-faint">{shortTime(t.ts)}</span>
            </div>
            <div className="mt-0.5 font-mono text-[11px] text-faint">sha256 {t.hash.slice(0, 16)}… ← {t.prev_hash.slice(0, 8)}…</div>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-[11.5px] text-faint">Each event stores the hash of the previous one, so any edit to history breaks the chain and shows in the sidebar.</p>
    </Section>
  );
}
