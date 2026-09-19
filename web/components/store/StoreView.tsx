"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import {
  Apple,
  BadgeCheck,
  Camera,
  Carrot,
  ChevronUp,
  Cookie,
  CupSoda,
  Droplets,
  ExternalLink,
  Flame,
  LayoutGrid,
  Lock,
  MapPin,
  Mic,
  Milk,
  Minus,
  PencilRuler,
  Plus,
  Search,
  ShieldCheck,
  ShoppingCart,
  SprayCan,
  Star,
  Wheat,
  X,
  type LucideIcon,
} from "lucide-react";
import Logo from "@/components/Logo";
import { api, errorMessage, IS_LIVE } from "@/lib/jhola/client";
import { usePolling } from "@/lib/jhola/hooks";
import type { ChatMember, ChatResponse } from "@/lib/jhola/types";
import catalogData from "@/lib/store/catalog.json";
import householdData from "@/lib/store/household.json";
import type { VoiceCart, VoiceDecisions, VoiceOrder } from "@/lib/voice/types";
import { checkItem, checkPayment, type Role } from "./policy";

// Mic, WebSocket and AudioWorklet only exist in the browser.
const JholaVoiceAssistant = dynamic(() => import("@/components/voice/JholaVoiceAssistant"), {
  ssr: false,
  loading: () => <p className="rounded-2xl border border-line bg-paper px-3 py-4 text-center text-sm text-ink-soft">Loading voice...</p>,
});
const VOICE_WSS = process.env.NEXT_PUBLIC_JHOLA_VOICE_WSS ?? "";

const DESKTOP = "(min-width: 1024px)";
function useIsDesktop() {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(DESKTOP);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => window.matchMedia(DESKTOP).matches,
    () => true,
  );
}

type Product = (typeof catalogData)[number];
const CATALOG = catalogData as Product[];
const BY_ID = new Map(CATALOG.map((p) => [p.id, p]));

const NAVY = "#131921";
const NAVY_2 = "#232f3e";
const ORANGE = "#ff9900";

const CATS: { id: string; label: string; icon: LucideIcon; cats: string[] | null; tint: string }[] = [
  { id: "all", label: "All", icon: LayoutGrid, cats: null, tint: "#eef2f7" },
  { id: "staples", label: "Staples", icon: Wheat, cats: ["staples"], tint: "#fbf0dc" },
  { id: "dairy", label: "Dairy & Bread", icon: Milk, cats: ["dairy"], tint: "#e8f1fb" },
  { id: "vegetables", label: "Vegetables", icon: Carrot, cats: ["vegetables"], tint: "#e6f4e6" },
  { id: "fruits", label: "Fruits", icon: Apple, cats: ["fruits"], tint: "#fde9e4" },
  { id: "snacks", label: "Snacks", icon: Cookie, cats: ["snacks"], tint: "#fdf1d8" },
  { id: "beverages", label: "Beverages", icon: CupSoda, cats: ["beverages", "energy_drinks"], tint: "#e4f3f6" },
  { id: "stationery", label: "Stationery", icon: PencilRuler, cats: ["stationery"], tint: "#efe9fb" },
  { id: "personal_care", label: "Personal care", icon: Droplets, cats: ["personal_care"], tint: "#f8e8f1" },
  { id: "cleaning", label: "Cleaning", icon: SprayCan, cats: ["cleaning"], tint: "#e3f1f0" },
  { id: "pooja", label: "Pooja", icon: Flame, cats: ["pooja"], tint: "#fdeede" },
];
const catFor = (category: string) => CATS.find((c) => c.cats?.includes(category)) ?? CATS[0];

const MEMBERS: { id: ChatMember; label: string; role: Role; initials: string; tone: string }[] = [
  { id: "mom", label: "Mom", role: "admin", initials: "SG", tone: "bg-ink text-cream" },
  { id: "dad", label: "Dad", role: "adult", initials: "RG", tone: "bg-jute text-white" },
  { id: "didi", label: "Didi", role: "house_help", initials: "KD", tone: "bg-leaf text-white" },
  { id: "teen", label: "Teen", role: "teen", initials: "AG", tone: "bg-turmeric text-ink" },
];

const USUAL = householdData.usual_by_member as Record<string, string[]>;
const MANDATE = householdData.mandate;

const rs = (n: number) => `Rs ${n.toLocaleString("en-IN")}`;
const packLabel = (p: Product) => `${p.pack_size} ${p.unit}`;
const fulfilLabel = (f: string) => (f === "amazon_fresh" ? "Amazon Fresh" : "Amazon Now");

type Cart = Record<string, number>;

async function fileToBase64(file: File): Promise<string> {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    await new Promise<void>((res, rej) => {
      img.onload = () => res();
      img.onerror = () => rej(new Error("Could not read that image."));
      img.src = url;
    });
    const scale = Math.min(1, 1400 / Math.max(img.width, img.height));
    const c = document.createElement("canvas");
    c.width = Math.round(img.width * scale);
    c.height = Math.round(img.height * scale);
    c.getContext("2d")!.drawImage(img, 0, 0, c.width, c.height);
    return c.toDataURL("image/jpeg", 0.85).split(",")[1] ?? "";
  } finally {
    URL.revokeObjectURL(url);
  }
}

function Stepper({ qty, onChange, label, size = "md", disabled = false }: { qty: number; onChange: (q: number) => void; label: string; size?: "sm" | "md"; disabled?: boolean }) {
  const h = size === "sm" ? "h-7" : "h-8";
  if (qty <= 0)
    return (
      <button
        type="button"
        onClick={() => onChange(1)}
        disabled={disabled}
        title={disabled ? "The voice cart is active. Ask Jhola, or switch back to the tap cart." : undefined}
        className={`${h} w-full rounded-lg border px-3 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-50`}
        style={{ borderColor: ORANGE, color: "#b35c00", background: "#fff8ec" }}
        aria-label={`Add ${label}`}
      >
        Add
      </button>
    );
  return (
    <div className={`${h} flex w-full items-center justify-between rounded-lg text-sm font-bold`} style={{ background: ORANGE, color: NAVY }}>
      <button type="button" disabled={disabled} onClick={() => onChange(qty - 1)} className="flex h-full w-8 items-center justify-center disabled:opacity-40" aria-label={`Remove one ${label}`}>
        <Minus className="h-4 w-4" aria-hidden />
      </button>
      <span aria-live="polite" aria-label={`${qty} in cart`}>
        {qty}
      </span>
      <button type="button" disabled={disabled} onClick={() => onChange(qty + 1)} className="flex h-full w-8 items-center justify-center disabled:opacity-40" aria-label={`Add one more ${label}`}>
        <Plus className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}

function ProductCard({ p, qty, setQty, role, memberLabel, usual, locked }: { p: Product; qty: number; setQty: (q: number) => void; role: Role; memberLabel: string; usual: boolean; locked: boolean }) {
  const cat = catFor(p.category);
  const Icon = cat.icon;
  const off = p.mrp_inr > p.price_inr ? Math.round(((p.mrp_inr - p.price_inr) / p.mrp_inr) * 100) : 0;
  const check = checkItem(role, p, Math.max(qty, 1));
  const label = `${p.brand} ${p.name}`;
  return (
    <li className="flex flex-col rounded-xl border border-[#e3e6ea] bg-white p-2.5 shadow-[0_1px_2px_rgba(15,17,17,0.06)]">
      <div className="relative flex aspect-[4/3] items-center justify-center rounded-lg" style={{ background: cat.tint }}>
        <Icon className="h-9 w-9 text-[#37475a]/70" aria-hidden />
        <span className="absolute bottom-1.5 right-2 font-display text-lg font-semibold text-[#37475a]/35" aria-hidden>
          {p.brand.slice(0, 1)}
        </span>
        {off >= 5 ? (
          <span className="absolute left-1.5 top-1.5 rounded bg-[#cc0c39] px-1.5 py-0.5 text-[10px] font-bold text-white">{off}% off</span>
        ) : null}
        {usual ? (
          <span className="absolute right-1.5 top-1.5 inline-flex items-center gap-0.5 rounded-full bg-leaf px-1.5 py-0.5 text-[10px] font-bold text-white">
            <BadgeCheck className="h-3 w-3" aria-hidden /> Your usual
          </span>
        ) : null}
      </div>
      <span className="mt-2 w-fit rounded bg-[#e7f4f5] px-1.5 py-0.5 text-[10px] font-bold text-[#007185]">{fulfilLabel(p.fulfilment)}</span>
      <p className="mt-1 line-clamp-2 min-h-[2.5rem] text-[13px] font-medium leading-tight text-[#0f1111]">
        {p.brand} {p.name}
      </p>
      <p className="text-xs text-[#565959]">{packLabel(p)}</p>
      <p className="mt-0.5 flex items-center gap-1 text-[11px] text-[#565959]">
        <Star className="h-3 w-3 fill-[#ffa41c] text-[#ffa41c]" aria-hidden />
        <span>{p.seller_rating.toFixed(1)}</span>
        <span className="sr-only">seller rating</span>
      </p>
      <p className="mt-1 flex items-baseline gap-1.5">
        <span className="text-base font-bold text-[#0f1111]">{rs(p.price_inr)}</span>
        {p.mrp_inr > p.price_inr ? <span className="text-xs text-[#565959] line-through">{rs(p.mrp_inr)}</span> : null}
      </p>
      {check.decision === "deny" ? (
        <p className="mt-1 flex items-start gap-1 text-[11px] leading-tight text-terracotta" title={check.reason}>
          <Lock className="mt-px h-3 w-3 shrink-0" aria-hidden />
          <span>
            Not for {memberLabel}: <code className="font-mono">{check.policy_ids[0]}</code>
          </span>
        </p>
      ) : null}
      <div className="mt-auto pt-2">
        {p.in_stock ? <Stepper qty={qty} onChange={setQty} label={label} disabled={locked} /> : <p className="py-1.5 text-center text-xs font-semibold text-[#565959]">Out of stock</p>}
        <a
          href={p.amazon_search_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-[#007185] hover:underline"
        >
          View on Amazon <ExternalLink className="h-3 w-3" aria-hidden />
          <span className="sr-only">(opens in a new tab)</span>
        </a>
      </div>
    </li>
  );
}

type Line = { p: Product; qty: number; check: ReturnType<typeof checkItem> };

function JholaPanel({
  member,
  setMember,
  lines,
  remaining,
  onCheckout,
  checkingOut,
  result,
  onParchi,
  parchiBusy,
  error,
  thinking,
  voiceSlot,
  voiceOn,
  voiceOutcome,
  voiceOrder,
  onLeaveVoice,
}: {
  member: (typeof MEMBERS)[number];
  setMember: (m: ChatMember) => void;
  lines: Line[];
  remaining: number;
  onCheckout: () => void;
  checkingOut: boolean;
  result: ChatResponse | null;
  onParchi: (f: File) => void;
  parchiBusy: boolean;
  error: string | null;
  thinking: string | null;
  voiceSlot: ReactNode;
  voiceOn: boolean;
  voiceOutcome: VoiceDecisions | null;
  voiceOrder: VoiceOrder | null;
  onLeaveVoice: () => void;
}) {
  const allowedTotal = lines.filter((l) => l.check.decision === "allow").reduce((s, l) => s + l.p.price_inr * l.qty, 0);
  const pay = checkPayment(member.role, allowedTotal, {
    remaining_inr: remaining,
    approval_above_inr: MANDATE.per_payment_approval_above_inr,
    house_help_daily_cap_inr: MANDATE.house_help_daily_cap_inr,
  });
  const fileRef = useRef<HTMLInputElement>(null);
  if (voiceOn && voiceOutcome) {
    const o = voiceOutcome.checkout_outcome;
    pay.outcome = o === "auto_pay" ? "auto_pay" : o === "needs_approval" ? "needs_approval" : o === "empty" ? "empty" : "blocked";
    pay.policy_ids = voiceOutcome.why?.policy_ids ?? (o === "needs_approval" ? ["approval-above-threshold"] : []);
    pay.reason = voiceOutcome.why?.reasons?.join(" ") || (o === "auto_pay" ? "Within the mandate and auto-pay limits." : o === "all_lines_blocked" ? "Every line was blocked by the household rules." : pay.reason);
  }

  return (
    <div className="space-y-3 text-ink">
      <div className="flex items-center gap-2">
        <Logo className="h-8 w-8" />
        <div className="leading-tight">
          <p className="font-display text-lg font-semibold">Jhola household agent</p>
          <p className="text-[11px] text-ink-soft">Checks every line with Cedar before you pay</p>
        </div>
      </div>

      <fieldset>
        <legend className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-jute">Shopping as</legend>
        <div className="grid grid-cols-4 gap-1.5" role="radiogroup">
          {MEMBERS.map((m) => (
            <button
              key={m.id}
              type="button"
              role="radio"
              aria-checked={member.id === m.id}
              onClick={() => setMember(m.id)}
              className={`flex flex-col items-center gap-1 rounded-xl border px-1 py-1.5 text-xs font-semibold ${member.id === m.id ? "border-ink bg-paper" : "border-line bg-paper/50 hover:border-ink/40"}`}
            >
              <span className={`flex h-7 w-7 items-center justify-center rounded-full text-[10px] font-bold ${m.tone}`} aria-hidden>
                {m.initials}
              </span>
              {m.label}
            </button>
          ))}
        </div>
      </fieldset>

      <div className="rounded-xl border border-line bg-paper p-3">
        <div className="flex items-baseline justify-between">
          <span className="text-xs font-semibold text-ink-soft">UPI mandate left</span>
          <span className="font-display text-lg font-semibold tabular-nums">{rs(remaining)}</span>
        </div>
        <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-sand" aria-hidden>
          <div className="h-full rounded-full bg-leaf" style={{ width: `${Math.max(0, Math.min(100, (remaining / MANDATE.monthly_cap_inr) * 100))}%` }} />
        </div>
        <p className="mt-1 text-[11px] text-ink-soft">of {rs(MANDATE.monthly_cap_inr)} this month</p>
      </div>

      <div id="voice" className="scroll-mt-36">
        {voiceSlot}
        <p className="mt-1.5 text-[11px] leading-snug text-ink-soft">
          You can also say: &ldquo;Do packet doodh aur paneer add karo&rdquo;, &ldquo;Paneer mein kitna protein hai?&rdquo;, &ldquo;Order kar do&rdquo;.
        </p>
      </div>

      {voiceOn ? (
        <p className="flex flex-wrap items-center gap-2 rounded-xl border border-leaf/30 bg-leaf-soft px-3 py-2 text-xs text-leaf">
          <span className="min-w-0 flex-1 font-semibold">Voice cart is active. It lives on the Jhola server and is shown below.</span>
          <button type="button" onClick={onLeaveVoice} className="rounded-full border border-leaf/40 bg-paper px-2.5 py-1 font-semibold text-ink hover:border-ink/50">
            Back to tap cart
          </button>
        </p>
      ) : null}

      <div>
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-jute">
          Live Cedar check{voiceOn ? (voiceOutcome ? " (from Jhola, by voice)" : " (preview)") : ""}
        </p>
        {lines.length === 0 ? (
          <p className="rounded-xl border border-dashed border-line px-3 py-4 text-center text-sm text-ink-soft">Add items to see what {member.label} is allowed to buy.</p>
        ) : (
          <ul className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
            {lines.map((l) => (
              <li key={l.p.id} className="rounded-lg border border-line bg-paper px-2.5 py-2 text-xs">
                <div className="flex items-start gap-2">
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${l.check.decision === "allow" ? "bg-leaf-soft text-leaf" : "bg-terracotta-soft text-terracotta"}`}
                  >
                    {l.check.decision}
                  </span>
                  <span className="min-w-0 flex-1 font-medium">
                    {l.p.brand} {l.p.name} <span className="text-ink-soft">x{l.qty}</span>
                  </span>
                  <span className={`tabular-nums ${l.check.decision === "deny" ? "text-ink-soft line-through" : ""}`}>{rs(l.p.price_inr * l.qty)}</span>
                </div>
                <p className="mt-1 flex flex-wrap gap-1">
                  {l.check.policy_ids.map((id) => (
                    <code key={id} className="rounded border border-ink/15 bg-cream px-1 font-mono text-[10px]">
                      {id}
                    </code>
                  ))}
                </p>
                {l.check.decision === "deny" ? <p className="mt-0.5 text-[11px] text-ink-soft">{l.check.reason}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      {pay.outcome === "needs_approval" ? (
        <p className="rounded-xl border border-turmeric/60 bg-turmeric-soft px-3 py-2 text-sm">
          <strong>Needs Mom&apos;s approval.</strong> {pay.reason} <code className="font-mono text-[11px]">{pay.policy_ids[0]}</code>
        </p>
      ) : pay.outcome === "blocked" ? (
        <p className="rounded-xl border border-terracotta/40 bg-terracotta-soft px-3 py-2 text-sm">
          <strong>Payment blocked.</strong> {pay.reason}{" "}
          {pay.policy_ids.map((id) => (
            <code key={id} className="mr-1 font-mono text-[11px]">
              {id}
            </code>
          ))}
        </p>
      ) : pay.outcome === "auto_pay" ? (
        <p className="rounded-xl border border-leaf/30 bg-leaf-soft px-3 py-2 text-sm text-leaf">
          <strong>Auto-pay OK.</strong> {pay.reason}
        </p>
      ) : null}

      <div className="flex items-baseline justify-between border-t border-line pt-2 text-sm">
        <span className="text-ink-soft">Allowed total</span>
        <span className="font-display text-xl font-semibold tabular-nums">{rs(allowedTotal)}</span>
      </div>

      {voiceOn ? (
        <p className="rounded-full border border-ink/20 bg-paper px-4 py-2.5 text-center text-sm font-semibold">Say &ldquo;Order kar do&rdquo; to check out by voice</p>
      ) : null}
      <button
        type="button"
        onClick={onCheckout}
        hidden={voiceOn}
        disabled={checkingOut || lines.length === 0}
        className="flex w-full items-center justify-center gap-2 rounded-full px-4 py-2.5 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-50"
        style={{ background: "#ffd814", color: NAVY }}
      >
        <ShieldCheck className="h-4 w-4" aria-hidden />
        {checkingOut ? "Checking with Jhola" : pay.outcome === "needs_approval" ? "Send to Mom for approval" : "Checkout through Jhola"}
      </button>

      <input
        ref={fileRef}
        id="store-parchi"
        type="file"
        accept="image/*"
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) onParchi(f);
        }}
      />
      <label
        htmlFor="store-parchi"
        className={`flex w-full cursor-pointer items-center justify-center gap-2 rounded-full border border-ink/25 bg-paper px-4 py-2 text-sm font-semibold hover:border-ink/60 ${parchiBusy ? "pointer-events-none opacity-50" : ""}`}
      >
        <Camera className="h-4 w-4" aria-hidden /> {parchiBusy ? "Reading parchi" : "Send parchi photo"}
      </label>

      {error ? (
        <p role="alert" className="rounded-xl border border-terracotta/40 bg-terracotta-soft px-3 py-2 text-sm">
          {error}
        </p>
      ) : null}

      {voiceOrder ? (
        <div className="rounded-xl border border-line bg-paper p-3 text-sm" aria-live="polite">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-jute">Voice order</p>
          <p className="mt-1">
            {voiceOrder.order_id ? <span className="font-mono">{voiceOrder.order_id}</span> : "Order"} is{" "}
            <strong>{voiceOrder.status.replace(/_/g, " ")}</strong>
            {voiceOrder.payment ? `. ${rs(voiceOrder.payment.amount_inr)} paid, UPI ref ${voiceOrder.payment.upi_ref} (simulated)` : ""}.
          </p>
          {(voiceOrder.needs_approval_because?.reasons ?? voiceOrder.deny?.reasons ?? []).map((r) => (
            <p key={r} className="mt-1 text-xs text-ink-soft">{r}</p>
          ))}
          {(voiceOrder.blocked_lines ?? []).map((b) => (
            <p key={b.label} className="mt-1 text-xs text-terracotta">
              Blocked: {b.label} x{b.qty}. {b.reasons.join(" ")}
            </p>
          ))}
          {(voiceOrder.notifications ?? []).map((n, i) => (
            <p key={i} className="mt-2 rounded-lg bg-turmeric-soft px-2 py-1 text-xs">
              [Sent to {n.to}] {n.text}
            </p>
          ))}
          {voiceOrder.order_id ? (
            <Link href={`/console/audit?order=${encodeURIComponent(voiceOrder.order_id)}`} className="mt-2 inline-block text-xs font-semibold underline underline-offset-2">
              See the audit trail
            </Link>
          ) : null}
        </div>
      ) : null}
      {(checkingOut || parchiBusy) && thinking ? (
        <p role="status" className="rounded-xl border border-line bg-paper px-3 py-2 text-sm text-ink-soft">
          Jhola is thinking. {thinking}
        </p>
      ) : null}
      {result ? (
        <div className="rounded-xl border border-line bg-paper p-3 text-sm" aria-live="polite">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-jute">Jhola replied</p>
          <p className="mt-1 whitespace-pre-wrap">{result.reply_text}</p>
          {(result.notifications ?? []).map((n, i) => (
            <p key={i} className="mt-2 rounded-lg bg-turmeric-soft px-2 py-1 text-xs">
              [Sent to {String(n.to ?? n.member ?? "family")}] {String(n.text ?? n.reply_text ?? "")}
            </p>
          ))}
          {result.order ? (
            <p className="mt-2 text-xs text-ink-soft">
              Order <span className="font-mono text-ink">{result.order.order_id}</span> is{" "}
              <strong className="text-ink">{result.order.status.replace(/_/g, " ")}</strong>.{" "}
              <Link href={`/console/audit?order=${encodeURIComponent(result.order.order_id)}`} className="font-semibold text-ink underline underline-offset-2">
                See the audit trail
              </Link>
            </p>
          ) : null}
        </div>
      ) : null}
      <p className="text-[11px] leading-snug text-ink-soft">
        The preview mirrors the household policies. At checkout the Jhola agent decides, with the same Cedar rules it uses on WhatsApp.
      </p>
    </div>
  );
}

function Drawer({ open, onClose, title, children, side = "right", keepMounted = false }: { open: boolean; onClose: () => void; title: string; children: ReactNode; side?: "right" | "bottom"; keepMounted?: boolean }) {
  if (!open && !keepMounted) return null;
  return (
    <div className={`fixed inset-0 z-50 ${open ? "" : "hidden"}`} role="dialog" aria-modal="true" aria-label={title}>
      <button type="button" className="absolute inset-0 bg-black/40" aria-label="Close" onClick={onClose} />
      <div
        className={
          side === "right"
            ? "absolute inset-y-0 right-0 flex w-full max-w-md flex-col bg-cream shadow-2xl"
            : "absolute inset-x-0 bottom-0 flex max-h-[88vh] flex-col rounded-t-3xl bg-cream shadow-2xl"
        }
        onKeyDown={(e) => e.key === "Escape" && onClose()}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <p className="font-display text-lg font-semibold">{title}</p>
          <button type="button" onClick={onClose} className="rounded-full p-1.5 hover:bg-sand" aria-label="Close" autoFocus={!keepMounted}>
            <X className="h-5 w-5" aria-hidden />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}

const PAGE = 48;

export default function StoreView() {
  const [memberId, setMemberId] = useState<ChatMember>("didi");
  const [cat, setCat] = useState("all");
  const [query, setQuery] = useState("");
  const [cart, setCart] = useState<Cart>({});
  const [limit, setLimit] = useState(PAGE);
  const [cartOpen, setCartOpen] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [checkingOut, setCheckingOut] = useState(false);
  const [parchiBusy, setParchiBusy] = useState(false);
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [thinking, setThinking] = useState<string | null>(null);
  const [sessionId] = useState(() => `web-store-${Math.random().toString(36).slice(2, 8)}`);

  const [voiceCart, setVoiceCart] = useState<VoiceCart | null>(null);
  const [voiceDecisions, setVoiceDecisions] = useState<VoiceDecisions | null>(null);
  const [voiceOrder, setVoiceOrder] = useState<VoiceOrder | null>(null);
  const isDesktop = useIsDesktop();
  // The server-side voice cart takes over as soon as it holds something.
  const voiceOn = (voiceCart?.lines.length ?? 0) > 0;

  // /store#voice (from the landing page) opens the Jhola sheet on mobile.
  useEffect(() => {
    if (window.location.hash !== "#voice") return;
    const t = setTimeout(() => {
      if (window.matchMedia(DESKTOP).matches) document.getElementById("voice")?.scrollIntoView({ block: "center" });
      else setPanelOpen(true);
    }, 300);
    return () => clearTimeout(t);
  }, []);

  const member = MEMBERS.find((m) => m.id === memberId)!;
  const household = usePolling(() => api.household(), 10000);
  const remaining = household.data?.mandate.remaining_inr ?? MANDATE.monthly_cap_inr;

  const usualSet = useMemo(() => new Set(USUAL[memberId] ?? []), [memberId]);

  const products = useMemo(() => {
    const q = query.trim().toLowerCase();
    const c = CATS.find((x) => x.id === cat);
    let list = CATALOG.filter((p) => (!c?.cats || c.cats.includes(p.category)) && (!q || q.split(/\s+/).every((w) => p.q.includes(w))));
    if (!q && cat === "all") list = [...list].sort((a, b) => Number(usualSet.has(b.id)) - Number(usualSet.has(a.id)));
    return list;
  }, [cat, query, usualSet]);

  const lines: Line[] = useMemo(
    () =>
      voiceCart && voiceCart.lines.length > 0
        ? voiceCart.lines.map((vl) => {
            const p: Product =
              BY_ID.get(vl.sku) ??
              ({ ...CATALOG[0], id: vl.sku, name: vl.name || vl.label, brand: vl.brand, category: vl.category, price_inr: vl.unit_price_inr, mrp_inr: vl.unit_price_inr } as Product);
            const d = voiceDecisions?.lines.find((x) => x.sku === vl.sku);
            const check = d
              ? { decision: d.allowed ? ("allow" as const) : ("deny" as const), policy_ids: d.policy_ids, reason: d.reasons.join(" ") }
              : checkItem(member.role, p, vl.qty);
            return { p, qty: vl.qty, check };
          })
        : Object.entries(cart)
        .filter(([, q]) => q > 0)
        .map(([id, qty]) => {
          const p = BY_ID.get(id)!;
          return { p, qty, check: checkItem(member.role, p, qty) };
        }),
    [cart, member.role, voiceCart, voiceDecisions],
  );
  const count = lines.reduce((s, l) => s + l.qty, 0);
  const subtotal = lines.reduce((s, l) => s + l.p.price_inr * l.qty, 0);

  const setQty = (id: string, q: number) => setCart((c) => ({ ...c, [id]: Math.max(0, Math.min(q, 20)) }));

  async function checkout() {
    setCheckingOut(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.checkoutCart(
        memberId,
        lines.map((l) => ({
          sku: l.p.id,
          name: l.p.name,
          brand: l.p.brand,
          size: packLabel(l.p),
          category: l.p.category,
          price_inr: l.p.price_inr,
          fulfilment: l.p.fulfilment,
          amazon_search_url: l.p.amazon_search_url,
          qty: l.qty,
        })),
        (t) => setThinking(t),
        `${sessionId}-${memberId}`,
      );
      setResult(res);
      if (res.order && res.order.status !== "denied" && res.order.status !== "draft") setCart({});
      household.refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setCheckingOut(false);
      setThinking(null);
    }
  }

  async function sendParchi(f: File) {
    setParchiBusy(true);
    setError(null);
    setResult(null);
    try {
      const b64 = await fileToBase64(f);
      setResult(await api.chat({ member: memberId, session_id: `${sessionId}-${memberId}`, image_base64: b64, media_type: "image/jpeg" }, (t) => setThinking(t)));
      household.refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setParchiBusy(false);
      setThinking(null);
    }
  }

  const leaveVoice = () => {
    setVoiceCart(null);
    setVoiceDecisions(null);
  };
  const voiceSlot = VOICE_WSS ? (
    <JholaVoiceAssistant
      key={memberId}
      apiUrl={VOICE_WSS}
      member={memberId}
      className="!border-line !bg-paper"
      onCartUpdate={(c) => {
        setVoiceCart(c);
        setVoiceDecisions(null);
      }}
      onDecisions={(d) => setVoiceDecisions(d)}
      onOrder={(o) => {
        setVoiceOrder(o);
        household.refresh();
      }}
    />
  ) : (
    <p className="rounded-2xl border border-dashed border-line px-3 py-3 text-center text-sm text-ink-soft">Talk to Jhola: live voice is not configured on this deployment.</p>
  );
  const panel = (
    <JholaPanel
      voiceSlot={voiceSlot}
      voiceOn={voiceOn}
      voiceOutcome={voiceDecisions}
      voiceOrder={voiceOrder}
      onLeaveVoice={leaveVoice}
      member={member}
      setMember={(m) => {
        leaveVoice();
        setVoiceOrder(null);
        setMemberId(m);
      }}
      lines={lines}
      remaining={remaining}
      onCheckout={checkout}
      checkingOut={checkingOut}
      result={result}
      onParchi={sendParchi}
      parchiBusy={parchiBusy}
      error={error}
      thinking={thinking}
    />
  );
  const denied = lines.filter((l) => l.check.decision === "deny").length;

  return (
    <div className="min-h-screen bg-[#eaeded] pb-24 text-[#0f1111] lg:pb-0">
      <p className="bg-turmeric-soft px-4 py-2 text-center text-xs font-medium text-ink sm:text-sm">
        Concept prototype: how Jhola could plug into a quick-commerce app like Amazon Now. Not affiliated with Amazon. Demo catalog, simulated
        payments.
      </p>

      <header style={{ background: NAVY }} className="sticky top-0 z-30 text-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
          <Link href="/" className="flex items-baseline gap-1 rounded px-1 outline-offset-2" aria-label="Now store concept, back to Jhola">
            <span className="text-2xl font-extrabold tracking-tight">now</span>
            <span className="text-xs font-semibold" style={{ color: ORANGE }}>
              store (concept)
            </span>
          </Link>
          <div className="order-3 flex min-w-0 flex-1 basis-full sm:order-none sm:basis-auto">
            <label htmlFor="store-search" className="sr-only">
              Search products
            </label>
            <input
              id="store-search"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setLimit(PAGE);
              }}
              placeholder="Search atta, doodh, Maggi, notebook..."
              className="h-10 min-w-0 flex-1 rounded-l-lg border-0 bg-white px-3 text-sm text-[#0f1111] outline-none"
            />
            <span className="flex h-10 w-11 items-center justify-center rounded-r-lg" style={{ background: "#febd69" }} aria-hidden>
              <Search className="h-5 w-5 text-[#0f1111]" />
            </span>
          </div>
          <button
            type="button"
            onClick={() => setCartOpen(true)}
            className="ml-auto flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-bold hover:outline hover:outline-1 hover:outline-white sm:ml-0"
            aria-label={`Cart, ${count} items`}
          >
            <span className="relative">
              <ShoppingCart className="h-7 w-7" aria-hidden />
              <span className="absolute -right-1.5 -top-1.5 min-w-5 rounded-full px-1 text-center text-xs font-bold" style={{ background: ORANGE, color: NAVY }}>
                {count}
              </span>
            </span>
            <span className="hidden sm:inline">Cart</span>
          </button>
        </div>
        <div style={{ background: NAVY_2 }}>
          <p className="mx-auto flex max-w-7xl items-center gap-1.5 px-4 py-1.5 text-xs sm:text-sm">
            <MapPin className="h-4 w-4 shrink-0" aria-hidden />
            <span>
              Delivery in <strong style={{ color: ORANGE }}>10 minutes</strong> to Home - Koramangala
            </span>
            <span className="ml-auto hidden text-white/70 md:inline">Shopping as {member.label} with Jhola household rules on</span>
          </p>
        </div>
      </header>

      <nav aria-label="Categories" className="border-b border-[#d5d9d9] bg-white">
        <ul className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-3 py-2 [scrollbar-width:none]">
          {CATS.map((c) => {
            const Icon = c.icon;
            const active = cat === c.id;
            return (
              <li key={c.id} className="shrink-0">
                <button
                  type="button"
                  onClick={() => {
                    setCat(c.id);
                    setLimit(PAGE);
                  }}
                  aria-pressed={active}
                  className={`flex w-20 flex-col items-center gap-1 rounded-lg px-1 py-1.5 text-[11px] font-semibold leading-tight ${active ? "text-[#0f1111]" : "text-[#565959] hover:text-[#0f1111]"}`}
                >
                  <span className={`flex h-11 w-11 items-center justify-center rounded-full ${active ? "ring-2" : ""}`} style={{ background: c.tint, ...(active ? { boxShadow: `0 0 0 2px ${ORANGE}` } : {}) }}>
                    <Icon className="h-5 w-5 text-[#37475a]" aria-hidden />
                  </span>
                  <span className="text-center">{c.label}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="mx-auto flex max-w-7xl gap-5 px-4 py-4">
        <main className="min-w-0 flex-1" id="store-main">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h1 className="text-lg font-bold">
              {query ? `Results for "${query}"` : CATS.find((c) => c.id === cat)?.label === "All" ? "Everyday essentials" : CATS.find((c) => c.id === cat)?.label}
            </h1>
            <p className="text-xs text-[#565959]">{products.length} products</p>
          </div>
          {products.length === 0 ? (
            <p className="rounded-xl bg-white p-8 text-center text-sm text-[#565959]">No products match. Try another word, like atta or doodh.</p>
          ) : (
            <ul className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-4">
              {products.slice(0, limit).map((p) => (
                <ProductCard
                  key={p.id}
                  p={p}
                  qty={voiceOn ? (voiceCart?.lines.find((l) => l.sku === p.id)?.qty ?? 0) : (cart[p.id] ?? 0)}
                  setQty={(q) => setQty(p.id, q)}
                  role={member.role}
                  memberLabel={member.label}
                  usual={usualSet.has(p.id)}
                  locked={voiceOn}
                />
              ))}
            </ul>
          )}
          {products.length > limit ? (
            <div className="mt-4 text-center">
              <button type="button" onClick={() => setLimit((l) => l + PAGE)} className="rounded-full border border-[#d5d9d9] bg-white px-5 py-2 text-sm font-semibold hover:bg-[#f7fafa]">
                Show more ({products.length - limit} left)
              </button>
            </div>
          ) : null}
          <p className="mt-6 text-center text-[11px] text-[#565959]">
            Demo catalog modeled on Amazon.in listings. Not affiliated with Amazon. {IS_LIVE ? "" : "Running on sample data."}{" "}
            <Link href="/console" className="underline">
              Open the family console
            </Link>
          </p>
        </main>

        <aside className="hidden w-80 shrink-0 lg:block" aria-label="Jhola household agent">
          <div className="sticky top-32 max-h-[calc(100vh-9rem)] overflow-y-auto rounded-2xl border border-line bg-cream p-4 shadow-sm">{isDesktop ? panel : null}</div>
        </aside>
      </div>

      {/* Mobile: Jhola bar opens the panel as a bottom sheet */}
      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-cream px-4 py-2.5 lg:hidden">
        <button type="button" onClick={() => setPanelOpen(true)} className="flex w-full items-center gap-3 text-left" aria-expanded={panelOpen}>
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-leaf text-white" aria-hidden>
            <Mic className="h-4 w-4" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold text-ink">Talk to Jhola as {member.label}</span>
            <span className="block text-xs text-ink-soft">
              {lines.length ? `${voiceOn ? "Voice cart: " : ""}${lines.length - denied} allowed, ${denied} blocked · ${rs(subtotal)}` : "Tap the mic, or add items to check them"}
            </span>
          </span>
          <ChevronUp className="h-5 w-5 text-ink" aria-hidden />
        </button>
      </div>

      {isDesktop ? null : (
        <Drawer open={panelOpen} onClose={() => setPanelOpen(false)} title="Jhola household agent" side="bottom" keepMounted>
          {panel}
        </Drawer>
      )}

      <Drawer open={cartOpen} onClose={() => setCartOpen(false)} title={`Cart (${count})`}>
        {lines.length === 0 ? (
          <p className="py-10 text-center text-sm text-ink-soft">Your cart is empty.</p>
        ) : (
          <div className="space-y-3">
            <ul className="space-y-2">
              {lines.map((l) => (
                <li key={l.p.id} className="flex items-center gap-3 rounded-xl border border-line bg-paper p-2.5">
                  <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg" style={{ background: catFor(l.p.category).tint }} aria-hidden>
                    {(() => {
                      const I = catFor(l.p.category).icon;
                      return <I className="h-5 w-5 text-[#37475a]" />;
                    })()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {l.p.brand} {l.p.name}
                    </p>
                    <p className="text-xs text-ink-soft">
                      {packLabel(l.p)} · {rs(l.p.price_inr)}
                    </p>
                    <p className={`text-[11px] font-semibold ${l.check.decision === "allow" ? "text-leaf" : "text-terracotta"}`}>
                      {l.check.decision === "allow" ? "Allowed" : `Blocked: ${l.check.policy_ids[0]}`}
                    </p>
                  </div>
                  <div className="w-24">
                    <Stepper qty={l.qty} onChange={(q) => setQty(l.p.id, q)} label={`${l.p.brand} ${l.p.name}`} size="sm" disabled={voiceOn} />
                  </div>
                </li>
              ))}
            </ul>
            <div className="flex items-baseline justify-between border-t border-line pt-2">
              <span className="text-sm text-ink-soft">Subtotal</span>
              <span className="font-display text-xl font-semibold">{rs(subtotal)}</span>
            </div>
            <button
              type="button"
              onClick={() => {
                setCartOpen(false);
                if (typeof window !== "undefined" && window.matchMedia("(max-width: 1023px)").matches) setPanelOpen(true);
                checkout();
              }}
              disabled={checkingOut}
              hidden={voiceOn}
              className="flex w-full items-center justify-center gap-2 rounded-full px-4 py-2.5 text-sm font-bold disabled:opacity-50"
              style={{ background: "#ffd814", color: NAVY }}
            >
              <ShieldCheck className="h-4 w-4" aria-hidden /> Checkout through Jhola
            </button>
            {voiceOn ? <p className="text-sm font-semibold">This is your voice cart. Say &ldquo;Order kar do&rdquo; to check out.</p> : null}
            <p className="text-[11px] text-ink-soft">Checkout runs the same Cedar policy gate as WhatsApp orders. Payments are simulated.</p>
          </div>
        )}
      </Drawer>
    </div>
  );
}
