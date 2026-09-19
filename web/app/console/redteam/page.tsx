import type { Metadata } from "next";
import RedteamView from "@/components/console/RedteamView";

export const metadata: Metadata = { title: "Try to break it" };

export default function RedteamPage() {
  return <RedteamView />;
}
