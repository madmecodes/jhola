import rulesPhoto from "@/public/images/household-rules.webp";
import SectionHeading from "./SectionHeading";
import SectionPhoto from "./SectionPhoto";

type Member = {
  name: string;
  role: string;
  initials: string;
  tone: string;
  can: string[];
  limit: string;
  example: { text: string; outcome: "allowed" | "approval" | "denied" };
};

const members: Member[] = [
  {
    name: "Meera",
    role: "Family admin",
    initials: "M",
    tone: "bg-ink text-cream",
    can: ["Sets and edits all rules", "Approves with one tap on WhatsApp", "Sees the full audit trail"],
    limit: "Monthly cap Rs 12,000",
    example: { text: "Approved Rs 1,123 grocery order", outcome: "allowed" },
  },
  {
    name: "Sunita",
    role: "House help",
    initials: "S",
    tone: "bg-leaf text-cream",
    can: ["Groceries and cleaning supplies", "Up to Rs 500 a day"],
    limit: "Rs 500 / day",
    example: { text: "Milk, bread, eggs: Rs 146", outcome: "allowed" },
  },
  {
    name: "Aarav",
    role: "Teenager",
    initials: "A",
    tone: "bg-turmeric text-ink",
    can: ["Stationery and snacks only", "Up to Rs 300 a week"],
    limit: "Rs 300 / week",
    example: { text: "Energy drink, 4 cans", outcome: "denied" },
  },
  {
    name: "Dadaji",
    role: "Grandparent",
    initials: "D",
    tone: "bg-jute text-cream",
    can: ["Groceries and medicines", "Orders by voice note in Hindi"],
    limit: "Rs 800 / day",
    example: { text: "Monthly medicines: Rs 1,460", outcome: "approval" },
  },
];

const outcomeStyle = {
  allowed: { label: "Allowed", cls: "bg-leaf-soft text-leaf" },
  approval: { label: "Sent to admin", cls: "bg-turmeric-soft text-ink" },
  denied: { label: "Blocked by rule", cls: "bg-terracotta-soft text-terracotta" },
};

export default function HouseholdRules() {
  return (
    <section id="rules" className="scroll-mt-20" aria-labelledby="rules-title">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <div className="grid items-center gap-10 lg:grid-cols-[1.05fr_1fr] lg:gap-14">
          <SectionPhoto
            src={rulesPhoto}
            alt="A family at the dining table looking at a phone together"
            className="order-last lg:order-first lg:rotate-[-1.2deg]"
          />
          <SectionHeading id="rules-title" eyebrow="Household rules" title="Everyone can order. Not everyone can order everything.">
            The admin decides who may buy what, and up to how much. Jhola applies the same rules every time, whoever
            is asking and however they ask.
          </SectionHeading>
        </div>
        <ul className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {members.map((m) => {
            const o = outcomeStyle[m.example.outcome];
            return (
              <li key={m.name} className="flex flex-col rounded-2xl border border-line bg-paper p-6 shadow-[0_1px_0_rgba(31,42,90,0.04)]">
                <div className="flex items-center gap-3">
                  <span className={`font-display grid h-11 w-11 place-items-center rounded-full text-lg font-semibold ${m.tone}`} aria-hidden>
                    {m.initials}
                  </span>
                  <div>
                    <h3 className="font-semibold leading-tight">{m.name}</h3>
                    <p className="text-sm text-ink-soft">{m.role}</p>
                  </div>
                </div>
                <ul className="mt-5 space-y-2 text-sm text-ink">
                  {m.can.map((c) => (
                    <li key={c} className="flex gap-2">
                      <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-jute" aria-hidden />
                      {c}
                    </li>
                  ))}
                </ul>
                <p className="mt-5 text-xs font-semibold uppercase tracking-[0.12em] text-jute">Limit</p>
                <p className="font-display text-xl font-semibold">{m.limit}</p>
                <div className="mt-auto pt-5">
                  <div className="rounded-xl border border-dashed border-line p-3">
                    <p className="text-sm text-ink">{m.example.text}</p>
                    <span className={`mt-2 inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${o.cls}`}>{o.label}</span>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
        <p className="mt-6 text-sm text-ink-soft">Every order above Rs 1,000 needs the admin&apos;s approval, whoever places it.</p>
      </div>
    </section>
  );
}
