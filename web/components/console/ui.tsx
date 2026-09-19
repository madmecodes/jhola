"use client";

import type { ReactNode } from "react";
import { AlertTriangle, Inbox, RotateCw } from "lucide-react";
import type { OrderStatus } from "@/lib/jhola/types";

export const rs = (n: number | null | undefined) => `Rs ${Number(n ?? 0).toLocaleString("en-IN")}`;

export function timeAgo(iso: string) {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  return new Date(t).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function clockTime(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", second: "2-digit" });
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-line bg-paper shadow-[0_1px_0_rgba(31,42,90,0.04)] ${className}`}>{children}</div>;
}

export function SectionTitle({ title, hint, action, id }: { title: string; hint?: ReactNode; action?: ReactNode; id?: string }) {
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
      <div className="min-w-0">
        <h2 id={id} className="font-display text-xl font-semibold tracking-tight">{title}</h2>
        {hint ? <p className="mt-0.5 text-sm text-ink-soft">{hint}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function PageHeader({ title, hindi, children }: { title: string; hindi?: string; children?: ReactNode }) {
  return (
    <header className="mb-6">
      <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">
        {title}
        {hindi ? (
          <span lang="hi" className="font-hindi ml-3 align-middle text-xl font-normal text-jute">
            {hindi}
          </span>
        ) : null}
      </h1>
      {children ? <div className="mt-2 max-w-2xl text-ink-soft">{children}</div> : null}
    </header>
  );
}

const STATUS: Record<OrderStatus, { label: string; cls: string }> = {
  paid: { label: "Paid", cls: "bg-leaf-soft text-leaf border-leaf/30" },
  partially_paid: { label: "Partly paid", cls: "bg-leaf-soft text-leaf border-leaf/30" },
  pending_approval: { label: "Needs approval", cls: "bg-turmeric-soft text-[#7a5500] border-turmeric/50" },
  denied: { label: "Denied", cls: "bg-terracotta-soft text-terracotta border-terracotta/30" },
  rejected: { label: "Rejected", cls: "bg-terracotta-soft text-terracotta border-terracotta/30" },
};

export function StatusChip({ status }: { status: OrderStatus | string }) {
  const s = STATUS[status as OrderStatus] ?? { label: status, cls: "bg-sand text-ink border-line" };
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-semibold ${s.cls}`}>
      {s.label}
    </span>
  );
}

export function DecisionChip({ decision }: { decision: string }) {
  const allow = decision === "allow";
  return (
    <span
      className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-bold uppercase tracking-wide ${
        allow ? "bg-leaf-soft text-leaf" : "bg-terracotta-soft text-terracotta"
      }`}
    >
      {allow ? "Allow" : "Deny"}
    </span>
  );
}

export function PolicyChip({ id }: { id: string }) {
  return (
    <code className="inline-flex max-w-full items-center truncate rounded-md border border-ink/15 bg-cream px-1.5 py-0.5 font-mono text-[11px] text-ink">
      {id}
    </code>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-sand ${className}`} aria-hidden />;
}

export function SkeletonList({ rows = 3, className = "h-16" }: { rows?: number; className?: string }) {
  return (
    <div className="space-y-3" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={className} />
      ))}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-line bg-paper/60 px-6 py-10 text-center">
      <Inbox className="h-7 w-7 text-jute" aria-hidden />
      <p className="mt-2 font-semibold">{title}</p>
      {children ? <div className="mt-1 max-w-sm text-sm text-ink-soft">{children}</div> : null}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-2xl border border-terracotta/30 bg-terracotta-soft/60 px-4 py-3 text-sm text-ink">
      <AlertTriangle className="h-4 w-4 shrink-0 text-terracotta" aria-hidden />
      <span className="min-w-0 flex-1">{message}</span>
      {onRetry ? (
        <button type="button" onClick={onRetry} className="inline-flex items-center gap-1 rounded-full border border-ink/20 bg-paper px-3 py-1 text-xs font-semibold hover:border-ink/50">
          <RotateCw className="h-3.5 w-3.5" aria-hidden /> Retry
        </button>
      ) : null}
    </div>
  );
}

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "leaf" | "danger" | "ghost"; size?: "sm" | "md" };

export function Button({ variant = "primary", size = "md", className = "", ...rest }: BtnProps) {
  const v = {
    primary: "bg-ink text-cream hover:bg-ink/90",
    leaf: "bg-leaf text-white hover:bg-leaf/90",
    danger: "border border-terracotta/50 bg-paper text-terracotta hover:bg-terracotta-soft",
    ghost: "border border-ink/20 bg-paper text-ink hover:border-ink/50",
  }[variant];
  const sz = size === "sm" ? "px-3 py-1.5 text-xs" : "px-4 py-2 text-sm";
  return (
    <button
      type="button"
      {...rest}
      className={`inline-flex items-center justify-center gap-1.5 rounded-full font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${v} ${sz} ${className}`}
    />
  );
}

export function JsonBlock({ value }: { value: unknown }) {
  let text: string;
  try {
    text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  } catch {
    text = String(value);
  }
  return (
    <pre className="max-h-80 overflow-auto rounded-xl bg-ink p-3 font-mono text-[12px] leading-relaxed text-cream/90">
      <code>{text}</code>
    </pre>
  );
}

export const AMAZON_DISCLAIMER = "Demo catalog modeled on Amazon.in listings. Not affiliated with Amazon.";
