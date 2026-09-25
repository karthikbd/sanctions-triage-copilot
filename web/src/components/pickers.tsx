import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import { CalendarDays, Check, ChevronDown, ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import { api, type Country } from "../api";
import { cx } from "./ui";

// ---------------------------------------------------------------------------------------------------------------------
// Shared helpers

function useOutside(ref: RefObject<HTMLElement | null>, open: boolean, close: () => void) {
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) close(); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [ref, open, close]);
}

const fieldCls = "flex h-8 w-full items-center rounded-md border border-line bg-bg text-[13px] focus-within:border-focus";
const popCls = "absolute left-0 right-0 top-full z-30 mt-1 rounded-lg border border-line bg-bg shadow-lg shadow-black/10";

// ---------------------------------------------------------------------------------------------------------------------
// Countries: loaded once from the API (the same table the matcher uses), with aliases like UAE / DPRK / UK.

let countryCache: Promise<Country[]> | null = null;
function loadCountries(): Promise<Country[]> {
  if (!countryCache) countryCache = api<Country[]>("/api/countries").catch((e) => { countryCache = null; throw e; });
  return countryCache;
}

const fold = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();

function rank(c: Country, q: string): number {
  if (!q) return c.historic ? 1 : 0;
  const n = fold(c.name);
  if (c.code === q) return 0;
  if (n.startsWith(q)) return 1;
  if (c.aliases.some((a) => a === q || a.startsWith(q))) return 2;
  if (n.split(" ").some((w) => w.startsWith(q))) return 3;
  if (n.includes(q) || c.aliases.some((a) => a.includes(q))) return 4;
  return -1;
}

export function CountryPicker({ value, onChange, placeholder = "Search countries", id }:
  { value: string; onChange: (v: string) => void; placeholder?: string; id?: string }) {
  const [all, setAll] = useState<Country[]>([]);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [hi, setHi] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);

  useEffect(() => { loadCountries().then(setAll).catch(() => setFailed(true)); }, []);
  const close = () => { setOpen(false); setQ(""); };
  useOutside(box, open, close);

  const matches = useMemo(() => {
    const fq = fold(q);
    return all.map((c) => [c, rank(c, fq)] as const).filter(([, r]) => r >= 0)
      .sort((a, b) => a[1] - b[1] || fold(a[0].name).localeCompare(fold(b[0].name))).map(([c]) => c);
  }, [all, q]);

  useEffect(() => { setHi(0); }, [q]);
  useEffect(() => { list.current?.querySelector(`[data-i="${hi}"]`)?.scrollIntoView({ block: "nearest" }); }, [hi]);

  const choose = (c: Country) => { onChange(c.name); close(); input.current?.blur(); };
  const selected = all.find((c) => fold(c.name) === fold(value) || c.aliases.includes(fold(value)) || c.code === fold(value));

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setHi((h) => Math.min(h + 1, matches.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
    else if (e.key === "Enter" && open) { e.preventDefault(); if (matches[hi]) choose(matches[hi]); else if (q.trim()) { onChange(q.trim()); close(); } }
    else if (e.key === "Escape") { close(); }
    else if (e.key === "Tab" && open && q.trim()) { if (matches[hi]) onChange(matches[hi].name); close(); }
  };

  return (
    <div ref={box} className="relative" data-testid={id ? `${id}-picker` : undefined}>
      <div className={fieldCls}>
        <Search size={13} className="ml-2.5 shrink-0 text-faint" />
        <input
          ref={input} id={id} data-picker-input role="combobox" aria-expanded={open} aria-autocomplete="list" autoComplete="off"
          className="h-full min-w-0 flex-1 bg-transparent px-2 placeholder:text-faint focus:outline-none"
          value={open ? q : value} placeholder={open && value ? value : placeholder}
          onFocus={() => setOpen(true)} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onKeyDown={onKey}
        />
        {value && !open && (
          <button type="button" aria-label="Clear country" onClick={() => onChange("")} className="mr-1 rounded p-1 text-faint hover:bg-sunken hover:text-fg">
            <X size={13} />
          </button>
        )}
        <button type="button" tabIndex={-1} aria-label="Show countries" onClick={() => (open ? close() : input.current?.focus())}
                className="mr-1 rounded p-1 text-faint hover:bg-sunken hover:text-fg">
          <ChevronDown size={14} className={cx("transition-transform", open && "rotate-180")} />
        </button>
      </div>
      {value && !open && !selected && all.length > 0 && (
        <div className="mt-1 text-[11.5px] text-faint">Not in the list; it will be matched as typed.</div>
      )}
      {open && (
        <div className={popCls}>
          <ul ref={list} role="listbox" className="max-h-64 overflow-y-auto py-1">
            {failed && <li className="px-3 py-2 text-[12px] text-red">Couldn't load the country list. Type the country instead.</li>}
            {!failed && all.length === 0 && <li className="px-3 py-2 text-[12px] text-faint">Loading countries…</li>}
            {all.length > 0 && matches.length === 0 && (
              <li className="px-3 py-2 text-[12px] text-faint">No country matches "{q}". Press Enter to use it as typed.</li>
            )}
            {matches.map((c, i) => {
              const isSel = selected?.code === c.code;
              const alias = q && !fold(c.name).includes(fold(q)) ? c.aliases.find((a) => a.includes(fold(q))) : undefined;
              return (
                <li key={c.code} data-i={i} role="option" aria-selected={isSel}
                    onMouseDown={(e) => e.preventDefault()} onClick={() => choose(c)} onMouseEnter={() => setHi(i)}
                    className={cx("flex cursor-pointer items-center gap-2 px-3 py-1.5 text-[12.5px]", i === hi && "bg-sunken")}>
                  <span className="w-4 shrink-0">{isSel && <Check size={13} className="text-brand" />}</span>
                  <span className="min-w-0 flex-1 truncate">
                    {c.name}
                    {alias && <span className="ml-1.5 text-faint">({alias})</span>}
                    {c.historic && <span className="ml-1.5 text-[11px] text-faint">historic</span>}
                  </span>
                  <span className="font-mono text-[10.5px] uppercase text-faint">{c.code}</span>
                </li>
              );
            })}
          </ul>
          {all.length > 0 && <div className="border-t border-line px-3 py-1.5 text-[11px] text-faint">{matches.length} of {all.length} · ↑↓ to move, Enter to pick</div>}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// Date of birth: typed (YYYY-MM-DD / YYYY-MM / YYYY) or picked from a calendar. Sanctions lists often hold only a
// birth year, so the picker has a "Year only" mode too.

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const DOW = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
const pad = (n: number) => String(n).padStart(2, "0");
const MIN_YEAR = 1900;

export const DOB_RE = /^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$/;
export function dobError(v: string): string | null {
  if (!v) return null;
  const m = DOB_RE.exec(v.trim());
  if (!m) return "Use YYYY-MM-DD, YYYY-MM or YYYY.";
  const y = +m[1], mo = m[2] ? +m[2] : 1, d = m[3] ? +m[3] : 1;
  const now = new Date();
  if (y < MIN_YEAR || y > now.getFullYear()) return `Year must be between ${MIN_YEAR} and ${now.getFullYear()}.`;
  if (mo < 1 || mo > 12) return "Month must be 01-12.";
  const dt = new Date(y, mo - 1, d);
  if (dt.getMonth() !== mo - 1) return "That day doesn't exist in that month.";
  if (dt > now) return "Date of birth can't be in the future.";
  return null;
}

export function DobPicker({ value, onChange, id }: { value: string; onChange: (v: string) => void; id?: string }) {
  const now = new Date();
  const thisYear = now.getFullYear();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"date" | "year">("date");
  const [vy, setVy] = useState(1975);
  const [vm, setVm] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  useOutside(box, open, () => setOpen(false));

  const m = DOB_RE.exec(value.trim());
  const sel = m ? { y: +m[1], mo: m[2] ? +m[2] - 1 : null, d: m[3] ? +m[3] : null } : null;
  const err = dobError(value);

  const show = () => {
    if (sel) { setVy(Math.min(Math.max(sel.y, MIN_YEAR), thisYear)); setVm(sel.mo ?? 0); setMode(sel.mo === null ? "year" : "date"); }
    setOpen(true);
  };

  const shift = (delta: number) => {
    let y = vy, mo = vm + delta;
    if (mo < 0) { mo = 11; y -= 1; } else if (mo > 11) { mo = 0; y += 1; }
    if (y < MIN_YEAR || (y === thisYear && mo > now.getMonth()) || y > thisYear) return;
    setVy(y); setVm(mo);
  };

  const first = (new Date(vy, vm, 1).getDay() + 6) % 7; // Monday-first
  const days = new Date(vy, vm + 1, 0).getDate();
  const cells: (number | null)[] = [...Array(first).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)];
  const decade = Math.floor(vy / 12) * 12;
  const years = Array.from({ length: 12 }, (_, i) => decade + i);

  const pickDay = (d: number) => { onChange(`${vy}-${pad(vm + 1)}-${pad(d)}`); setOpen(false); };
  const pickYear = (y: number) => { onChange(String(y)); setOpen(false); };

  return (
    <div ref={box} className="relative" data-testid={id ? `${id}-picker` : undefined}>
      <div className={cx(fieldCls, err && "border-red")}>
        <input
          id={id} data-picker-input inputMode="numeric" autoComplete="off" value={value} placeholder="YYYY-MM-DD or YYYY"
          aria-invalid={!!err} onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); if (e.key === "ArrowDown" && e.altKey) show(); }}
          className="h-full min-w-0 flex-1 bg-transparent px-2.5 placeholder:text-faint focus:outline-none"
        />
        {value && (
          <button type="button" aria-label="Clear date of birth" onClick={() => onChange("")} className="mr-0.5 rounded p-1 text-faint hover:bg-sunken hover:text-fg">
            <X size={13} />
          </button>
        )}
        <button type="button" aria-label="Open calendar" aria-expanded={open} onClick={() => (open ? setOpen(false) : show())}
                className="mr-1 rounded p-1 text-muted hover:bg-sunken hover:text-fg">
          <CalendarDays size={14} />
        </button>
      </div>
      {err && <div className="mt-1 text-[11.5px] text-red">{err}</div>}

      {open && (
        <div className={cx(popCls, "w-[17.5rem] p-2.5")} role="dialog" aria-label="Choose date of birth">
          <div className="mb-2 flex rounded-md bg-sunken p-0.5 text-[12px]" role="tablist">
            {(["date", "year"] as const).map((k) => (
              <button key={k} type="button" role="tab" aria-selected={mode === k} onClick={() => setMode(k)}
                      className={cx("flex-1 rounded px-2 py-1 font-medium", mode === k ? "bg-bg text-fg shadow-sm" : "text-muted hover:text-fg")}>
                {k === "date" ? "Full date" : "Year only"}
              </button>
            ))}
          </div>

          {mode === "date" ? (
            <>
              <div className="mb-2 flex items-center gap-1">
                <button type="button" aria-label="Previous month" onClick={() => shift(-1)} className="rounded p-1 text-muted hover:bg-sunken hover:text-fg"><ChevronLeft size={15} /></button>
                <select aria-label="Month" value={vm} onChange={(e) => setVm(+e.target.value)}
                        className="h-7 min-w-0 flex-1 rounded-md border border-line bg-bg px-1.5 text-[12.5px] focus:border-focus focus:outline-none">
                  {MONTHS.map((n, i) => <option key={n} value={i} disabled={vy === thisYear && i > now.getMonth()}>{n}</option>)}
                </select>
                <select aria-label="Year" value={vy} onChange={(e) => { const y = +e.target.value; setVy(y); if (y === thisYear) setVm((x) => Math.min(x, now.getMonth())); }}
                        className="h-7 w-[4.6rem] rounded-md border border-line bg-bg px-1.5 text-[12.5px] focus:border-focus focus:outline-none">
                  {Array.from({ length: thisYear - MIN_YEAR + 1 }, (_, i) => thisYear - i).map((y) => <option key={y} value={y}>{y}</option>)}
                </select>
                <button type="button" aria-label="Next month" onClick={() => shift(1)} className="rounded p-1 text-muted hover:bg-sunken hover:text-fg"><ChevronRight size={15} /></button>
              </div>
              <div className="grid grid-cols-7 gap-0.5 text-center">
                {DOW.map((d) => <div key={d} className="py-1 text-[10.5px] font-medium text-faint">{d}</div>)}
                {cells.map((d, i) => {
                  if (d === null) return <div key={`e${i}`} />;
                  const future = new Date(vy, vm, d) > now;
                  const isSel = sel?.y === vy && sel?.mo === vm && sel?.d === d;
                  const isToday = vy === thisYear && vm === now.getMonth() && d === now.getDate();
                  return (
                    <button key={d} type="button" disabled={future} onClick={() => pickDay(d)} aria-label={`${d} ${MONTHS[vm]} ${vy}`}
                            className={cx("h-8 rounded-md text-[12.5px] tabular-nums disabled:cursor-not-allowed disabled:opacity-30",
                              isSel ? "bg-primary font-semibold text-primary-fg" : "hover:bg-sunken", isToday && !isSel && "ring-1 ring-line-strong")}>
                      {d}
                    </button>
                  );
                })}
              </div>
            </>
          ) : (
            <>
              <div className="mb-2 flex items-center justify-between">
                <button type="button" aria-label="Earlier years" disabled={decade <= MIN_YEAR} onClick={() => setVy(Math.max(MIN_YEAR, decade - 12))}
                        className="rounded p-1 text-muted hover:bg-sunken hover:text-fg disabled:opacity-30"><ChevronLeft size={15} /></button>
                <span className="text-[12.5px] font-medium tabular-nums">{decade} – {decade + 11}</span>
                <button type="button" aria-label="Later years" disabled={decade + 12 > thisYear} onClick={() => setVy(decade + 12)}
                        className="rounded p-1 text-muted hover:bg-sunken hover:text-fg disabled:opacity-30"><ChevronRight size={15} /></button>
              </div>
              <div className="grid grid-cols-4 gap-1">
                {years.map((y) => (
                  <button key={y} type="button" disabled={y > thisYear || y < MIN_YEAR} onClick={() => pickYear(y)}
                          className={cx("h-8 rounded-md text-[12.5px] tabular-nums disabled:opacity-30",
                            sel?.y === y && sel.mo === null ? "bg-primary font-semibold text-primary-fg" : "hover:bg-sunken")}>
                    {y}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-faint">Many list entries only record a birth year. Matching treats a year as a partial date.</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
