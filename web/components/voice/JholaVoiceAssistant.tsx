"use client";

/**
 * Jhola voice assistant: hold a real-time Hinglish conversation with the kirana agent.
 * Mic audio goes to the voice server over a WebSocket, Amazon Nova 2 Sonic answers in speech,
 * and cart / policy / order updates arrive as events while the model works.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Mic, ShieldAlert, Square } from "lucide-react";
import { VoiceClient } from "@/lib/voice/client";
import type {
  VoiceCart,
  VoiceDecisions,
  VoiceMember,
  VoiceOrder,
  VoiceServerEvent,
  VoiceStatus,
} from "@/lib/voice/types";

export type JholaVoiceAssistantProps = {
  /** wss:// URL of the voice server (CloudFront). */
  apiUrl: string;
  /** Acting family member; the server applies that member's Cedar rules. */
  member: VoiceMember;
  /** Called whenever the voice cart changes (also right after connecting, with the empty cart). */
  onCartUpdate?: (cart: VoiceCart) => void;
  /** Called when checkout returns: paid, pending_approval or denied. */
  onOrder?: (order: VoiceOrder) => void;
  /** Called with the Cedar per-line decisions when the assistant checks the cart. */
  onDecisions?: (decisions: VoiceDecisions) => void;
  /** Nova Sonic voice id. kiara (feminine) and arjun (masculine) are the Indian voices. */
  voice?: "kiara" | "arjun";
  /** Extra classes for the outer card. */
  className?: string;
  /** Hide the built-in transcript panel when the host page renders its own. */
  showTranscript?: boolean;
};

type Bubble = { id: number; role: "user" | "assistant"; text: string };

const STATUS_TEXT: Record<VoiceStatus, string> = {
  idle: "Tap to talk",
  connecting: "Connecting",
  listening: "Listening",
  speaking: "Jhola is speaking",
  ended: "Session ended",
  error: "Something went wrong",
};

const TOOL_TEXT: Record<string, string> = {
  search_products: "Searching the catalog",
  get_product_details: "Checking product details",
  compare_products: "Comparing products",
  add_to_cart: "Adding to cart",
  remove_from_cart: "Removing from cart",
  view_cart: "Reading the cart",
  check_cart: "Checking the family rules",
  checkout: "Placing the order",
};

export default function JholaVoiceAssistant({
  apiUrl,
  member,
  onCartUpdate,
  onOrder,
  onDecisions,
  voice = "kiara",
  className = "",
  showTranscript = true,
}: JholaVoiceAssistantProps) {
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [error, setError] = useState("");
  const [level, setLevel] = useState(0);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [activity, setActivity] = useState("");
  const [cart, setCart] = useState<VoiceCart | null>(null);
  const [decisions, setDecisions] = useState<VoiceDecisions | null>(null);
  const [order, setOrder] = useState<VoiceOrder | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);

  const clientRef = useRef<VoiceClient | null>(null);
  const speakingRef = useRef(false);
  const idRef = useRef(0);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const cbRef = useRef({ onCartUpdate, onOrder, onDecisions });
  useEffect(() => {
    cbRef.current = { onCartUpdate, onOrder, onDecisions };
  }, [onCartUpdate, onOrder, onDecisions]);

  const active = status === "listening" || status === "speaking" || status === "connecting";

  const push = useCallback((role: "user" | "assistant", text: string) => {
    const clean = text.trim();
    if (!clean) return;
    setBubbles((prev) => {
      const last = prev[prev.length - 1];
      // Nova Sonic streams the assistant turn in fragments; keep one bubble per turn.
      if (last && last.role === role && role === "assistant") {
        const merged = [...prev];
        merged[merged.length - 1] = { ...last, text: `${last.text} ${clean}`.trim() };
        return merged;
      }
      idRef.current += 1;
      return [...prev, { id: idRef.current, role, text: clean }].slice(-30);
    });
  }, []);

  const onEvent = useCallback(
    (ev: VoiceServerEvent) => {
      switch (ev.type) {
        case "ready":
          setStatus("listening");
          setSecondsLeft(ev.max_seconds);
          break;
        case "transcript":
          push(ev.role, ev.text);
          break;
        case "interrupted":
          setStatus("listening");
          break;
        case "tool":
          setActivity(ev.phase === "start" ? TOOL_TEXT[ev.name] ?? ev.name : "");
          break;
        case "cart":
          setCart(ev.cart);
          cbRef.current.onCartUpdate?.(ev.cart);
          break;
        case "decisions":
          setDecisions(ev);
          cbRef.current.onDecisions?.(ev);
          break;
        case "order":
          setOrder(ev);
          cbRef.current.onOrder?.(ev);
          break;
        case "error":
          setError(ev.message);
          break;
        case "ended":
        case "model_closed":
          setStatus("ended");
          setActivity("");
          break;
        default:
          break;
      }
    },
    [push],
  );

  const stop = useCallback(() => {
    clientRef.current?.stop();
    clientRef.current = null;
    setStatus((s) => (s === "error" ? s : "ended"));
    setActivity("");
    setLevel(0);
  }, []);

  const start = useCallback(async () => {
    setError("");
    setBubbles([]);
    setOrder(null);
    setDecisions(null);
    setStatus("connecting");
    const client = new VoiceClient(
      apiUrl,
      member,
      {
        onEvent,
        onLevel: (l) => setLevel(l),
        onSpeaking: (speaking) => {
          speakingRef.current = speaking;
          setStatus((s) => (s === "ended" || s === "error" ? s : speaking ? "speaking" : "listening"));
        },
        onClose: (reason) => {
          setStatus("ended");
          setActivity("");
          if (reason && reason !== "client stopped") setError(reason);
        },
      },
      voice,
    );
    clientRef.current = client;
    try {
      await client.start();
    } catch (e) {
      clientRef.current = null;
      setStatus("error");
      const msg = e instanceof Error ? e.message : String(e);
      setError(
        msg.includes("Permission") || msg.includes("NotAllowed")
          ? "Microphone access was blocked. Allow the mic in the browser and try again."
          : msg,
      );
    }
  }, [apiUrl, member, onEvent, voice]);

  useEffect(() => () => clientRef.current?.stop(), []);

  useEffect(() => {
    if (!active || status === "connecting") return;
    const t = setInterval(() => setSecondsLeft((s) => (s > 0 ? s - 1 : 0)), 1000);
    return () => clearInterval(t);
  }, [active, status]);

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
  }, [bubbles, activity]);

  const bars = useMemo(() => Array.from({ length: 9 }, (_, i) => i), []);
  const outcome = decisions?.checkout_outcome;

  return (
    <section className={`rounded-2xl border border-slate-200 bg-white p-4 shadow-sm ${className}`}>
      <header className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">Talk to Jhola</h2>
          <p className="text-xs text-slate-500">
            Hindi or Hinglish, real time. Acting as {member}. Payments stay behind the family rules.
          </p>
        </div>
        {active && status !== "connecting" ? (
          <span className="shrink-0 rounded-full bg-slate-100 px-2 py-1 text-[11px] font-medium text-slate-600">
            {Math.floor(secondsLeft / 60)}:{String(secondsLeft % 60).padStart(2, "0")} left
          </span>
        ) : null}
      </header>

      <div className="mt-4 flex items-center gap-4">
        <button
          type="button"
          onClick={active ? stop : start}
          disabled={status === "connecting"}
          className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full text-white transition ${
            active ? "bg-rose-600 hover:bg-rose-700" : "bg-emerald-600 hover:bg-emerald-700"
          } disabled:opacity-60`}
          aria-label={active ? "Stop the voice session" : "Start the voice session"}
        >
          {status === "connecting" ? (
            <Loader2 className="h-6 w-6 animate-spin" />
          ) : active ? (
            <Square className="h-5 w-5" />
          ) : (
            <Mic className="h-6 w-6" />
          )}
        </button>

        <div className="min-w-0 flex-1">
          <div className="flex h-8 items-end gap-1" aria-hidden>
            {bars.map((i) => {
              const base = status === "speaking" ? 0.35 : level;
              const h = Math.max(3, Math.min(30, base * 34 * (1 - Math.abs(i - 4) / 7) * (active ? 1 : 0) + 3));
              return (
                <span
                  key={i}
                  className={`w-1.5 rounded-full transition-all duration-100 ${
                    status === "speaking" ? "bg-sky-500" : "bg-emerald-500"
                  }`}
                  style={{ height: `${h}px` }}
                />
              );
            })}
          </div>
          <p className="mt-1 truncate text-xs text-slate-600">
            {activity || STATUS_TEXT[status]}
            {status === "listening" && !activity ? " - bolna shuru kijiye" : ""}
          </p>
        </div>
      </div>

      {error ? (
        <p className="mt-3 flex items-start gap-2 rounded-lg bg-rose-50 p-2 text-xs text-rose-700">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
        </p>
      ) : null}

      {showTranscript ? (
        <div ref={transcriptRef} className="mt-4 max-h-56 space-y-2 overflow-y-auto pr-1">
          {bubbles.length === 0 ? (
            <p className="text-xs text-slate-400">
              Try: &quot;Mujhe do packet doodh aur ek paneer chahiye, paneer mein kitna protein hai?&quot;
            </p>
          ) : null}
          {bubbles.map((b) => (
            <div key={b.id} className={b.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <p
                className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm ${
                  b.role === "user" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-800"
                }`}
              >
                {b.text}
              </p>
            </div>
          ))}
        </div>
      ) : null}

      {cart && cart.lines.length > 0 ? (
        <div className="mt-4 rounded-xl border border-slate-200 p-3">
          <p className="text-xs font-semibold text-slate-700">
            Voice cart - {cart.items} item{cart.items === 1 ? "" : "s"}, Rs {cart.total_inr}
          </p>
          <ul className="mt-2 space-y-1 text-xs text-slate-600">
            {cart.lines.map((l) => (
              <li key={l.sku} className="flex justify-between gap-2">
                <span className="truncate">
                  {l.brand} {l.name} x{l.qty}
                </span>
                <span className="shrink-0">Rs {l.line_total_inr}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {decisions && outcome && outcome !== "empty" ? (
        <div className="mt-3 rounded-xl bg-slate-50 p-3 text-xs text-slate-700">
          <p className="flex items-center gap-1.5 font-semibold">
            {outcome === "auto_pay" ? (
              <>
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> Auto-pay allowed for Rs {decisions.payable_inr}
              </>
            ) : outcome === "needs_approval" ? (
              <>
                <ShieldAlert className="h-3.5 w-3.5 text-amber-600" /> Needs Mom&apos;s approval
              </>
            ) : (
              <>
                <ShieldAlert className="h-3.5 w-3.5 text-rose-600" /> Blocked by the family rules
              </>
            )}
          </p>
          {decisions.lines
            .filter((l) => !l.allowed)
            .map((l) => (
              <p key={l.sku} className="mt-1">
                {l.label}: {l.reasons.join(" ")} <span className="text-slate-400">({l.policy_ids.join(", ")})</span>
              </p>
            ))}
          {decisions.why?.reasons?.length ? <p className="mt-1">{decisions.why.reasons.join(" ")}</p> : null}
          <p className="mt-1 text-slate-500">Mandate remaining: Rs {decisions.mandate_remaining_inr}</p>
        </div>
      ) : null}

      {order ? (
        <div className="mt-3 rounded-xl border border-slate-200 p-3 text-xs">
          <p className="font-semibold text-slate-800">
            {order.status === "paid"
              ? `Paid Rs ${order.payment?.amount_inr} (UPI ref ${order.payment?.upi_ref}, simulated)`
              : order.status === "pending_approval"
                ? "Sent to Mom for approval"
                : order.status === "denied"
                  ? "Order denied by the family rules"
                  : `Order ${order.status}`}
          </p>
          {order.order_id ? <p className="mt-0.5 text-slate-500">Order {order.order_id}</p> : null}
          {order.deny?.reasons?.length ? <p className="mt-1 text-slate-600">{order.deny.reasons.join(" ")}</p> : null}
          {order.needs_approval_because?.reasons?.length ? (
            <p className="mt-1 text-slate-600">{order.needs_approval_because.reasons.join(" ")}</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
