import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { post, runJob, type Job } from "../api";
import { useApp } from "../App";
import { ago, Badge, Button, Callout, Card, Empty, fmt, KV } from "../components/ui";

export function ListsPage() {
  const { lists: l, health, refresh, isAdmin, requireAdmin } = useApp();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "green" | "red" | "blue"; text: string } | null>(null);

  const check = async () => {
    if (health?.admin_required && !isAdmin) return requireAdmin();
    setBusy(true); setMsg({ tone: "blue", text: "Checking OpenSanctions for new list versions… a full load takes up to a couple of minutes." });
    try {
      const done = await runJob(await post<Job>("/api/lists/refresh"), () => {});
      if (done.status === "failed") throw new Error(done.error || "failed");
      const r = done.result as { updated?: boolean; entities?: number } | null;
      setMsg({ tone: "green", text: r?.updated === false ? "Already up to date." : `Updated: ${fmt(r?.entities)} entries loaded.` });
      await refresh();
    } catch (e) { setMsg({ tone: "red", text: (e as Error).message }); }
    finally { setBusy(false); }
  };

  const D = l?.last_delta;
  const live = health?.backend === "postgres";
  const sample = l?.version === "static";

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="space-y-4">
        <Card title="Loaded sanctions lists" actions={<Button size="sm" onClick={check} disabled={busy}><RefreshCw size={13} className={busy ? "animate-spin" : ""} />Check for list updates</Button>} bodyClass="p-0">
          {!l ? <Empty title="Loading…" /> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-[12.5px]">
                <thead className="bg-subtle text-[11.5px] text-muted">
                  <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:text-left [&>th]:font-medium"><th>Dataset</th><th className="!text-right">Entities</th><th>Version</th><th>Source</th></tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {l.datasets.map((d) => (
                    <tr key={d.name} className="[&>td]:px-3 [&>td]:py-2">
                      <td><div className="font-medium">{d.name}</div>{d.error && <div className="text-[11.5px] text-red">{d.error}</div>}</td>
                      <td className="tnum text-right">{fmt(d.entities)}</td>
                      <td className="font-mono text-[11.5px] text-muted">{d.version || "–"}</td>
                      <td className="text-muted">{d.source || "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        {msg && <Callout tone={msg.tone}>{msg.text}</Callout>}
        {sample && (
          <Callout tone="amber">
            This is the small <b>fictional sample list</b>. {live
              ? <>Click <b>Check for list updates</b> (admin) to load the real OFAC SDN, UN, EU and UK lists from OpenSanctions into Supabase.</>
              : <>The real lists need the database: once Supabase is connected, <b>Check for list updates</b> loads OFAC SDN, UN, EU and UK lists.</>}
          </Callout>
        )}
        <Card title="Last update">
          {!D ? <Empty title="No updates applied yet" /> : D.updated === false ? <p className="text-[12.5px] text-muted">No changes.</p> : (
            <p className="text-[12.5px]">
              {D.baseline ? "Baseline load" : "Delta vs previous version"}: <b className="text-green">+{fmt(D.added)}</b> added, <b className="text-amber">{fmt(D.changed)}</b> changed, <b className="text-red">{fmt(D.removed)}</b> removed.{" "}
              {D.rescreen ? <>Re-screened {fmt(D.rescreen.customers)} customers against the new and changed entries: <b>{fmt(D.rescreen.new_alerts)}</b> new alerts.</>
                : <span className="text-muted">Only new and changed entries are re-screened against the customer book.</span>}
            </p>
          )}
        </Card>
      </div>

      <div className="space-y-4">
        <Card title="Status">
          {l && (
            <KV rows={[
              ["Source", <span className="font-normal">{l.source}</span>],
              ["Entries", fmt(l.entities)],
              ["Status", <Badge tone={l.status === "ready" ? "green" : l.status === "loading" ? "blue" : l.status === "demo" ? "amber" : "red"}>{l.status}</Badge>],
              ["Storage", live ? "Supabase Postgres" : "temporary"],
              ["Last check", ago(l.last_refresh)],
              ["Schedule", <span className="font-normal">{l.schedule}</span>],
            ]} />
          )}
        </Card>
        <Card title="Where the data comes from" bodyClass="p-4 space-y-2 text-[12.5px] text-muted">
          <p><b className="text-fg">OpenSanctions</b> republishes the official lists (US OFAC SDN, UN Security Council, EU Financial Sanctions, UK FCDO) in one schema, several times a day.</p>
          <p>Each refresh compares entry fingerprints with the previous version. Only <b className="text-fg">added or changed</b> entries are re-screened against the customer book, which is how banks keep screening near real-time without rescanning everything.</p>
          {l?.attribution && <p className="text-[11.5px] text-faint">{l.attribution}</p>}
        </Card>
      </div>
    </div>
  );
}
