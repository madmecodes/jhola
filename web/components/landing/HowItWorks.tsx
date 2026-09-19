import howPhoto from "@/public/images/how-it-works.webp";
import SectionHeading from "./SectionHeading";
import SectionPhoto from "./SectionPhoto";

const steps = [
  {
    title: "Send it the way you already do",
    body: "A photo of the handwritten parchi, a voice note, or a text. On WhatsApp, to Jhola, like you would to the shop. Voice works two ways: voice notes on WhatsApp and live voice in the store.",
    note: "aata 5kg, doodh 2, dhaniya",
  },
  {
    title: "Jhola reads and matches",
    body: "Every item is matched to your household's usual brand and pack size. If something is out of stock, it substitutes only within your rules.",
    note: "atta → Aashirvaad 5 kg",
  },
  {
    title: "Household rules decide",
    body: "Who can buy what, and how much, is set by the family admin. Anything outside the rules is stopped or sent for approval.",
    note: "above Rs 1,000 → ask admin",
  },
  {
    title: "Pay within a monthly mandate",
    body: "Payment happens inside a monthly UPI AutoPay-style spending cap that the admin sets once. No card details in chat.",
    note: "cap: Rs 12,000 / month",
  },
  {
    title: "Everything is on the record",
    body: "Every read, match, policy check and payment is written to an audit trail the admin can open at any time.",
    note: "9:42 approved by Meera",
  },
];

export default function HowItWorks() {
  return (
    <section id="how" className="scroll-mt-20 border-y border-line bg-paper/70" aria-labelledby="how-title">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <div className="grid items-center gap-10 lg:grid-cols-[1fr_1.05fr] lg:gap-14">
          <SectionHeading id="how-title" eyebrow="How it works" title="From parchi to doorstep, without a new habit">
            Jhola keeps the way Indian households already order, and adds the parts that were missing: consistent
            brands, spending rules and a record of every rupee.
          </SectionHeading>
          <SectionPhoto
            src={howPhoto}
            alt="A house helper in a kitchen taking a phone photo of a handwritten grocery list"
            className="lg:rotate-[1.2deg]"
          />
        </div>
        <ol className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-5">
          {steps.map((step, i) => (
            <li key={step.title} className="stitch flex flex-col rounded-2xl border border-line bg-cream p-6">
              <span className="font-display text-4xl font-semibold text-turmeric" aria-hidden>
                {String(i + 1).padStart(2, "0")}
              </span>
              <h3 className="font-display mt-3 text-lg font-semibold leading-snug">{step.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-ink-soft">{step.body}</p>
              <p className="font-hand mt-auto pt-4 text-lg text-jute">{step.note}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
