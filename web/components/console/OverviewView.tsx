"use client";

import { useState } from "react";
import { Avatar } from "@/components/Avatar";
import { Check, RefreshCw, RotateCcw, X } from "lucide-react";
import { api, errorMessage } from "@/lib/jhola/client";
import { usePolling } from "@/lib/jhola/hooks";
import type { Mandate, Member } from "@/lib/jhola/types";
import { Guarded } from "./AdminKey";
import OrderCard from "./OrderCard";
import { Button, Card, EmptyState, ErrorState, PageHeader, SectionTitle, Skeleton, SkeletonList, formatPeriod, rs, timeAgo } from "./ui";

const ROLE_LABEL: Record<string, string> = { admin: "Admin", adult: "Adult", house_help: "House help", teen: "Teen" };
const ROLE_TONE: Record<string, string> = {
  admin: "bg-ink text-cream",
  adult: "bg-jute text-white",
  house_help: "bg-leaf text-white",
  teen: "bg-turmeric text-ink",
};

function initials(name: string) {
  return name
    .replace(/\(.*?\)/g, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");
}

function MandateMeter({ m }: { m: Mandate }) {
  const pct = m.cap_inr > 0 ? Math.min(100, Math.round((m.used_inr / m.cap_inr) * 100)) : 0;
  const tone = pct >= 90 ? "bg-terracotta" : pct >= 70 ? "bg-turmeric" : "bg-leaf";
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-jute">UPI AutoPay mandate</p>
          <p className="mt-1 font-display text-3xl font-semibold tabular-nums">{rs(m.remaining_inr)}</p>
          <p className="text-sm text-ink-soft">left this month{formatPeriod(m) ? ` (${formatPeriod(m)})` : ""}</p>
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
          <dt className="text-ink-soft">Cap</dt>
          <dd className="text-right font-semibold tabular-nums">{rs(m.cap_inr)}</dd>
          <dt className="text-ink-soft">Used</dt>
          <dd className="text-right font-semibold tabular-nums">{rs(m.used_inr)}</dd>
        </dl>
      </div>
      <div
        className="mt-4 h-3 overflow-hidden rounded-full bg-sand"
        role="meter"
        aria-label="Mandate used"
        aria-valuemin={0}
        aria-valuemax={m.cap_inr}
        aria-valuenow={m.used_inr}
        aria-valuetext={`${rs(m.used_inr)} of ${rs(m.cap_inr)} used`}
      >
        <div className={`h-full rounded-full transition-[width] duration-700 ${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-2 text-xs text-ink-soft">
        {pct}% used. Cedar blocks any payment that would cross the cap, even after approval.
      </p>
    </Card>
  );
}

function MemberCard({ m }: { m: Member }) {
  return (
    <li className="flex gap-3 rounded-2xl border border-line bg-paper p-4">
      <Avatar id={m.id} initials={initials(m.name)} tone={ROLE_TONE[m.role] ?? "bg-sand text-ink"} size={40} />
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 font-semibold">
          {m.name}
          {m.display && !m.name.includes(m.display) ? <span className="font-normal text-ink-soft">({m.display})</span> : null}
          <span className="rounded-full bg-sand px-2 py-0.5 text-[11px] font-semibold text-ink-soft">{ROLE_LABEL[m.role] ?? m.role}</span>
        </p>
        <p className="text-xs text-ink-soft">{m.phone_masked}</p>
        <p className="mt-1 text-sm leading-snug">{m.limits_summary}</p>
      </div>
    </li>
  );
}

export default function OverviewView() {
  const household = usePolling(() => api.household(), 5000);
  const orders = usePolling(() => api.orders(20), 5000);
  const approvals = usePolling(() => api.approvals(), 5000);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refreshAll = () => Promise.all([household.refresh(), orders.refresh(), approvals.refresh()]);

  async function run(label: string, fn: () => Promise<unknown>, done: string) {
    setBusy(label);
    setActionError(null);
    setNotice(null);
    try {
      await fn();
      setNotice(done);
      await refreshAll();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  const h = household.data;
  const pending = approvals.data?.pending ?? [];

  return (
    <div>
      <PageHeader title={h ? h.household.name : "Family console"} hindi="परिवार">
        Everything the family ordered on WhatsApp, what the rules allowed, and what was paid. Refreshes every 5 seconds.
      </PageHeader>

      {actionError ? <div className="mb-4"><ErrorState message={actionError} /></div> : null}
      {notice ? (
        <p role="status" className="mb-4 rounded-2xl border border-leaf/30 bg-leaf-soft px-4 py-2.5 text-sm text-leaf">
          {notice}
        </p>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[1.25fr_1fr]">
        <div className="space-y-6">
          {household.error && !h ? (
            <ErrorState message={household.error} onRetry={household.refresh} />
          ) : h ? (
            <MandateMeter m={h.mandate} />
          ) : (
            <Skeleton className="h-40" />
          )}

          <section aria-labelledby="approvals-title">
            <SectionTitle id="approvals-title" title="Waiting for approval" hint="Orders above Rs 1,000 wait for Mom." />
            {approvals.loading ? (
              <SkeletonList rows={1} />
            ) : approvals.error && !approvals.data ? (
              <ErrorState message={approvals.error} onRetry={approvals.refresh} />
            ) : pending.length === 0 ? (
              <EmptyState title="Nothing waiting">New approval requests appear here and on Mom&apos;s WhatsApp.</EmptyState>
            ) : (
              <ul className="space-y-3">
                {pending.map((p) => (
                  <li key={p.order_id} className="flex flex-wrap items-center gap-3 rounded-2xl border border-turmeric/60 bg-turmeric-soft/60 p-4">
                    <div className="min-w-0 flex-1 basis-full sm:basis-auto">
                      <p className="font-semibold">
                        {p.member_name} <span className="font-normal text-ink-soft">wants {p.items_count} items</span>
                      </p>
                      <p className="text-xs text-ink-soft">
                        <span className="font-mono">{p.order_id}</span> · {timeAgo(p.created_at)}
                      </p>
                    </div>
                    <p className="font-display text-xl font-semibold tabular-nums">{rs(p.total_inr)}</p>
                    <div className="ml-auto flex gap-2">
                      <Guarded>
                        {(key, disabled) => (
                          <>
                            <Button
                              variant="leaf"
                              size="sm"
                              disabled={disabled || busy !== null}
                              onClick={() => run(`a-${p.order_id}`, () => api.decide(p.order_id, "approve", key), `${p.order_id} approved and paid.`)}
                            >
                              <Check className="h-3.5 w-3.5" aria-hidden /> {busy === `a-${p.order_id}` ? "Approving" : "Approve"}
                            </Button>
                            <Button
                              variant="danger"
                              size="sm"
                              disabled={disabled || busy !== null}
                              onClick={() => run(`r-${p.order_id}`, () => api.decide(p.order_id, "reject", key), `${p.order_id} rejected.`)}
                            >
                              <X className="h-3.5 w-3.5" aria-hidden /> {busy === `r-${p.order_id}` ? "Rejecting" : "Reject"}
                            </Button>
                          </>
                        )}
                      </Guarded>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="orders-title">
            <SectionTitle
              id="orders-title"
              title="Recent orders"
              hint="Open an order to see the Cedar decision for every line."
              action={
                <Button variant="ghost" size="sm" onClick={() => orders.refresh()} aria-label="Refresh orders">
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Refresh
                </Button>
              }
            />
            {orders.loading ? (
              <SkeletonList rows={4} />
            ) : orders.error && !orders.data ? (
              <ErrorState message={orders.error} onRetry={orders.refresh} />
            ) : (orders.data?.orders.length ?? 0) === 0 ? (
              <EmptyState title="No orders yet">Send a message on WhatsApp or use Try it.</EmptyState>
            ) : (
              <ul className="space-y-3">
                {orders.data!.orders.map((o, i) => (
                  <li key={o.order_id}>
                    <OrderCard order={o} defaultOpen={i === 0} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <div className="space-y-6">
          <section aria-labelledby="members-title">
            <SectionTitle id="members-title" title="Family" hint="Each person has their own limits." />
            {h ? (
              <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                {h.members.map((m) => (
                  <MemberCard key={m.id} m={m} />
                ))}
              </ul>
            ) : household.error ? null : (
              <SkeletonList rows={4} className="h-20" />
            )}
          </section>

          <Card className="p-5">
            <h2 className="font-display text-lg font-semibold">Demo controls</h2>
            <p className="mt-1 text-sm text-ink-soft">Run the weekly refill prediction, or put the household back to its starting state.</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Guarded>
                {(key, disabled) => (
                  <>
                    <Button variant="ghost" size="sm" disabled={disabled || busy !== null} onClick={() => run("refill", () => api.refill(key), "Refill run started.")}>
                      <RefreshCw className="h-3.5 w-3.5" aria-hidden /> {busy === "refill" ? "Running" : "Run refill"}
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={disabled || busy !== null}
                      onClick={() => {
                        if (window.confirm("Reset the demo household? This clears orders and custom rules.")) run("reset", () => api.reset(key), "Demo reset.");
                      }}
                    >
                      <RotateCcw className="h-3.5 w-3.5" aria-hidden /> {busy === "reset" ? "Resetting" : "Reset demo"}
                    </Button>
                  </>
                )}
              </Guarded>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
