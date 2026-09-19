import Logo from "../Logo";
import Parchi from "./Parchi";

const cart = [
  { name: "Aashirvaad atta", size: "5 kg", price: 285 },
  { name: "Toned milk", size: "2 x 500 ml", price: 58 },
  { name: "Coriander", size: "1 bunch", price: 15 },
  { name: "Potatoes", size: "1 kg", price: 40 },
  { name: "Tomatoes", size: "500 g", price: 30 },
  { name: "Arhar (toor) dal", size: "1 kg", price: 175 },
  { name: "Basmati rice", size: "5 kg", price: 520 },
];
const total = cart.reduce((sum, item) => sum + item.price, 0);
const rs = (n: number) => `Rs ${n.toLocaleString("en-IN")}`;

function Tick() {
  return (
    <svg viewBox="0 0 16 11" className="inline h-2.5 w-3.5" aria-hidden>
      <path d="M1 6l3 3 6-7M6 9l1 0 7-8" fill="none" stroke="#3b82c4" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

// WhatsApp-style conversation, built in HTML/CSS. Illustrative only: no real number.
export default function ChatMockup() {
  return (
    <div className="relative mx-auto w-full max-w-[360px]">
      <div className="overflow-hidden rounded-[2.2rem] border-[9px] border-ink bg-ink shadow-[0_30px_60px_-25px_rgba(31,42,90,0.55)]">
        {/* Chat header */}
        <div className="flex items-center gap-3 bg-ink px-4 pb-3 pt-2 text-cream">
          <Logo className="h-9 w-9 ring-2 ring-cream/25" />
          <div className="min-w-0 leading-tight">
            <p className="text-sm font-semibold">Jhola</p>
            <p className="text-[11px] text-cream/70">Household ordering assistant</p>
          </div>
        </div>

        <div className="chat-wallpaper space-y-3 px-3 pb-4 pt-3 text-[13px] leading-snug">
          <p className="mx-auto w-fit rounded-md bg-paper/90 px-2.5 py-0.5 text-[10.5px] font-medium text-ink-soft shadow-sm">
            TODAY
          </p>

          {/* Outgoing: photo of the parchi */}
          <div className="ml-auto w-[78%] rounded-xl rounded-tr-sm bg-chat-out p-1.5 shadow-sm">
            <div className="rounded-lg bg-sand p-3">
              <Parchi className="rotate-[-2deg]" />
            </div>
            <p className="px-1.5 pt-1.5 text-ink">Ghar ka saaman, please</p>
            <p className="px-1.5 text-right text-[10px] text-ink-soft">
              9:41 <Tick />
            </p>
          </div>

          {/* Incoming: matched cart */}
          <div className="mr-auto w-[88%] rounded-xl rounded-tl-sm bg-paper p-3 shadow-sm">
            <p className="text-ink">
              Read your list. <strong>7 of 7 items</strong> matched to your usual brands:
            </p>
            <ul className="mt-2 divide-y divide-line/80 text-[12px]">
              {cart.map((item) => (
                <li key={item.name} className="flex items-baseline justify-between gap-2 py-1">
                  <span className="min-w-0">
                    <span className="font-medium text-ink">{item.name}</span>{" "}
                    <span className="text-ink-soft">{item.size}</span>
                  </span>
                  <span className="shrink-0 tabular-nums text-ink">{rs(item.price)}</span>
                </li>
              ))}
            </ul>
            <div className="mt-1.5 flex items-baseline justify-between border-t border-ink/20 pt-1.5 font-semibold">
              <span>Total</span>
              <span className="tabular-nums">{rs(total)}</span>
            </div>
            <p className="mt-2 rounded-md bg-turmeric-soft px-2 py-1.5 text-[11.5px] text-ink">
              Above the Rs 1,000 household limit, so it needs your approval.
            </p>
            <p className="pt-1 text-right text-[10px] text-ink-soft">9:41</p>
          </div>

          {/* Approval buttons, styled like WhatsApp quick replies */}
          <div className="mr-auto grid w-[88%] grid-cols-2 gap-1.5" aria-label="Approval buttons (illustration)">
            <span className="rounded-lg bg-paper py-2 text-center text-[12.5px] font-semibold text-leaf shadow-sm">
              Approve {rs(total)}
            </span>
            <span className="rounded-lg bg-paper py-2 text-center text-[12.5px] font-semibold text-terracotta shadow-sm">
              Edit cart
            </span>
          </div>

          {/* Confirmation */}
          <div className="mr-auto w-[88%] rounded-xl rounded-tl-sm bg-paper p-3 shadow-sm">
            <p className="flex items-start gap-2 text-ink">
              <span className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full bg-leaf text-[9px] text-cream" aria-hidden>
                <svg viewBox="0 0 10 8" className="h-2 w-2.5"><path d="M1 4l2.5 2.5L9 1" fill="none" stroke="currentColor" strokeWidth="1.8" /></svg>
              </span>
              <span>
                Approved by Meera. Paid from this month&apos;s spending mandate. Logged to your audit trail.
              </span>
            </p>
            <p className="pt-1 text-right text-[10px] text-ink-soft">9:42</p>
          </div>
        </div>
      </div>
    </div>
  );
}
