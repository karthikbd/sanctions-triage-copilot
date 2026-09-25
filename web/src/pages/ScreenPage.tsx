import { useEffect, useState } from "react";
import { ArrowRight, Eraser, Play, TriangleAlert } from "lucide-react";
import { api, post, type Party, type PartyType, type Scenario, type ScreeningResult } from "../api";
import { useApp } from "../App";
import { Badge, Button, Callout, Card, cx, Field, fmt, humanize, Input, Select, StatusText, statusTone, Textarea, verdictTone } from "../components/ui";
import { CountryPicker, DobPicker, dobError } from "../components/pickers";

const EMPTY: Party = { name: "", party_type: "individual", id_numbers: [] };

const OUTCOME: Record<ScreeningResult["outcome"], { title: string; sub: string; tone: "green" | "blue" | "gray" | "red" }> = {
  clear: { title: "No potential matches", sub: "Nothing on the loaded lists resembles this party.", tone: "green" },
  review: { title: "Sent to the analyst queue", sub: "At least one potential match needs a human decision.", tone: "blue" },
  auto_closed: { title: "Auto-closed as a false positive", sub: "Closed on deterministic evidence; eligible for QA sampling.", tone: "gray" },
  suppressed: { title: "Hit suppressed (previously cleared)", sub: "Same customer data and list entry as an alert an analyst already cleared.", tone: "gray" },
  blocked: { title: "Confirmed sanctioned party", sub: "An analyst has already confirmed this match. Keep blocked.", tone: "red" },
};

export function ScreenPage() {
  const { health, openAlert, refresh } = useApp();
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [active, setActive] = useState<number | null>(null);
  const [p, setP] = useState<Party>(EMPTY);
  const [ids, setIds] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<ScreeningResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const listKey = `${health?.list_source}|${health?.list_version}`;
  useEffect(() => {
    let dead = false;
    const load = (attempt: number) => api<Scenario[]>("/api/scenarios")
      .then((s) => { if (dead) return; if (s.length || attempt >= 3) setScenarios(s); else setTimeout(() => load(attempt + 1), 1500); })
      .catch(() => { if (!dead && attempt < 3) setTimeout(() => load(attempt + 1), 1500); });
    load(0);
    return () => { dead = true; };
  }, [listKey]);

  const set = (k: keyof Party) => (e: { target: { value: string } }) => setP((x) => ({ ...x, [k]: e.target.value }));
  const setVal = (k: keyof Party) => (v: string) => setP((x) => ({ ...x, [k]: v }));

  const screen = async (party: Party) => {
    setBusy(true); setErr(null);
    const body: Party = { ...party, name: party.name.trim() };
    for (const k of ["dob", "country", "nationality", "notes"] as const) if (!body[k]) delete body[k];
    try { setRes(await post<ScreeningResult>("/api/screen", body)); await refresh(); }
    catch (e) { setRes(null); setErr((e as Error).message); }
    finally { setBusy(false); }
  };

  const pick = (i: number) => {
    const s = scenarios[i];
    setActive(i); setP({ ...EMPTY, ...s.party }); setIds((s.party.id_numbers || []).join(", "));
    screen(s.party);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const bad = dobError(p.dob ?? "");
    if (bad) { setRes(null); setErr(`Date of birth: ${bad}`); return; }
    screen({ ...p, id_numbers: ids.split(",").map((x) => x.trim()).filter(Boolean) });
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="space-y-4">
        <Card title="Try a test case" bodyClass="p-2">
          <p className="px-3 pt-1 pb-2 text-[12px] text-muted">
            One-click test customers, one for each kind of alert an L1 analyst sees every day. Most are built from
            real entries on the loaded list ({fmt(health?.list_size)} entries), so each click runs a genuine screening and
            shows how the copilot routes it. Screening the same customer twice links to the open alert, so no duplicates.
          </p>
          {scenarios.length === 0 && <div className="px-3 pb-2 text-[12px] text-faint">Loading test cases…</div>}
          <div className="grid gap-1 sm:grid-cols-2">
            {scenarios.map((s, i) => {
              const [what, expect] = s.description.split(/\s*Expect:\s*/);
              return (
                <button key={i} onClick={() => pick(i)} disabled={busy}
                        className={cx("flex flex-col justify-start rounded-md border border-transparent px-3 py-2 text-left hover:border-line hover:bg-subtle disabled:opacity-60", active === i && "border-line bg-sunken")}>
                  <div className="flex items-center gap-1.5 text-[12.5px] font-medium"><Play size={11} className="text-brand" />{s.title}</div>
                  <div className="mt-0.5 line-clamp-2 text-[11.5px] text-faint">{what}</div>
                  {expect && <div className="mt-1 text-[11.5px]"><span className="text-faint">Expected: </span><span className="text-muted">{expect.replace(/\.$/, "")}</span></div>}
                </button>
              );
            })}
          </div>
        </Card>

        <Card title="Party details">
          <form onSubmit={submit} className="space-y-3" autoComplete="off">
            <Field label="Name"><Input required value={p.name} onChange={set("name")} placeholder="Full name, company or vessel" /></Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Type">
                <Select value={p.party_type} onChange={(e) => setP((x) => ({ ...x, party_type: e.target.value as PartyType }))}>
                  {["individual", "entity", "vessel", "unknown"].map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
                </Select>
              </Field>
              <Field label="Date of birth" htmlFor="dob"><DobPicker id="dob" value={p.dob ?? ""} onChange={setVal("dob")} /></Field>
              <Field label="Country" htmlFor="country"><CountryPicker id="country" value={p.country ?? ""} onChange={setVal("country")} /></Field>
              <Field label="Nationality" htmlFor="nationality"><CountryPicker id="nationality" value={p.nationality ?? ""} onChange={setVal("nationality")} placeholder="Search nationalities" /></Field>
            </div>
            <Field label="ID numbers" hint="Passport, IMO, registration. Comma-separated.">
              <Input value={ids} onChange={(e) => setIds(e.target.value)} />
            </Field>
            <Field label="Free text" hint="KYC notes or payment remittance info. Treated as untrusted and scanned for prompt injection.">
              <Textarea value={p.notes ?? ""} onChange={set("notes")} />
            </Field>
            <div className="flex gap-2">
              <Button variant="primary" className="flex-1" disabled={busy}>{busy ? "Screening…" : "Screen"}</Button>
              <Button type="button" onClick={() => { setP(EMPTY); setIds(""); setRes(null); setErr(null); setActive(null); }}><Eraser size={13} />Clear</Button>
            </div>
          </form>
        </Card>
      </div>

      <div className="space-y-4 lg:sticky lg:top-0 lg:self-start">
        <Card title="Result">
          {err ? <Callout tone="red">{err}</Callout> : !res ? (
            <div className="py-10 text-center text-[12.5px] text-muted">Pick a scenario or fill in the form, then screen.</div>
          ) : (
            <div className="space-y-4">
              <div>
                <StatusText tone={OUTCOME[res.outcome].tone}><span className="text-[14px] font-semibold">{OUTCOME[res.outcome].title}</span></StatusText>
                <p className="mt-0.5 pl-3.5 text-[12.5px] text-muted">{OUTCOME[res.outcome].sub}</p>
              </div>
              {res.injection_flags.length > 0 && (
                <Callout tone="red">
                  <span className="inline-flex items-center gap-1.5 font-semibold"><TriangleAlert size={14} />Prompt injection detected in the free text</span>
                  <div className="mt-0.5">{res.injection_flags.join(" | ")}. Automatic closure disabled; case flagged high priority.</div>
                </Callout>
              )}
              {(res.alerts.length > 0 || res.repeat_hits.length > 0) && (
                <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
                  {res.alerts.map((a) => (
                    <li key={a.alert_id}>
                      <button onClick={() => openAlert(a.alert_id)} className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-subtle">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[12.5px] font-medium">{a.candidate.entry.name}</div>
                          <div className="font-mono text-[11px] text-faint">{a.alert_id} · score {a.candidate.name_score.toFixed(1)}</div>
                        </div>
                        <Badge tone={verdictTone(a.decision.verdict)}>{humanize(a.decision.verdict)}</Badge>
                        <StatusText tone={statusTone(a.status)}><span className="text-[12px]">{humanize(a.status)}</span></StatusText>
                        <ArrowRight size={14} className="text-faint" />
                      </button>
                    </li>
                  ))}
                  {res.repeat_hits.map((h) => (
                    <li key={h.alert_id + h.list_uid}>
                      <button onClick={() => openAlert(h.alert_id)} className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-subtle">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[12.5px] font-medium">↺ {h.list_name}</div>
                          <div className="text-[11.5px] text-faint">{h.detail}</div>
                        </div>
                        <ArrowRight size={14} className="text-faint" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="font-mono text-[11px] text-faint">
                {res.list_source} · {fmt(res.list_size)} entries · {Math.round(res.duration_ms)} ms · {res.request_id}
              </div>
            </div>
          )}
        </Card>
        <Card title="How triage works" bodyClass="p-4 text-[12.5px] text-muted space-y-1.5">
          <p><b className="text-fg">1. Screen.</b> Fuzzy and phonetic name matching across aliases and transliterations.</p>
          <p><b className="text-fg">2. Signals.</b> Date of birth, country, IDs and party type are compared in code.</p>
          <p><b className="text-fg">3. Recommend.</b> An adjudicator (rules, or Claude when an API key is set) proposes a verdict.</p>
          <p><b className="text-fg">4. Guardrails.</b> Only hard contradictions auto-close. True matches and injection attempts always go to a human.</p>
        </Card>
      </div>
    </div>
  );
}
