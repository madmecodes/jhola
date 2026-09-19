import type { Metadata } from "next";
import ConsoleShell from "@/components/console/ConsoleShell";

export const metadata: Metadata = {
  title: { default: "Family console", template: "%s - Jhola console" },
  description: "Live view of the Jhola household: orders, Cedar decisions, approvals, rules and the audit trail.",
};

export default function ConsoleLayout({ children }: LayoutProps<"/console">) {
  return <ConsoleShell>{children}</ConsoleShell>;
}
