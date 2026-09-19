import Link from "next/link";
import HeroVisual from "./HeroVisual";

const inputs = ["Photo of a handwritten list", "Voice note in Hindi or English", "A quick text"];

export default function Hero() {
  return (
    <section className="overflow-hidden" aria-labelledby="hero-title">
      <div className="mx-auto grid max-w-6xl items-center gap-14 px-4 pb-20 pt-12 sm:px-6 md:pt-20 lg:grid-cols-[1.1fr_1fr] lg:gap-10">
        <div>
          <p className="inline-flex items-center gap-2 rounded-full border border-line bg-paper px-3 py-1 text-sm text-ink-soft">
            <span lang="hi" className="font-hindi text-base text-ink">
              झोला
            </span>
            <span aria-hidden>/</span>
            <span>jhola, the cloth shopping bag</span>
          </p>
          <h1
            id="hero-title"
            className="font-display mt-6 text-[2.6rem] font-semibold leading-[1.05] tracking-tight sm:text-6xl"
          >
            Send the parchi.
            <br />
            <span className="text-jute">Jhola</span> handles the rest.
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-soft">
            Your family already sends the kirana a handwritten list, a voice note or a text. Jhola reads it on
            WhatsApp, matches every item to your usual brands, checks your household rules and orders, with an
            approval tap whenever it matters.
          </p>
          <ul className="mt-7 flex flex-wrap gap-2" aria-label="Ways to order">
            {inputs.map((i) => (
              <li key={i} className="rounded-full bg-sand px-3.5 py-1.5 text-sm font-medium text-ink">
                {i}
              </li>
            ))}
          </ul>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Link
              href="/console/try"
              className="rounded-full bg-ink px-6 py-3 text-sm font-semibold text-cream shadow-sm transition-colors hover:bg-ink/90"
            >
              Try the live demo
            </Link>
            <a
              href="#how"
              className="rounded-full border border-ink/25 px-6 py-3 text-sm font-semibold text-ink transition-colors hover:border-ink/60"
            >
              How it works
            </a>
            <a
              href="#safety"
              className="rounded-full border border-ink/25 px-6 py-3 text-sm font-semibold text-ink transition-colors hover:border-ink/60"
            >
              Why it is safe
            </a>
          </div>
          <p className="mt-6 text-sm text-ink-soft">Works inside WhatsApp. Nothing new to install for the family.</p>
        </div>
        <HeroVisual />
      </div>
    </section>
  );
}
