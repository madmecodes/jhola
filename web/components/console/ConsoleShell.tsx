"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useSyncExternalStore, type ReactNode } from "react";
import { FlaskConical, LayoutDashboard, MessageCircle, ScrollText, ShieldAlert, Scale } from "lucide-react";
import Logo from "@/components/Logo";
import { api, connectionStore, IS_LIVE } from "@/lib/jhola/client";
import { AdminKeyControl } from "./AdminKey";

const NAV = [
  { href: "/console", label: "Overview", icon: LayoutDashboard },
  { href: "/console/try", label: "Try it", icon: MessageCircle },
  { href: "/console/audit", label: "Audit trail", icon: ScrollText },
  { href: "/console/rules", label: "Rules", icon: Scale },
  { href: "/console/redteam", label: "Try to break it", icon: ShieldAlert },
] as const;

function LiveIndicator() {
  const conn = useSyncExternalStore(connectionStore.subscribe, connectionStore.get, connectionStore.getServer);

  useEffect(() => {
    if (!IS_LIVE) return;
    const ping = () => api.household().catch(() => undefined);
    const t = setInterval(ping, 20000);
    ping();
    return () => clearInterval(t);
  }, []);

  if (!IS_LIVE) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-sand px-2.5 py-1 text-xs font-semibold text-ink-soft" title="No backend configured. The console runs on built-in sample data.">
        <FlaskConical className="h-3.5 w-3.5" aria-hidden /> Sample data
      </span>
    );
  }
  const up = conn === "up";
  const label = conn === "up" ? "Live" : conn === "down" ? "Offline" : "Connecting";
  return (
    <span
      role="status"
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${
        up ? "border-leaf/40 bg-leaf-soft text-leaf" : conn === "down" ? "border-terracotta/40 bg-terracotta-soft text-terracotta" : "border-line bg-sand text-ink-soft"
      }`}
    >
      <span className="relative flex h-2 w-2" aria-hidden>
        {up ? <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-leaf opacity-60 motion-reduce:animate-none" /> : null}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${up ? "bg-leaf" : conn === "down" ? "bg-terracotta" : "bg-jute"}`} />
      </span>
      {label}
    </span>
  );
}

export default function ConsoleShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isActive = (href: string) => (href === "/console" ? pathname === "/console" : pathname.startsWith(href));

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#console-main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-ink focus:px-3 focus:py-2 focus:text-cream">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-line/70 bg-cream/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <Link href="/" className="flex shrink-0 items-center gap-2" aria-label="Jhola home">
              <Logo className="h-9 w-9" />
              <span className="font-display hidden text-xl font-semibold tracking-tight sm:inline">Jhola</span>
            </Link>
            <span className="hidden text-sm font-medium text-ink-soft md:inline">Family console</span>
            <LiveIndicator />
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden rounded-full border border-turmeric/50 bg-turmeric-soft px-2.5 py-1 text-xs font-semibold text-[#7a5500] lg:inline">
              Demo data, simulated payments
            </span>
            <AdminKeyControl />
          </div>
        </div>
        {/* Mobile tabs */}
        <nav aria-label="Console" className="border-t border-line/60 lg:hidden">
          <ul className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-3 py-2 [scrollbar-width:none]">
            {NAV.map(({ href, label, icon: Icon }) => (
              <li key={href} className="shrink-0">
                <Link
                  href={href}
                  aria-current={isActive(href) ? "page" : undefined}
                  className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-semibold ${
                    isActive(href) ? "bg-ink text-cream" : "text-ink-soft hover:bg-sand hover:text-ink"
                  }`}
                >
                  <Icon className="h-4 w-4" aria-hidden />
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </header>

      <div className="mx-auto flex w-full max-w-7xl flex-1 gap-8 px-4 sm:px-6">
        <aside className="hidden w-56 shrink-0 lg:block">
          <nav aria-label="Console" className="sticky top-20 py-6">
            <ul className="space-y-1">
              {NAV.map(({ href, label, icon: Icon }) => (
                <li key={href}>
                  <Link
                    href={href}
                    aria-current={isActive(href) ? "page" : undefined}
                    className={`flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-semibold transition-colors ${
                      isActive(href) ? "bg-ink text-cream" : "text-ink-soft hover:bg-sand hover:text-ink"
                    }`}
                  >
                    <Icon className="h-4 w-4" aria-hidden />
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
            <div className="mt-6 rounded-2xl border border-line bg-paper p-4 text-xs leading-relaxed text-ink-soft">
              <p className="font-semibold text-ink">The same agent runs on WhatsApp</p>
              <p className="mt-1">Message +91 96063 54404. Orders and approvals show up here within seconds.</p>
            </div>
          </nav>
        </aside>
        <main id="console-main" className="min-w-0 flex-1 py-6 lg:py-8">
          <p className="mb-4 inline-flex rounded-full border border-turmeric/50 bg-turmeric-soft px-2.5 py-1 text-xs font-semibold text-[#7a5500] lg:hidden">
            Demo data, simulated payments
          </p>
          {children}
        </main>
      </div>
    </div>
  );
}
