// Types for the Jhola backend API. Mirrors the contract the agent service exposes.

export type Role = "admin" | "adult" | "house_help" | "teen" | string;

export type Member = {
  id: string;
  name: string;
  display?: string;
  role: Role;
  phone_masked: string;
  limits_summary: string;
};

export type Rule = {
  id: string;
  title_en: string;
  title_hinglish: string;
  cedar: string;
  source: "base" | "custom";
  active?: boolean;
};

export type Mandate = {
  cap_inr: number;
  used_inr: number;
  remaining_inr: number;
  period: string;
  month?: string;
  approval_threshold_inr?: number;
  house_help_daily_cap_inr?: number;
};

export type HouseholdResponse = {
  household: { name: string };
  members: Member[];
  rules: Rule[];
  mandate: Mandate;
};

export type OrderStatus = "paid" | "pending_approval" | "denied" | "partially_paid" | "rejected" | "draft";

export type OrderItem = {
  sku: string;
  name: string;
  brand: string;
  qty: number;
  price_inr: number;
  decision: "allow" | "deny" | "pending";
  policy_ids: string[];
  reason: string;
  reason_hinglish?: string;
  category?: string;
  line_total_inr?: number;
  amazon_search_url?: string;
  fulfilment?: string;
};

export type Order = {
  order_id: string;
  member_name: string;
  role: Role;
  created_at: string;
  status: OrderStatus;
  total_inr: number;
  paid_inr: number;
  upi_ref?: string | null;
  items: OrderItem[];
  channel: "whatsapp" | "web";
  input_type: "text" | "image" | "voice";
};

export type AuditEvent = {
  ts: string;
  order_id?: string | null;
  type: string;
  actor?: string | null;
  summary?: string;
  data?: unknown;
};

export type PendingApproval = {
  order_id: string;
  member_name: string;
  total_inr: number;
  items_count: number;
  created_at: string;
};

export type ChatMember = "didi" | "teen" | "dad" | "mom";

export type ChatRequest = {
  member: ChatMember;
  session_id?: string;
  button_id?: string;
  text?: string;
  image_base64?: string;
  media_type?: string;
};

export type ChatButton = { id: string; title: string };

export type ChatNotification = { to?: string; member?: string; text?: string; reply_text?: string; buttons?: ChatButton[] } & Record<string, unknown>;

export type ChatResponse = {
  reply_text: string;
  notifications?: ChatNotification[];
  member?: string;
  buttons?: ChatButton[];
  order?: Order;
  decisions?: unknown;
};

export type RuleTestResult = { case: string; expected: string; actual: string; pass: boolean };

export type RuleDraft = {
  cedar: string;
  explanation_en: string;
  explanation_hinglish: string;
  validation: { ok: boolean; errors: string[] };
  test_results?: RuleTestResult[];
};

export type AttackKind = "injection" | "overspend" | "forbidden_category";

export type RedteamResult = {
  attack: AttackKind | string;
  simulated_compromised_model: boolean;
  model_proposed: unknown[];
  decisions: unknown[];
  payment: unknown;
  audit: unknown[];
  verdict: "blocked" | "allowed";
  description?: string;
  member?: string;
  message?: string;
  flagged_untrusted_text?: string[];
  agent_reply?: string;
  sandbox?: boolean;
};
