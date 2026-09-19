"use client";

import { useEffect, useRef, useState } from "react";
import { ImagePlus, SendHorizontal, X } from "lucide-react";
import Logo from "@/components/Logo";
import { api, errorMessage } from "@/lib/jhola/client";
import type { ChatButton, ChatMember, Order } from "@/lib/jhola/types";
import { DecisionChip, PageHeader, PolicyChip, StatusChip, rs } from "./ui";

const MEMBERS: { id: ChatMember; label: string; sub: string; initials: string; tone: string }[] = [
  { id: "mom", label: "Mom", sub: "Admin", initials: "SG", tone: "bg-ink text-cream" },
  { id: "dad", label: "Dad", sub: "Adult", initials: "RG", tone: "bg-jute text-white" },
  { id: "didi", label: "Didi", sub: "House help", initials: "KD", tone: "bg-leaf text-white" },
  { id: "teen", label: "Teen", sub: "Aarav", initials: "AG", tone: "bg-turmeric text-ink" },
];

const QUICK: { member: ChatMember; text: string }[] = [
  { member: "didi", text: "doodh 2, dhaniya, aloo 1 kg" },
  { member: "teen", text: "4 Red Bull and a geometry box" },
  { member: "dad", text: "rajma chawal for 6 tonight" },
  { member: "didi", text: "shampoo aur surf" },
  { member: "mom", text: "atta, namak, 2 surf excel" },
];

type Msg = {
  id: number;
  from: "me" | "bot";
  text?: string;
  image?: string;
  buttons?: ChatButton[];
  order?: Order;
  error?: boolean;
  system?: boolean;
  owner?: ChatMember;
  at: string;
};

function memberFrom(v: unknown): ChatMember | null {
  const t = String(v ?? "").toLowerCase();
  if (/mom|sunita|admin/.test(t)) return "mom";
  if (/dad|rajesh/.test(t)) return "dad";
  if (/didi|kamla|house/.test(t)) return "didi";
  if (/teen|aarav/.test(t)) return "teen";
  return null;
}
const LABEL: Record<ChatMember, string> = { mom: "Mom", dad: "Dad", didi: "Didi", teen: "Teen" };

let msgId = 0;
const now = () => new Date().toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });

async function fileToJpeg(file: File): Promise<{ base64: string; dataUrl: string }> {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    await new Promise<void>((res, rej) => {
      img.onload = () => res();
      img.onerror = () => rej(new Error("Could not read that image."));
      img.src = url;
    });
    const scale = Math.min(1, 1400 / Math.max(img.width, img.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    canvas.getContext("2d")!.drawImage(img, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
    return { dataUrl, base64: dataUrl.split(",")[1] ?? "" };
  } finally {
    URL.revokeObjectURL(url);
  }
}

function OrderSummary({ order }: { order: Order }) {
  return (
    <div className="mt-2 rounded-lg border border-line bg-cream/70 p-2">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] text-ink-soft">{order.order_id}</span>
        <StatusChip status={order.status} />
      </div>
      <ul className="mt-1.5 space-y-1.5">
        {order.items.map((it, i) => (
          <li key={`${it.sku}-${i}`} className="text-[12px]">
            <div className="flex items-start gap-1.5">
              <DecisionChip decision={it.decision} />
              <span className="min-w-0 flex-1">
                {it.brand} {it.name} x{it.qty}
              </span>
              <span className="tabular-nums">{rs(it.price_inr * it.qty)}</span>
            </div>
            <div className="mt-0.5 flex flex-wrap gap-1 pl-12">
              {it.policy_ids.map((p) => (
                <PolicyChip key={p} id={p} />
              ))}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function TryView() {
  const [member, setMember] = useState<ChatMember>("didi");
  const [threads, setThreads] = useState<Record<ChatMember, Msg[]>>({ mom: [], dad: [], didi: [], teen: [] });
  const [text, setText] = useState("");
  const [image, setImage] = useState<{ base64: string; dataUrl: string } | null>(null);
  const [sending, setSending] = useState(false);
  const [thinking, setThinking] = useState<string | null>(null);
  const [sessions] = useState<Record<ChatMember, string>>(() => {
    const r = Math.random().toString(36).slice(2, 8);
    return { mom: `web-mom-${r}`, dad: `web-dad-${r}`, didi: `web-didi-${r}`, teen: `web-teen-${r}` };
  });
  const scroller = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const thread = threads[member];
  const m = MEMBERS.find((x) => x.id === member)!;

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [thread.length, sending]);

  const push = (who: ChatMember, msg: Omit<Msg, "id" | "at">) =>
    setThreads((t) => ({ ...t, [who]: [...t[who], { ...msg, id: ++msgId, at: now() }] }));

  async function send(who: ChatMember, body: string, img: typeof image, buttonId?: string) {
    if (!body.trim() && !img && !buttonId) return;
    push(who, { from: "me", text: body.trim() || undefined, image: img?.dataUrl });
    setText("");
    setImage(null);
    setSending(true);
    setThinking(null);
    try {
      const res = await api.chat(
        {
          member: who,
          session_id: sessions[who],
          text: body.trim() || undefined,
          button_id: buttonId,
          image_base64: img?.base64,
          media_type: img ? "image/jpeg" : undefined,
        },
        (interim) => setThinking(interim),
      );
      push(who, { from: "bot", text: res.reply_text, buttons: res.buttons, order: res.order });
      for (const n of res.notifications ?? []) {
        const to = memberFrom(n.to ?? n.member ?? n.member_id ?? n.recipient);
        const body = String(n.text ?? n.reply_text ?? n.body ?? "");
        const label = to ? LABEL[to] : String(n.to ?? n.member ?? "family");
        push(who, { from: "bot", system: true, text: `[Sent to ${label}] ${body}` });
        if (to && to !== who) push(to, { from: "bot", text: body, buttons: n.buttons, owner: to });
      }
    } catch (e) {
      push(who, { from: "bot", text: errorMessage(e), error: true });
    } finally {
      setSending(false);
      setThinking(null);
    }
  }

  // Reply buttons (Approve / Reject and others) go back to the agent as button_id, like a WhatsApp tap.
  function onButton(msg: Msg, b: ChatButton) {
    setThreads((t) => ({ ...t, [member]: t[member].map((x) => (x.id === msg.id ? { ...x, buttons: undefined } : x)) }));
    send(msg.owner ?? member, b.title, null, b.id);
  }

  return (
    <div>
      <PageHeader title="Try it" hindi="आज़माइए">
        Chat with the same agent that runs on WhatsApp. Pick who is sending, type a list the way your family would, or upload a
        parchi photo.
      </PageHeader>
      <p className="mb-5 rounded-2xl border border-line bg-paper px-4 py-2.5 text-sm">
        The same agent also runs on WhatsApp at <strong className="whitespace-nowrap">+91 96063 54404</strong>.
      </p>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="min-w-0">
          <fieldset>
            <legend className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-jute">Sending as</legend>
            <div className="grid grid-cols-4 gap-2" role="radiogroup">
              {MEMBERS.map((x) => (
                <button
                  key={x.id}
                  type="button"
                  role="radio"
                  aria-checked={member === x.id}
                  onClick={() => setMember(x.id)}
                  className={`flex min-w-0 flex-col items-center gap-1 rounded-2xl border p-2 text-center transition-colors sm:flex-row sm:text-left ${
                    member === x.id ? "border-ink bg-paper shadow-sm" : "border-line bg-paper/60 hover:border-ink/40"
                  }`}
                >
                  <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-bold ${x.tone}`} aria-hidden>
                    {x.initials}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold">{x.label}</span>
                    <span className="hidden truncate text-[11px] text-ink-soft sm:block">{x.sub}</span>
                  </span>
                </button>
              ))}
            </div>
          </fieldset>

          <div className="mt-4 overflow-hidden rounded-3xl border-[6px] border-ink bg-ink shadow-[0_30px_60px_-30px_rgba(31,42,90,0.55)]">
            <div className="flex items-center gap-3 px-4 py-2.5 text-cream">
              <Logo className="h-9 w-9 ring-2 ring-cream/25" />
              <div className="min-w-0 leading-tight">
                <p className="text-sm font-semibold">Jhola</p>
                <p className="truncate text-[11px] text-cream/70">Chatting as {m.label} ({m.sub})</p>
              </div>
            </div>
            <div ref={scroller} className="chat-wallpaper h-[26rem] space-y-2.5 overflow-y-auto px-3 py-3 text-[13.5px] leading-snug sm:h-[30rem]" aria-live="polite">
              {thread.length === 0 ? (
                <p className="mx-auto mt-6 max-w-xs rounded-lg bg-paper/90 px-3 py-2 text-center text-xs text-ink-soft shadow-sm">
                  Send a message as {m.label}, or tap a quick prompt.
                </p>
              ) : null}
              {thread.map((msg) =>
                msg.system ? (
                  <p key={msg.id} className="mx-auto w-fit max-w-[92%] whitespace-pre-wrap rounded-lg bg-turmeric-soft/90 px-2.5 py-1 text-center text-[11.5px] text-ink shadow-sm">
                    {msg.text}
                  </p>
                ) : msg.from === "me" ? (
                  <div key={msg.id} className="ml-auto w-fit max-w-[82%] rounded-xl rounded-tr-sm bg-chat-out px-2.5 py-1.5 shadow-sm">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    {msg.image ? <img src={msg.image} alt="Uploaded parchi" className="mb-1 max-h-56 rounded-lg" /> : null}
                    {msg.text ? <p className="whitespace-pre-wrap break-words">{msg.text}</p> : null}
                    <p className="text-right text-[10px] text-ink-soft">{msg.at}</p>
                  </div>
                ) : (
                  <div
                    key={msg.id}
                    className={`mr-auto w-fit max-w-[88%] rounded-xl rounded-tl-sm px-2.5 py-1.5 shadow-sm ${msg.error ? "border border-terracotta/40 bg-terracotta-soft" : "bg-paper"}`}
                  >
                    <p className="whitespace-pre-wrap break-words">{msg.text}</p>
                    {msg.order ? <OrderSummary order={msg.order} /> : null}
                    <p className="text-right text-[10px] text-ink-soft">{msg.at}</p>
                    {msg.buttons?.length ? (
                      <div className="-mx-2.5 mt-1 grid border-t border-line" style={{ gridTemplateColumns: `repeat(${Math.min(msg.buttons.length, 3)}, minmax(0, 1fr))` }}>
                        {msg.buttons.map((b) => {
                          return (
                            <span key={b.id} className="border-line [&:not(:first-child)]:border-l">
                              <button
                                type="button"
                                disabled={sending}
                                onClick={() => onButton(msg, b)}
                                className="w-full py-2 text-center text-sm font-semibold text-[#1f7aa8] hover:bg-cream disabled:cursor-not-allowed disabled:opacity-45"
                              >
                                {b.title}
                              </button>
                            </span>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
                ),
              )}
              {sending ? (
                <div className="mr-auto w-fit max-w-[88%] rounded-xl rounded-tl-sm bg-paper px-3 py-2 shadow-sm" role="status" aria-label="Jhola is thinking">
                  {thinking ? <p className="mb-1 whitespace-pre-wrap text-[12.5px] text-ink-soft">Jhola is thinking. {thinking}</p> : null}
                  <span className="flex gap-1" aria-hidden>
                    {[0, 1, 2].map((i) => (
                      <span key={i} className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink-soft" style={{ animationDelay: `${i * 120}ms` }} />
                    ))}
                  </span>
                </div>
              ) : null}
            </div>

            <form
              className="flex items-end gap-2 bg-sand px-2.5 py-2.5"
              onSubmit={(e) => {
                e.preventDefault();
                send(member, text, image);
              }}
            >
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                className="sr-only"
                id="parchi-upload"
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (!f) return;
                  try {
                    setImage(await fileToJpeg(f));
                  } catch (err) {
                    push(member, { from: "bot", text: errorMessage(err), error: true });
                  }
                }}
              />
              <label
                htmlFor="parchi-upload"
                className="flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-full bg-paper text-ink hover:bg-cream focus-within:outline"
                title="Attach a parchi photo"
              >
                <ImagePlus className="h-5 w-5" aria-hidden />
                <span className="sr-only">Attach a parchi photo</span>
              </label>
              <div className="min-w-0 flex-1 rounded-2xl bg-paper px-3 py-1.5">
                {image ? (
                  <div className="mb-1 flex items-center gap-2">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={image.dataUrl} alt="Parchi to send" className="h-12 w-12 rounded-md object-cover" />
                    <span className="text-xs text-ink-soft">Parchi attached</span>
                    <button type="button" onClick={() => setImage(null)} className="ml-auto rounded-full p-1 hover:bg-sand" aria-label="Remove photo">
                      <X className="h-4 w-4" aria-hidden />
                    </button>
                  </div>
                ) : null}
                <label htmlFor="chat-text" className="sr-only">
                  Message
                </label>
                <input
                  id="chat-text"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={image ? "Add a note (optional)" : "Type a message"}
                  autoComplete="off"
                  className="w-full bg-transparent py-1 text-sm outline-none"
                />
              </div>
              <button
                type="submit"
                disabled={sending || (!text.trim() && !image)}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-leaf text-white disabled:opacity-45"
                aria-label="Send"
              >
                <SendHorizontal className="h-5 w-5" aria-hidden />
              </button>
            </form>
          </div>
        </div>

        <aside aria-labelledby="quick-title" className="space-y-4">
          <div>
            <h2 id="quick-title" className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-jute">
              Quick prompts
            </h2>
            <ul className="space-y-2">
              {QUICK.map((q) => {
                const who = MEMBERS.find((x) => x.id === q.member)!;
                return (
                  <li key={q.text}>
                    <button
                      type="button"
                      disabled={sending}
                      onClick={() => {
                        setMember(q.member);
                        send(q.member, q.text, null);
                      }}
                      className="w-full rounded-2xl border border-line bg-paper px-3 py-2.5 text-left text-sm hover:border-ink/40 disabled:opacity-50"
                    >
                      <span className="font-semibold">{who.label}:</span> {q.text}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
          <div className="rounded-2xl border border-line bg-paper p-4 text-sm text-ink-soft">
            <p className="font-semibold text-ink">What to look for</p>
            <ul className="mt-2 list-disc space-y-1 pl-4">
              <li>Didi&apos;s groceries go through, her shampoo does not.</li>
              <li>Teen gets the geometry box, not the Red Bull.</li>
              <li>Dad&apos;s dinner is above Rs 1,000, so Mom has to approve.</li>
            </ul>
            <p className="mt-2">Approval requests are sent to Mom: switch to Mom to tap Approve or Reject. Every order also appears on Overview and in the Audit trail.</p>
          </div>
        </aside>
      </div>
    </div>
  );
}
