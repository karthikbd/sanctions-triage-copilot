import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");
export const fmt = (n: number | null | undefined) => (n ?? 0).toLocaleString();
export const humanize = (s: string | null | undefined) => String(s ?? "").replace(/_/g, " ");

export function ago(ts: string | null | undefined): string {
  if (!ts) return "never";
  const s = (Date.now() - Date.parse(ts)) / 1000;
  if (Number.isNaN(s)) return ts;
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

export function shortTime(ts: string): string {
  const d = new Date(ts);
  return Number.isNaN(+d) ? ts : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// ---------------------------------------------------------------------------------------------------------------------

type Tone = "red" | "amber" | "green" | "blue" | "gray" | "brand";
const toneCls: Record<Tone, string> = {
  red: "bg-red-soft text-red",
  amber: "bg-amber-soft text-amber",
  green: "bg-green-soft text-green",
  blue: "bg-blue-soft text-blue",
  gray: "bg-gray-soft text-muted",
  brand: "bg-brand-soft text-brand",
};
const dotCls: Record<Tone, string> = {
  red: "bg-red", amber: "bg-amber", green: "bg-green", blue: "bg-blue", gray: "bg-faint", brand: "bg-brand",
};

export const verdictTone = (v: string): Tone => (v === "true_match" ? "red" : v === "false_positive" ? "green" : "amber");
export const statusTone = (s: string): Tone =>
  ({ pending_review: "blue", auto_closed: "gray", confirmed_match: "red", cleared: "green" } as Record<string, Tone>)[s] ?? "gray";
export const priorityTone = (p: string): Tone => (p === "high" ? "red" : p === "medium" ? "amber" : "green");
export const signalTone = (o: string): Tone =>
  ({ exact: "red", match: "red", near: "amber", mismatch: "green" } as Record<string, Tone>)[o] ?? "gray";

export function Badge({ tone = "gray", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-md px-1.5 py-px text-[11.5px] font-medium whitespace-nowrap", toneCls[tone], className)}>
      {children}
    </span>
  );
}

export function Dot({ tone = "gray", pulse }: { tone?: Tone; pulse?: boolean }) {
  return (
    <span className="relative inline-flex size-2 shrink-0">
      {pulse && <span className={cx("absolute inset-0 animate-ping rounded-full opacity-60", dotCls[tone])} />}
      <span className={cx("relative inline-flex size-2 rounded-full", dotCls[tone])} />
    </span>
  );
}

export function StatusText({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className="inline-flex items-center gap-1.5 whitespace-nowrap"><Dot tone={tone} />{children}</span>;
}

// ---------------------------------------------------------------------------------------------------------------------

type BtnVariant = "primary" | "secondary" | "ghost" | "danger";
export function Button({ variant = "secondary", size = "md", className, ...p }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: "sm" | "md" }) {
  return (
    <button
      {...p}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-7 px-2.5 text-[12px]" : "h-8 px-3 text-[13px]",
        variant === "primary" && "bg-primary text-primary-fg hover:opacity-90",
        variant === "secondary" && "border border-line bg-bg hover:bg-subtle",
        variant === "ghost" && "text-muted hover:bg-sunken hover:text-fg",
        variant === "danger" && "border border-line bg-bg text-red hover:bg-red-soft",
        className,
      )}
    />
  );
}

const inputCls = "w-full rounded-md border border-line bg-bg px-2.5 py-1.5 text-[13px] placeholder:text-faint focus:border-focus focus:outline-none";
export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cx(inputCls, "h-8", p.className)} />;
export const Select = (p: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cx(inputCls, "h-8", p.className)} />;
export const Textarea = (p: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={cx(inputCls, "min-h-16 resize-y", p.className)} />;

export function Field({ label, hint, children, className }: { label: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <label className={cx("block", className)}>
      <span className="mb-1 block text-[12px] font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11.5px] text-faint">{hint}</span>}
    </label>
  );
}

export function Card({ title, actions, children, className, bodyClass }:
  { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string }) {
  return (
    <section className={cx("rounded-lg border border-line bg-bg", className)}>
      {(title || actions) && (
        <header className="flex min-h-10 items-center justify-between gap-3 border-b border-line px-4 py-2">
          <h2 className="text-[13px] font-semibold">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={cx("p-4", bodyClass)}>{children}</div>
    </section>
  );
}

export function StatStrip({ items }: { items: { label: string; value: ReactNode; sub?: ReactNode }[] }) {
  return (
    <div className="grid grid-cols-2 overflow-hidden rounded-lg border border-line bg-bg sm:grid-cols-3 lg:grid-cols-5">
      {items.map((it, i) => (
        <div key={it.label} className={cx("px-4 py-3", i > 0 && "border-line max-sm:odd:border-l-0 sm:border-l", i >= 2 && "max-sm:border-t", i >= 3 && "sm:max-lg:border-t")}>
          <div className="text-[12px] text-muted">{it.label}</div>
          <div className="tnum mt-0.5 text-[20px] font-semibold leading-7">{it.value}</div>
          {it.sub && <div className="text-[11.5px] text-faint">{it.sub}</div>}
        </div>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, items }:
  { value: T; onChange: (v: T) => void; items: { value: T; label: ReactNode; count?: number }[] }) {
  return (
    <div className="flex gap-1 overflow-x-auto" role="tablist">
      {items.map((it) => (
        <button
          key={it.value}
          role="tab"
          aria-selected={value === it.value}
          onClick={() => onChange(it.value)}
          className={cx(
            "inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 text-[12.5px] font-medium",
            value === it.value ? "bg-sunken text-fg" : "text-muted hover:text-fg",
          )}
        >
          {it.label}
          {it.count !== undefined && <span className="tnum text-[11px] text-faint">{fmt(it.count)}</span>}
        </button>
      ))}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="px-6 py-12 text-center">
      <div className="text-[13px] font-medium">{title}</div>
      {children && <div className="mx-auto mt-1 max-w-md text-[12.5px] text-muted">{children}</div>}
    </div>
  );
}

export function KV({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1.5 text-[12.5px]">
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="tnum text-right font-medium">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Progress({ value }: { value: number }) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-sunken">
      <div className="h-full rounded-full bg-brand transition-[width] duration-300" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function Callout({ tone = "blue", children }: { tone?: Tone; children: ReactNode }) {
  return <div className={cx("rounded-md px-3 py-2 text-[12.5px]", toneCls[tone])}>{children}</div>;
}
