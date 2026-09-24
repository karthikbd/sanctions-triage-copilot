import { useEffect, useState } from "react";
import { Play, Sparkles } from "lucide-react";
import { api, post, runJob, type CustomersInfo, type Job } from "../api";
import { useApp } from "../App";
import { Badge, Button, Callout, Card, Empty, Field, fmt, humanize, KV, Progress, Select, shortTime } from "../components/ui";

/** "us_ofac_sdn@20260924044053-hka+..." -> "OpenSanctions 2026-09-24"; other versions pass through. */
function listLabel(v: string): string {
  const m = /@(\d{4})(\d{2})(\d{2})/.exec(v);
  return m ? `OpenSanctions ${m[1]}-${m[2]}-${m[3]}` : `list ${v}`;
}

export function BookPage() {
  const { version, refresh, go, isAdmin, requireAdmin, health } = useApp();
  const [c, setC] = useState<CustomersInfo | null>(null);
  const [n, setN] = useState(2000);
  const [job, setJob] = useState<Job | null>(null);
  const [msg, setMsg] = useState<{ tone: "green" | "red" | "blue"; text: string } | null>(null);

  const load = () => api<CustomersInfo>("/api/customers?limit=12").then(setC).catch(() => {});
  useEffect(() => { load(); }, [version]);

  const needAdmin = () => { if (health?.admin_required && !isAdmin) { requireAdmin(); return true; } return false; };
  const busy = job?.status === "running";

  const generate = async () => {
    if (needAdmin()) return;
    setMsg({ tone: "blue", text: "Generating customers (SDV + Faker)…" });
    try {
      const done = await runJob(await post<Job>("/api/customers/generate", { n, use_sdv: true }), setJob);
      if (done.status === "failed") throw new Error(done.error || "failed");
      const r = done.result as Record<string, number | string>;
      setMsg({ tone: "green", text: `Generated ${fmt(Number(r.customers))} customers (${r.method}). Planted ${r.planted_true_matches} true matches and ${r.planted_near_misses} near-misses from ${r.list_source}.` });
      await load();
    } catch (e) { setMsg({ tone: "red", text: (e as Error).message }); }
  };

  const screenAll = async () => {
    if (needAdmin()) return;
    setMsg({ tone: "blue", text: "Screening the whole book…" });
    try {
      const done = await runJob(await post<Job>("/api/customers/screen"), setJob);
      if (done.status === "failed") throw new Error(done.error || "failed");
      setMsg({ tone: "green", text: "Batch screening finished. New alerts are in the queue." });
      await load(); await refresh();
    } catch (e) { setMsg({ tone: "red", text: (e as Error).message }); }
  };

  const L = c?.last_batch;
  const pct = job?.total ? (100 * job.progress) / job.total : busy ? 20 : 100;

  return (
    <div className="grid gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
      <div className="space-y-4">
        <Card title="What is the customer book?" bodyClass="p-4 space-y-2 text-[12.5px] text-muted">
          <p>Screening compares <b className="text-fg">your customers</b> against <b className="text-fg">sanctions lists</b>. The lists are real (see Watchlists). A bank's customer data is confidential, so the book is <b className="text-fg">synthetic</b>:</p>
          <ul className="list-disc space-y-1 pl-4">
            <li><b className="text-fg">SDV</b> models realistic attributes (segment, country, age, turnover, PEP, risk rating, FATF high-risk countries).</li>
            <li><b className="text-fg">Faker</b> fills in names, addresses and IDs.</li>
            <li>Real listed names are <b className="text-fg">planted</b> with typos, transliterations and partial dates of birth, plus same-name near-misses, so recall and false-positive handling can be measured.</li>
          </ul>
        </Card>
        <Card title="Run">
          <div className="space-y-3">
            <Field label="Customers to generate">
              <Select value={n} onChange={(e) => setN(Number(e.target.value))}>
                {[500, 1000, 2000].map((x) => <option key={x} value={x}>{fmt(x)}</option>)}
              </Select>
            </Field>
            <Button className="w-full" disabled={busy} onClick={generate}><Sparkles size={14} />Generate customer book</Button>
            <Button variant="primary" className="w-full" disabled={busy || !c?.count} onClick={screenAll}><Play size={14} />Screen entire book</Button>
            {busy && <Progress value={pct} />}
            {msg && <Callout tone={msg.tone}>{msg.text}</Callout>}
            <p className="text-[11.5px] text-faint">Larger books (10k+) run in the Docker worker on GitHub Actions.</p>
          </div>
        </Card>
      </div>

      <div className="space-y-4">
        <Card title="Last batch run" actions={L && <span className="text-[11.5px] text-faint">{shortTime(L.finished_at)} · {listLabel(L.list_version)}</span>}>
          {!L ? <Empty title="Not run yet">Generate a book, then screen it to see recall and alert volumes.</Empty> : (
            <div className="grid gap-6 sm:grid-cols-2">
              <KV rows={[
                ["Customers screened", fmt(L.customers)],
                ["Customers with a hit", `${fmt(L.customers_with_hits)} (${((100 * L.customers_with_hits) / Math.max(1, L.customers)).toFixed(1)}%)`],
                ["New alerts · repeat hits", `${fmt(L.new_alerts)} · ${fmt(L.repeat_hits)}`],
                ["Auto-closed · to analysts", `${fmt(L.auto_closed)} · ${fmt(L.pending_review)}`],
                ["Speed", `${L.ms_per_customer} ms / customer`],
              ]} />
              <KV rows={[
                [<b className="text-fg">Recall on planted true matches</b>, <b>{L.planted_recall == null ? "–" : `${(100 * L.planted_recall).toFixed(1)}%`} <span className="font-normal text-faint">({L.planted_found}/{L.planted_true_matches})</span></b>],
                ["Planted matches wrongly auto-closed", L.planted_found - L.planted_found_not_auto_closed],
                ["Near-miss alerts auto-closed", `${fmt(L.near_miss_auto_closed)} of ${fmt(L.near_misses)}`],
              ]} />
              {L.missed.length > 0 && (
                <div className="sm:col-span-2">
                  <div className="mb-1 text-[12px] font-medium">Missed planted matches</div>
                  <ul className="space-y-0.5 text-[12px] text-muted">
                    {L.missed.slice(0, 6).map((m, i) => <li key={i}>{m.name} → <span className="font-mono text-[11px]">{m.list_uid}</span> <span className="text-faint">({m.method})</span></li>)}
                  </ul>
                </div>
              )}
              <div className="sm:col-span-2"><Button size="sm" onClick={() => go("alerts")}>Open the alert queue</Button></div>
            </div>
          )}
        </Card>

        <Card title="Customers" actions={c && c.count > 0 && (
          <span className="text-[11.5px] text-faint">{fmt(c.count)} total · {fmt(c.planted_true_matches)} planted matches · {fmt(c.planted_near_misses)} near-misses</span>
        )} bodyClass="p-0">
          {!c?.count ? <Empty title="No customer book yet">Generate one on the left.</Empty> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-[12.5px]">
                <thead className="bg-subtle text-[11.5px] text-muted">
                  <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:text-left [&>th]:font-medium"><th>ID</th><th>Name</th><th>Country</th><th>Segment</th><th>Risk</th></tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {c.sample.map((r) => (
                    <tr key={r.customer_id} className="[&>td]:px-3 [&>td]:py-2">
                      <td className="font-mono text-[11.5px] text-muted">{r.customer_id}</td>
                      <td><div className="font-medium">{r.name}</div><div className="text-[11.5px] text-faint">{humanize(r.party_type)}</div></td>
                      <td>{r.country}</td>
                      <td className="text-muted">{humanize(r.segment)}</td>
                      <td><Badge tone={r.risk_rating === "high" ? "red" : r.risk_rating === "medium" ? "amber" : "green"}>{r.risk_rating}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
