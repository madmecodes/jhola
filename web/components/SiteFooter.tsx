import Link from "next/link";
import Logo from "./Logo";
import { CONTACT_EMAIL, HACKATHON_NAME } from "@/lib/config";

export default function SiteFooter() {
  return (
    <footer className="mt-auto border-t border-line bg-sand/60">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-12 sm:px-6 md:grid-cols-[1.4fr_1fr_1fr]">
        <div>
          <div className="flex items-center gap-2.5">
            <Logo className="h-8 w-8" />
            <span className="font-display text-xl font-semibold">Jhola</span>
          </div>
          <p className="mt-3 max-w-sm text-sm leading-relaxed text-ink-soft">
            Household ordering on WhatsApp, with family rules that the AI cannot talk its way around.
          </p>
          <p className="mt-4 text-sm text-ink-soft">
            Jhola is a student project built for the {HACKATHON_NAME} hackathon.
          </p>
        </div>
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-jute">Legal</h2>
          <ul className="mt-3 space-y-2 text-sm">
            <li>
              <Link href="/privacy" className="underline-offset-4 hover:underline">
                Privacy policy
              </Link>
            </li>
            <li>
              <Link href="/terms" className="underline-offset-4 hover:underline">
                Terms of use
              </Link>
            </li>
          </ul>
        </div>
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-jute">Contact</h2>
          <p className="mt-3 text-sm">
            Questions or data requests:{" "}
            <a href={`mailto:${CONTACT_EMAIL}`} className="font-medium underline underline-offset-4">
              {CONTACT_EMAIL}
            </a>
          </p>
        </div>
      </div>
      <div className="border-t border-line/80">
        <div className="mx-auto flex max-w-6xl flex-col gap-1 px-4 py-5 text-xs text-ink-soft sm:flex-row sm:justify-between sm:px-6">
          <span>&copy; {new Date().getFullYear()} Jhola. Payments shown on this site are simulated.</span>
          <span>Built on AWS.</span>
        </div>
      </div>
    </footer>
  );
}
