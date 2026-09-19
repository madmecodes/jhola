import type { Metadata } from "next";
import TryView from "@/components/console/TryView";

export const metadata: Metadata = { title: "Try it" };

export default function TryPage() {
  return <TryView />;
}
