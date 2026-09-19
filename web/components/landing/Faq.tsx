import SectionHeading from "./SectionHeading";

const faqs = [
  {
    q: "Do family members need to install anything?",
    a: "No. Everyone orders from WhatsApp, the way they already message the local shop. Only the admin uses a simple web console to set rules and read the audit trail.",
  },
  {
    q: "Can Jhola read handwriting in Hindi and English?",
    a: "Yes, that is the point. Lists often mix both, like \"aata 5kg, धनिया, doodh 2\". Jhola also understands voice notes and plain text.",
  },
  {
    q: "What stops someone from buying something they should not?",
    a: "Household rules. They are checked by a separate policy engine, not by the AI, so a clever message or a misleading product listing cannot talk its way past them.",
  },
  {
    q: "Is my money actually charged?",
    a: "Not in this version. Jhola is a student project, and all payments and spending mandates are simulated. No real purchases are made.",
  },
  {
    q: "What happens to my messages and photos?",
    a: "They are used only to run the order demo and are never sold. You can ask for them to be deleted at any time. See the privacy policy for details.",
  },
];

export default function Faq() {
  return (
    <section id="faq" className="scroll-mt-20" aria-labelledby="faq-title">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-20 sm:px-6 lg:grid-cols-[1fr_1.4fr]">
        <SectionHeading id="faq-title" eyebrow="FAQ" title="Questions families ask" />
        <div className="divide-y divide-line rounded-2xl border border-line bg-paper">
          {faqs.map((f) => (
            <details key={f.q} className="group px-5 py-4 sm:px-6">
              <summary className="flex cursor-pointer items-center justify-between gap-4 font-semibold">
                {f.q}
                <span className="faq-plus grid h-7 w-7 shrink-0 place-items-center rounded-full bg-sand text-lg leading-none transition-transform" aria-hidden>
                  +
                </span>
              </summary>
              <p className="mt-3 text-sm leading-relaxed text-ink-soft">{f.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
