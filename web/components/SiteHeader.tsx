import Link from "next/link";
import Logo from "./Logo";

const nav = [
  { href: "/#how", label: "How it works" },
  { href: "/#rules", label: "Household rules" },
  { href: "/#safety", label: "Safety" },
  { href: "/#faq", label: "FAQ" },
];

export default function SiteHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-line/70 bg-cream/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5" aria-label="Jhola home">
          <Logo className="h-9 w-9" />
          <span className="font-display text-2xl font-semibold tracking-tight">Jhola</span>
          <span lang="hi" className="font-hindi hidden text-lg text-jute sm:inline">
            झोला
          </span>
        </Link>
        <nav aria-label="Main" className="hidden items-center gap-7 text-sm font-medium text-ink-soft md:flex">
          {nav.map((item) => (
            <Link key={item.href} href={item.href} className="transition-colors hover:text-ink">
              {item.label}
            </Link>
          ))}
        </nav>
        <Link
          href="/#how"
          className="rounded-full bg-ink px-4 py-2 text-sm font-semibold text-cream transition-colors hover:bg-ink/90"
        >
          See how it works
        </Link>
      </div>
    </header>
  );
}
