import SiteHeader from "./SiteHeader";
import SiteFooter from "./SiteFooter";
import { LAST_UPDATED } from "@/lib/config";

export default function LegalPage({ title, intro, children }: { title: string; intro: string; children: React.ReactNode }) {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto w-full max-w-3xl px-4 py-16 sm:px-6">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-jute">Last updated {LAST_UPDATED}</p>
        <h1 className="font-display mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">{title}</h1>
        <p className="mt-5 text-lg leading-relaxed text-ink-soft">{intro}</p>
        <div className="mt-10 space-y-8 rounded-2xl border border-line bg-paper p-6 leading-relaxed sm:p-10 [&_h2]:font-display [&_h2]:text-xl [&_h2]:font-semibold [&_li]:mt-1.5 [&_p]:mt-2 [&_p]:text-ink-soft [&_ul]:mt-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:text-ink-soft [&_a]:font-medium [&_a]:text-ink [&_a]:underline [&_a]:underline-offset-4">
          {children}
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
