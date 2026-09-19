import type { Metadata } from "next";
import RulesView from "@/components/console/RulesView";

export const metadata: Metadata = { title: "Rules" };

export default function RulesPage() {
  return <RulesView />;
}
