// Human one-liners for audit events. The backend may omit `summary`, so derive one from `data`.
import type { AuditEvent } from "./types";

type Rec = Record<string, unknown>;
const rec = (v: unknown): Rec => (v && typeof v === "object" && !Array.isArray(v) ? (v as Rec) : {});
const cut = (s: string, n = 140) => (s.length > n ? `${s.slice(0, n - 1)}...` : s);

export function summarizeEvent(e: Pick<AuditEvent, "type" | "summary" | "data">): string {
  if (e.summary) return e.summary;
  const d = rec(e.data);
  const who = typeof d.to === "string" ? d.to : typeof d.member === "string" ? d.member : "";
  switch (e.type) {
    case "message_received":
      return d.text ? `"${cut(String(d.text))}"` : d.has_image ? "Photo received" : "Message received";
    case "voice_transcribed":
      return d.transcript ?? d.text ? `Transcribed: "${cut(String(d.transcript ?? d.text))}"` : "Voice note transcribed";
    case "cart_built": {
      const lines = Array.isArray(d.lines) ? d.lines.length : 0;
      return `Cart built: ${lines} line${lines === 1 ? "" : "s"}${d.total_inr !== undefined ? `, Rs ${Number(d.total_inr).toLocaleString("en-IN")}` : ""}`;
    }
    case "policy_evaluated": {
      const reasons = Array.isArray(d.reasons) ? d.reasons.join(" ") : "";
      const target = d.sku ? ` ${d.sku}${d.qty ? ` x${d.qty}` : ""}` : "";
      return `${String(d.action ?? "check")}${target}: ${d.allowed ? "allowed" : "denied"}${reasons ? `. ${cut(reasons)}` : ""}`;
    }
    case "order_denied":
      return `Order denied${d.stage ? ` at ${d.stage} stage` : ""}`;
    case "payment_captured":
      return `Payment captured${d.amount_inr !== undefined ? `: Rs ${Number(d.amount_inr).toLocaleString("en-IN")}` : ""}${d.upi_ref ? ` (${d.upi_ref})` : ""}`;
    case "approval_requested":
      return "Approval requested from the admin";
    case "approval_response":
    case "approval_rejected":
      return `Admin ${String(d.decision ?? (e.type === "approval_rejected" ? "rejected" : "responded"))}`;
    case "reply_sent":
    case "notification_sent":
      return d.text ? `To ${who || "member"}: "${cut(String(d.text))}"` : `Sent to ${who || "member"}`;
    case "suspicious_content_detected":
      return `Untrusted instructions found in ${d.sku ? String(d.sku) : "content"}, treated as data`;
    default:
      return e.type.replace(/_/g, " ");
  }
}
