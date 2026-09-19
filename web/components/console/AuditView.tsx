"use client";

import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  BadgeCheck,
  Ban,
  ChevronDown,
  CircleDollarSign,
  FileImage,
  Gavel,
  Hourglass,
  ListChecks,
  MessageSquareText,
  Mic,
  Search,
  Send,
  ShoppingBasket,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { api } from "@/lib/jhola/client";
import { usePolling } from "@/lib/jhola/hooks";
import type { AuditEvent } from "@/lib/jhola/types";
import { summarizeEvent } from "@/lib/jhola/summarize";
import { EmptyState, ErrorState, JsonBlock, PageHeader, SkeletonList, clockTime, timeAgo } from "./ui";

type Tone = "ink" | "leaf" | "turmeric" | "terracotta" | "jute";

function styleFor(type: string): { icon: LucideIcon; tone: Tone; label: string } {
  const t = type.toLowerCase();
  if (t.includes("message_received")) return { icon: MessageSquareText, tone: "ink", label: "Message received" };
  if (t.includes("voice") || t.includes("transcri")) return { icon: Mic, tone: "jute", label: "Transcribed" };
  if (t.includes("parchi") || t.includes("image") || t.includes("vision")) return { icon: FileImage, tone: "jute", label: "Parchi read" };
  if (t.includes("extract")) return { icon: Sparkles, tone: "jute", label: "Extracted" };
  if (t.includes("resolv")) return { icon: Search, tone: "jute", label: "Resolved" };
  if (t.includes("cart")) return { icon: ShoppingBasket, tone: "ink", label: "Cart" };
  if (t.includes("suspicious")) return { icon: Ban, tone: "terracotta", label: "Suspicious" };
  if (t.includes("denied") || t.includes("reject") || t.includes("blocked")) return { icon: Ban, tone: "terracotta", label: "Denied" };
  if (t.includes("policy") || t.includes("cedar") || t.includes("decision")) return { icon: Gavel, tone: "ink", label: "Cedar decision" };
  if (t.includes("approval_requested")) return { icon: Hourglass, tone: "turmeric", label: "Approval requested" };
  if (t.includes("approval")) return { icon: BadgeCheck, tone: "turmeric", label: "Approval" };
  if (t.includes("payment") || t.includes("mandate")) return { icon: CircleDollarSign, tone: "leaf", label: "Payment" };
  if (t.includes("reply") || t.includes("notification")) return { icon: Send, tone: "ink", label: "Reply" };
  if (t.includes("rule")) return { icon: ListChecks, tone: "turmeric", label: "Rule" };
  return { icon: ListChecks, tone: "ink", label: type.replace(/_/g, " ") };
}

const TONE: Record<Tone, string> = {
  ink: "bg-ink text-cream",
  leaf: "bg-leaf text-white",
  turmeric: "bg-turmeric text-ink",
  terracotta: "bg-terracotta text-white",
  jute: "bg-jute text-white",
};

function policyIds(data: unknown): string[] {
  const out = new Set<string>();
  const walk = (v: unknown, depth: number) => {
    if (depth > 4 || !v || typeof v !== "object") return;
    if (Array.isArray(v)) return v.forEach((x) => walk(x, depth + 1));
    for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
      if ((k === "policy_ids" || k === "determining_policies") && Array.isArray(val)) val.forEach((p) => typeof p === "string" && out.add(p));
      else walk(val, depth + 1);
    }
  };
  walk(data, 0);
  return [...out];
}

function EventRow({ e }: { e: AuditEvent }) {
  const s = styleFor(e.type);
  const Icon = s.icon;
  const ids = policyIds(e.data);
  const hasData = e.data !== undefined && e.data !== null && !(typeof e.data === "object" && Object.keys(e.data as object).length === 0);
  return (
    <li className="relative pl-12">
      <span className={`absolute left-0 top-3 flex h-8 w-8 items-center justify-center rounded-full ring-4 ring-cream ${TONE[s.tone]}`} aria-hidden>
        <Icon className="h-4 w-4" />
      </span>
      <details className="group rounded-2xl border border-line bg-paper">
        <summary className="flex cursor-pointer flex-wrap items-start gap-x-3 gap-y-1 rounded-2xl px-4 py-3 hover:bg-cream/60">
          <div className="min-w-0 flex-1">
            <p className="flex flex-wrap items-center gap-2 text-xs">
              <code className="rounded bg-sand px-1.5 py-0.5 font-mono text-[11px] text-ink">{e.type}</code>
              {e.order_id ? <span className="font-mono text-ink-soft">{e.order_id}</span> : null}
              {e.actor ? <span className="text-ink-soft">by {e.actor}</span> : null}
            </p>
            <p className="mt-1 break-words text-sm font-medium">{summarizeEvent(e)}</p>
            {ids.length ? (
              <p className="mt-1.5 flex flex-wrap gap-1.5">
                {ids.map((p) => (
                  <code key={p} className="rounded-md border border-ink/15 bg-cream px-1.5 py-0.5 font-mono text-[11px]">
                    {p}
                  </code>
                ))}
              </p>
            ) : null}
          </div>
          <time dateTime={e.ts} className="shrink-0 text-xs tabular-nums text-ink-soft" title={new Date(e.ts).toLocaleString("en-IN")}>
            {clockTime(e.ts)}
            <span className="block text-right">{timeAgo(e.ts)}</span>
          </time>
          {hasData ? <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-ink-soft transition-transform group-open:rotate-180" aria-hidden /> : null}
        </summary>
        {hasData ? (
          <div className="border-t border-line p-3">
            <JsonBlock value={e.data} />
          </div>
        ) : null}
      </details>
    </li>
  );
}

export default function AuditView() {
  const params = useSearchParams();
  const router = useRouter();
  const orderId = params.get("order") ?? "";
  const [orderInput, setOrderInput] = useState(orderId);
  const [type, setType] = useState("all");
  const [newestFirst, setNewestFirst] = useState<boolean | null>(null);
  const newest = newestFirst ?? !orderId;

  const audit = usePolling(() => api.audit(orderId || undefined, 100), 5000, [orderId]);

  const types = useMemo(() => [...new Set((audit.data?.events ?? []).map((e) => e.type))].sort(), [audit.data]);
  const events = useMemo(
    () =>
      (audit.data?.events ?? [])
        .filter((e) => type === "all" || e.type === type)
        .slice()
        .sort((a, b) => (newest ? b.ts.localeCompare(a.ts) : a.ts.localeCompare(b.ts))),
    [audit.data, type, newest],
  );

  return (
    <div>
      <PageHeader title="Audit trail" hindi="हिसाब">
        The trust trail. Every step from the message to the payment is recorded: received, transcribed or read, resolved to products,
        checked by Cedar with the exact policy ids, approved, paid.
      </PageHeader>

      <form
        className="mb-6 flex flex-wrap items-end gap-3 rounded-2xl border border-line bg-paper p-4"
        onSubmit={(e) => {
          e.preventDefault();
          const v = orderInput.trim();
          router.replace(v ? `/console/audit?order=${encodeURIComponent(v)}` : "/console/audit");
        }}
      >
        <div className="min-w-0 flex-1 basis-48">
          <label htmlFor="audit-order" className="text-xs font-semibold text-ink-soft">
            Order id
          </label>
          <input
            id="audit-order"
            value={orderInput}
            onChange={(e) => setOrderInput(e.target.value)}
            placeholder="Paste an order id"
            className="mt-1 w-full rounded-lg border border-line bg-cream px-3 py-2 font-mono text-sm outline-none focus:border-ink"
          />
        </div>
        <div className="min-w-0 basis-44">
          <label htmlFor="audit-type" className="text-xs font-semibold text-ink-soft">
            Event type
          </label>
          <select
            id="audit-type"
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="mt-1 w-full rounded-lg border border-line bg-cream px-3 py-2 text-sm outline-none focus:border-ink"
          >
            <option value="all">All events</option>
            {types.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="flex gap-2">
          <button type="submit" className="rounded-full bg-ink px-4 py-2 text-sm font-semibold text-cream hover:bg-ink/90">
            Filter
          </button>
          {orderId || type !== "all" ? (
            <button
              type="button"
              onClick={() => {
                setOrderInput("");
                setType("all");
                router.replace("/console/audit");
              }}
              className="rounded-full border border-ink/20 px-4 py-2 text-sm font-semibold hover:border-ink/50"
            >
              Clear
            </button>
          ) : null}
        </div>
      </form>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 text-sm text-ink-soft">
        <p>
          {orderId ? (
            <>
              Showing order <span className="font-mono font-semibold text-ink">{orderId}</span>.
            </>
          ) : (
            "All recent events."
          )}
        </p>
        <button
          type="button"
          onClick={() => setNewestFirst(!newest)}
          className="rounded-full border border-ink/20 bg-paper px-3 py-1 text-xs font-semibold text-ink hover:border-ink/50"
        >
          {newest ? "Newest first" : "Oldest first"} <span className="sr-only">(change order)</span>
        </button>
      </div>

      {audit.loading ? (
        <SkeletonList rows={6} className="h-20" />
      ) : audit.error && !audit.data ? (
        <ErrorState message={audit.error} onRetry={audit.refresh} />
      ) : events.length === 0 ? (
        <EmptyState title="No events match">Try another order id or clear the filters.</EmptyState>
      ) : (
        <ol className="relative space-y-3 before:absolute before:bottom-4 before:left-4 before:top-4 before:w-px before:bg-line" aria-label="Audit events">
          {events.map((e, i) => (
            <EventRow key={`${e.ts}-${e.type}-${i}`} e={e} />
          ))}
        </ol>
      )}
    </div>
  );
}
