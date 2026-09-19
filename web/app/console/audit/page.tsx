import type { Metadata } from "next";
import { Suspense } from "react";
import AuditView from "@/components/console/AuditView";
import { SkeletonList } from "@/components/console/ui";

export const metadata: Metadata = { title: "Audit trail" };

export default function AuditPage() {
  return (
    <Suspense fallback={<SkeletonList rows={6} className="h-20" />}>
      <AuditView />
    </Suspense>
  );
}
