/** Wire protocol of the Jhola voice server (voice/src/jhola_voice/server.py). */

export type VoiceMember = "mom" | "dad" | "didi" | "teen";

export type VoiceCartLine = {
  sku: string;
  label: string;
  name: string;
  brand: string;
  category: string;
  qty: number;
  unit_price_inr: number;
  line_total_inr: number;
};

export type VoiceCart = {
  member: string;
  lines: VoiceCartLine[];
  total_inr: number;
  items: number;
};

export type VoiceDecisionLine = {
  sku: string;
  label: string;
  qty: number;
  line_total_inr: number;
  allowed: boolean;
  policy_ids: string[];
  reasons: string[];
  reasons_hinglish: string[];
};

export type VoiceDecisions = {
  type: "decisions";
  member: string;
  role: string;
  lines: VoiceDecisionLine[];
  payable_inr: number;
  mandate_remaining_inr: number;
  checkout_outcome: "auto_pay" | "needs_approval" | "denied" | "all_lines_blocked" | "empty";
  why?: { policy_ids?: string[]; reasons?: string[] };
  approver?: string | null;
};

export type VoiceOrder = {
  type: "order";
  order_id?: string;
  status: string;
  payable_inr?: number;
  payment?: { txn_id: string; upi_ref: string; amount_inr: number; simulated: boolean } | null;
  blocked_lines?: { label: string; qty: number; reasons: string[]; reasons_hinglish: string[] }[];
  mandate_remaining_inr?: number;
  needs_approval_because?: { reasons?: string[] };
  deny?: { reasons?: string[] };
  notifications?: { to: string; text: string }[];
  next_step?: string;
};

export type VoiceServerEvent =
  | { type: "ready"; session_id: string; member: string; voice: string; max_seconds: number }
  | { type: "transcript"; role: "user" | "assistant"; text: string; stage?: string }
  | { type: "interrupted" }
  | { type: "tool"; name: string; phase: "start" | "end"; args?: Record<string, unknown>; summary?: string }
  | { type: "cart"; cart: VoiceCart }
  | VoiceDecisions
  | VoiceOrder
  | { type: "error"; message: string }
  | { type: "ended"; reason: string }
  | { type: "model_closed"; reason: string }
  | { type: "pong" };

export type VoiceStatus = "idle" | "connecting" | "listening" | "speaking" | "ended" | "error";
