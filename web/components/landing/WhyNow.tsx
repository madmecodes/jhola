import SectionHeading from "./SectionHeading";

const notes = [
  {
    when: "10 Sep 2026",
    what: "NPCI, Global Fintech Fest",
    body: "As reported, NPCI chairman Ajay Kumar Choudhary said an AI agent may work out what a user wants, but it should not be the thing that approves the payment, and that decision making and execution must remain separate. NPCI has said no agent-authorisation framework exists yet for UPI.",
  },
  {
    when: "11 Sep 2026",
    what: "Amazon Pay, same event",
    body: "As reported, Amazon Pay launched agentic UPI payments: a Smart Wallet that lets AI agents make UPI payments on a user's behalf, live first for flight booking.",
  },
  {
    when: "Since Oct 2025",
    what: "Amazon Pay UPI Circle",
    body: "As reported, UPI Circle already lets one person delegate UPI spending to another, in full or in part, with spending limits, aimed at household managers, teenagers aged 13 to 17 and dependents without their own bank accounts.",
  },
];

export default function WhyNow() {
  return (
    <section id="why-now" className="scroll-mt-20 border-y border-line bg-cream" aria-labelledby="why-now-title">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <SectionHeading id="why-now-title" eyebrow="Why now" title="Agents can pay. Nothing yet decides whether they may.">
          Three things happened in the last few weeks. Put together, they describe a gap.
        </SectionHeading>

        <ol className="mt-10 grid gap-5 md:grid-cols-3">
          {notes.map((n) => (
            <li key={n.when} className="flex flex-col rounded-2xl border border-line bg-paper p-6">
              <p className="font-display text-sm font-semibold text-turmeric">{n.when}</p>
              <p className="mt-1 font-semibold">{n.what}</p>
              <p className="mt-2 text-sm leading-relaxed text-ink-soft">{n.body}</p>
            </li>
          ))}
        </ol>

        <p className="mt-8 max-w-3xl text-base leading-relaxed text-ink sm:text-lg">
          <strong>UPI Circle delegates to a person. Nobody has delegated to an agent, because there is no framework
          for it yet</strong> &mdash; NPCI said so on 10 September 2026. Jhola is a working sketch of the missing piece:
          the model reads intent, and a deterministic engine verifies identity, mandate, limits and consent, and
          writes down why.
        </p>
      </div>
    </section>
  );
}
