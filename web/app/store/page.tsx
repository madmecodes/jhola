import type { Metadata } from "next";
import StoreView from "@/components/store/StoreView";

export const metadata: Metadata = {
  title: "Store concept",
  description:
    "Concept prototype: how Jhola could plug into a quick-commerce app. Household rules checked by Cedar on every cart line. Not affiliated with Amazon.",
};

export default function StorePage() {
  return <StoreView />;
}
