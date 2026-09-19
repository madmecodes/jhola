"use client";

import Link from "next/link";
import { ChevronDown, ExternalLink, FileImage, Globe, Mic, MessageSquareText, Smartphone } from "lucide-react";
import type { Order } from "@/lib/jhola/types";
import { AMAZON_DISCLAIMER, DecisionChip, PolicyChip, StatusChip, rs, timeAgo } from "./ui";

const INPUT_ICON = { text: MessageSquareText, image: FileImage, voice: Mic } as const;
const INPUT_LABEL = { text: "Text", image: "Parchi photo", voice: "Voice note" } as const;

export default function OrderCard({ order, defaultOpen = false }: { order: Order; defaultOpen?: boolean }) {
  const InputIcon = INPUT_ICON[order.input_type] ?? MessageSquareText;
  const ChannelIcon = order.channel === "web" ? Globe : Smartphone;
  return (
    <details className="group rounded-2xl border border-line bg-paper open:shadow-sm" open={defaultOpen}>
      <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1.5 rounded-2xl px-4 py-3 hover:bg-cream/60">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-semibold">{order.member_name}</span>
            <StatusChip status={order.status} />
          </div>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-ink-soft">
            <span className="font-mono">{order.order_id}</span>
            <span aria-hidden>·</span>
            <span className="inline-flex items-center gap-1">
              <ChannelIcon className="h-3 w-3" aria-hidden />
              {order.channel === "web" ? "Web" : "WhatsApp"}
            </span>
            <span aria-hidden>·</span>
            <span className="inline-flex items-center gap-1">
              <InputIcon className="h-3 w-3" aria-hidden />
              {INPUT_LABEL[order.input_type] ?? order.input_type}
            </span>
            <span aria-hidden>·</span>
            <time dateTime={order.created_at}>{timeAgo(order.created_at)}</time>
          </p>
        </div>
        <div className="text-right">
          <p className="font-semibold tabular-nums">{rs(order.total_inr)}</p>
          {order.paid_inr > 0 && order.paid_inr !== order.total_inr ? (
            <p className="text-xs tabular-nums text-leaf">{rs(order.paid_inr)} paid</p>
          ) : null}
        </div>
        <ChevronDown className="h-4 w-4 shrink-0 text-ink-soft transition-transform group-open:rotate-180" aria-hidden />
      </summary>

      <div className="border-t border-line px-4 pb-4 pt-3">
        <ul className="divide-y divide-line/70">
          {order.items.map((it, i) => (
            <li key={`${it.sku}-${i}`} className="py-2.5">
              <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
                <DecisionChip decision={it.decision} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm">
                    <span className="font-semibold">{it.brand}</span> {it.name}{" "}
                    <span className="text-ink-soft">x{it.qty}</span>
                  </p>
                  <p className="mt-0.5 text-xs text-ink-soft">{it.reason}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    {it.policy_ids.map((p) => (
                      <PolicyChip key={p} id={p} />
                    ))}
                    {it.amazon_search_url ? (
                      <a
                        href={it.amazon_search_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs font-semibold text-ink underline-offset-2 hover:underline"
                      >
                        View on Amazon <ExternalLink className="h-3 w-3" aria-hidden />
                        <span className="sr-only">(opens in a new tab)</span>
                      </a>
                    ) : null}
                  </div>
                </div>
                <p className={`text-sm tabular-nums ${it.decision === "deny" ? "text-ink-soft line-through" : ""}`}>
                  {rs(it.price_inr * it.qty)}
                </p>
              </div>
            </li>
          ))}
        </ul>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-xs text-ink-soft">
          <span>
            {order.upi_ref ? (
              <>
                UPI ref <span className="font-mono text-ink">{order.upi_ref}</span> (simulated)
              </>
            ) : (
              "No payment made"
            )}
          </span>
          <Link href={`/console/audit?order=${encodeURIComponent(order.order_id)}`} className="font-semibold text-ink underline-offset-2 hover:underline">
            See audit trail
          </Link>
        </div>
        <p className="mt-2 text-[11px] text-ink-soft">{AMAZON_DISCLAIMER}</p>
      </div>
    </details>
  );
}
