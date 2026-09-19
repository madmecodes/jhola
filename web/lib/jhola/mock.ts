// In-browser mock of the Jhola backend. Used when NEXT_PUBLIC_JHOLA_API is not set.
// It follows the API contract exactly and applies a small copy of the household Cedar rules,
// so the console behaves like the real thing (orders, approvals, audit trail, red team).

import type {
  AttackKind,
  AuditEvent,
  ChatRequest,
  ChatResponse,
  HouseholdResponse,
  Member,
  Order,
  OrderItem,
  PendingApproval,
  RedteamResult,
  Rule,
  RuleDraft,
} from "./types";
import REDTEAM_SAMPLES from "./redteam-samples.json";

type Sku = {
  sku: string;
  name: string;
  brand: string;
  size: string;
  category: string;
  price_inr: number;
  fulfilment: "amazon_now" | "amazon_fresh";
  keys: string[];
};

const CATALOG: Sku[] = [
  { sku: "nandini-toned-milk-500ml", name: "Toned Milk", brand: "Nandini", size: "500 ml", category: "dairy", price_inr: 24, fulfilment: "amazon_now", keys: ["doodh", "milk"] },
  { sku: "amul-masti-dahi-1kg", name: "Masti Dahi", brand: "Amul", size: "1 kg", category: "dairy", price_inr: 80, fulfilment: "amazon_now", keys: ["dahi", "curd"] },
  { sku: "freshfarm-coriander-100g", name: "Coriander Leaves", brand: "FreshFarm", size: "100 g", category: "vegetables", price_inr: 15, fulfilment: "amazon_now", keys: ["dhaniya", "coriander"] },
  { sku: "freshfarm-potato-1kg", name: "Potato", brand: "FreshFarm", size: "1 kg", category: "vegetables", price_inr: 30, fulfilment: "amazon_now", keys: ["aloo", "potato"] },
  { sku: "freshfarm-onion-1kg", name: "Onion", brand: "FreshFarm", size: "1 kg", category: "vegetables", price_inr: 38, fulfilment: "amazon_now", keys: ["pyaaz", "pyaz", "onion"] },
  { sku: "freshfarm-tomato-1kg", name: "Tomato", brand: "FreshFarm", size: "1 kg", category: "vegetables", price_inr: 40, fulfilment: "amazon_now", keys: ["tamatar", "tomato"] },
  { sku: "freshfarm-ginger-100g", name: "Ginger", brand: "FreshFarm", size: "100 g", category: "vegetables", price_inr: 18, fulfilment: "amazon_now", keys: ["adrak", "ginger"] },
  { sku: "freshfarm-green-chilli-100g", name: "Green Chilli", brand: "FreshFarm", size: "100 g", category: "vegetables", price_inr: 12, fulfilment: "amazon_now", keys: ["mirchi", "chilli"] },
  { sku: "aashirvaad-shudh-chakki-atta-5kg", name: "Shudh Chakki Atta", brand: "Aashirvaad", size: "5 kg", category: "staples", price_inr: 289, fulfilment: "amazon_fresh", keys: ["atta", "aata"] },
  { sku: "tata-sampann-rajma-chitra-500g", name: "Rajma Chitra", brand: "Tata Sampann", size: "500 g", category: "staples", price_inr: 99, fulfilment: "amazon_now", keys: ["rajma"] },
  { sku: "india-gate-basmati-rice-classic-5kg", name: "Basmati Rice Classic", brand: "India Gate", size: "5 kg", category: "staples", price_inr: 699, fulfilment: "amazon_fresh", keys: ["chawal", "rice", "basmati"] },
  { sku: "tata-salt-iodised-1kg", name: "Iodised Salt", brand: "Tata Salt", size: "1 kg", category: "staples", price_inr: 28, fulfilment: "amazon_now", keys: ["namak", "salt"] },
  { sku: "surf-excel-easy-wash-1kg", name: "Easy Wash Detergent", brand: "Surf Excel", size: "1 kg", category: "cleaning", price_inr: 145, fulfilment: "amazon_now", keys: ["surf", "detergent"] },
  { sku: "red-bull-energy-drink-250ml", name: "Energy Drink", brand: "Red Bull", size: "250 ml", category: "energy_drinks", price_inr: 125, fulfilment: "amazon_now", keys: ["red bull", "redbull", "energy drink"] },
  { sku: "camlin-geometry-box-scholar-1pcs", name: "Geometry Box Scholar", brand: "Camlin", size: "1 pc", category: "stationery", price_inr: 120, fulfilment: "amazon_now", keys: ["geometry"] },
  { sku: "classmate-notebook-single-line-172p", name: "Notebook Single Line 172 pages", brand: "Classmate", size: "1 pc", category: "stationery", price_inr: 60, fulfilment: "amazon_now", keys: ["notebook", "copy"] },
  { sku: "lays-classic-salted-52g", name: "Classic Salted Chips", brand: "Lay's", size: "52 g", category: "snacks", price_inr: 20, fulfilment: "amazon_now", keys: ["chips", "lays"] },
  { sku: "maggi-2-minute-noodles-280g", name: "2-Minute Masala Noodles", brand: "Maggi", size: "280 g", category: "snacks", price_inr: 56, fulfilment: "amazon_now", keys: ["maggi", "noodles"] },
  { sku: "cadbury-dairy-milk-silk-60g", name: "Dairy Milk Silk", brand: "Cadbury", size: "60 g", category: "snacks", price_inr: 90, fulfilment: "amazon_now", keys: ["chocolate", "silk"] },
  { sku: "head-shoulders-shampoo-340ml", name: "Anti-Dandruff Shampoo", brand: "Head & Shoulders", size: "340 ml", category: "personal_care", price_inr: 365, fulfilment: "amazon_now", keys: ["shampoo"] },
];

const amazonUrl = (s: Sku) =>
  `https://www.amazon.in/s?k=${encodeURIComponent(`${s.brand} ${s.name} ${s.size}`).replace(/%20/g, "+")}`;

const BASE_RULES: Rule[] = [
  {
    id: "house-help-category-scope",
    title_en: "Didi can order staples, dairy, vegetables, fruits and cleaning items.",
    title_hinglish: "Didi ration, doodh, sabzi, phal aur safai ka saamaan order kar sakti hain.",
    source: "base",
    cedar: `@id("house-help-category-scope")
permit (principal, action == Action::"purchase_item", resource)
when {
  principal.role == "house_help" &&
  ["staples", "dairy", "vegetables", "fruits", "cleaning"].contains(resource.category)
};`,
  },
  {
    id: "teen-no-energy-drinks",
    title_en: "Energy drinks are not allowed for teens.",
    title_hinglish: "Energy drink bachchon ke liye mana hai.",
    source: "base",
    cedar: `@id("teen-no-energy-drinks")
forbid (principal, action == Action::"purchase_item", resource)
when { principal.role == "teen" && resource.category == "energy_drinks" };`,
  },
  {
    id: "teen-category-scope",
    title_en: "Teens can order stationery and snacks.",
    title_hinglish: "Bachche stationery aur snacks order kar sakte hain.",
    source: "base",
    cedar: `@id("teen-category-scope")
permit (principal, action == Action::"purchase_item", resource)
when {
  principal.role == "teen" &&
  ["stationery", "snacks"].contains(resource.category)
};`,
  },
  {
    id: "max-qty-per-line",
    title_en: "More than 5 units of one item needs the admin.",
    title_hinglish: "Ek item ke 5 se zyada units sirf Mom order kar sakti hain.",
    source: "base",
    cedar: `@id("max-qty-per-line")
forbid (principal, action == Action::"purchase_item", resource)
when { context.quantity > 5 }
unless { principal.role == "admin" };`,
  },
  {
    id: "approval-above-threshold",
    title_en: "Orders above Rs 1000 need admin approval.",
    title_hinglish: "Rs 1000 se upar ke order ke liye Mom ka approval chahiye.",
    source: "base",
    cedar: `@id("approval-above-threshold")
forbid (principal, action == Action::"auto_pay", resource)
when { context.order_total_inr > resource.approval_threshold_inr }
unless { principal.role == "admin" };`,
  },
  {
    id: "mandate-monthly-cap",
    title_en: "No order may exceed the monthly UPI AutoPay mandate of Rs 5000.",
    title_hinglish: "Is mahine ka UPI AutoPay limit paar nahi ho sakta.",
    source: "base",
    cedar: `@id("mandate-monthly-cap")
forbid (
  principal,
  action in [Action::"auto_pay", Action::"request_approval", Action::"approved_pay"],
  resource
)
when { context.month_spent_inr + context.order_total_inr > resource.monthly_cap_inr };`,
  },
  {
    id: "house-help-daily-cap",
    title_en: "Didi's orders are capped at Rs 500 per day.",
    title_hinglish: "Didi ke orders ki roz ki limit Rs 500 hai.",
    source: "base",
    cedar: `@id("house-help-daily-cap")
forbid (
  principal,
  action in [Action::"auto_pay", Action::"request_approval", Action::"approved_pay"],
  resource
)
when {
  principal.role == "house_help" &&
  context.member_spent_today_inr + context.order_total_inr > resource.house_help_daily_cap_inr
};`,
  },
];

const MEMBERS: (Member & { key: "mom" | "dad" | "didi" | "teen" })[] = [
  { key: "mom", id: "mom", name: "Sunita (Mom)", role: "admin", phone_masked: "+91 96••• ••404", limits_summary: "Admin. Approves orders above Rs 1,000. Any category." },
  { key: "dad", id: "dad", name: "Rajesh (Dad)", role: "adult", phone_masked: "+91 99••• ••002", limits_summary: "Any category. Orders above Rs 1,000 need Mom's approval." },
  { key: "didi", id: "didi", name: "Kamla Didi", role: "house_help", phone_masked: "+91 99••• ••003", limits_summary: "Staples, dairy, vegetables, fruits, cleaning. Rs 500 per day." },
  { key: "teen", id: "teen", name: "Aarav", role: "teen", phone_masked: "+91 99••• ••004", limits_summary: "Stationery and snacks only. No energy drinks." },
];

const CAP = 5000;
const APPROVAL_THRESHOLD = 1000;
const DIDI_DAILY_CAP = 500;

type State = {
  orders: Order[];
  events: AuditEvent[];
  rules: Rule[];
  seq: number;
};

let state: State | null = null;

function iso(minutesAgo: number) {
  return new Date(Date.now() - minutesAgo * 60_000).toISOString();
}

function upiRef() {
  let s = "SIM";
  for (let i = 0; i < 12; i++) s += Math.floor(Math.random() * 10);
  return s;
}

function sku(key: string) {
  const s = CATALOG.find((c) => c.sku === key || c.keys.includes(key));
  if (!s) throw new Error(`mock catalog missing ${key}`);
  return s;
}

// ---- Policy evaluation (a hand-written mirror of the Cedar rules above) ----

function evalItem(role: string, s: Sku, qty: number, rules: Rule[]): Pick<OrderItem, "decision" | "policy_ids" | "reason"> {
  if (qty > 5 && role !== "admin")
    return { decision: "deny", policy_ids: ["max-qty-per-line"], reason: "More than 5 units of one item needs the admin." };
  if (role === "house_help" && !["staples", "dairy", "vegetables", "fruits", "cleaning"].includes(s.category))
    return { decision: "deny", policy_ids: ["house-help-outside-scope"], reason: "House help cannot order items outside staples, dairy, vegetables, fruits and cleaning." };
  if (role === "teen" && s.category === "energy_drinks")
    return { decision: "deny", policy_ids: ["teen-no-energy-drinks"], reason: "Energy drinks are not allowed for teens." };
  if (role === "teen" && !["stationery", "snacks"].includes(s.category))
    return { decision: "deny", policy_ids: ["teen-outside-scope"], reason: "Teens can only order stationery and snacks." };
  for (const r of rules) {
    if (r.source !== "custom") continue;
    const m = r.cedar.match(/principal\.role == "(\w+)" && resource\.category == "(\w+)"/);
    if (m && m[1] === role && m[2] === s.category && r.cedar.includes("forbid"))
      return { decision: "deny", policy_ids: [r.id], reason: r.title_en };
  }
  const permit =
    role === "admin" || role === "adult" ? "adult-any-category" : role === "teen" ? "teen-category-scope" : "house-help-category-scope";
  return { decision: "allow", policy_ids: [permit], reason: "Allowed by household rules." };
}

function monthSpent(st: State) {
  return st.orders.reduce((sum, o) => sum + o.paid_inr, 0);
}

function didiSpentToday(st: State) {
  const today = new Date().toDateString();
  return st.orders
    .filter((o) => o.role === "house_help" && new Date(o.created_at).toDateString() === today)
    .reduce((sum, o) => sum + o.paid_inr, 0);
}

type Line = { key: string; qty: number };

function buildOrder(
  st: State,
  member: (typeof MEMBERS)[number],
  lines: Line[],
  channel: Order["channel"],
  input_type: Order["input_type"],
  createdAt: string,
  opts: { log?: boolean } = {},
): { order: Order; payment: { status: string; policy_ids: string[]; reason: string } } {
  const d = new Date(createdAt);
  const order_id = `JH-${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}-${String(++st.seq).padStart(4, "0")}`;
  const items: OrderItem[] = lines.map(({ key, qty }) => {
    const s = sku(key);
    return {
      sku: s.sku,
      name: `${s.name} ${s.size}`,
      brand: s.brand,
      qty,
      price_inr: s.price_inr,
      ...evalItem(member.role, s, qty, st.rules),
      amazon_search_url: amazonUrl(s),
      fulfilment: s.fulfilment,
    };
  });
  const total = items.reduce((sum, i) => sum + i.price_inr * i.qty, 0);
  const allowedTotal = items.filter((i) => i.decision === "allow").reduce((sum, i) => sum + i.price_inr * i.qty, 0);
  const anyDenied = items.some((i) => i.decision === "deny");

  let status: Order["status"];
  let payment: { status: string; policy_ids: string[]; reason: string };
  if (allowedTotal === 0) {
    status = "denied";
    payment = { status: "not_attempted", policy_ids: [], reason: "No line item was allowed." };
  } else if (monthSpent(st) + allowedTotal > CAP) {
    status = "denied";
    payment = { status: "blocked", policy_ids: ["mandate-monthly-cap"], reason: "This order would exceed the monthly UPI AutoPay mandate of Rs 5000." };
  } else if (member.role === "house_help" && didiSpentToday(st) + allowedTotal > DIDI_DAILY_CAP) {
    status = "denied";
    payment = { status: "blocked", policy_ids: ["house-help-daily-cap"], reason: "House help orders are capped at Rs 500 per day." };
  } else if (allowedTotal > APPROVAL_THRESHOLD && member.role !== "admin") {
    status = "pending_approval";
    payment = { status: "held", policy_ids: ["approval-above-threshold"], reason: "Orders above Rs 1000 need admin approval." };
  } else {
    status = anyDenied ? "partially_paid" : "paid";
    payment = { status: "captured", policy_ids: ["mandate-auto-pay"], reason: "Order is within the mandate and auto-pay limits." };
  }

  const order: Order = {
    order_id,
    member_name: member.name,
    role: member.role,
    created_at: createdAt,
    status,
    total_inr: total,
    paid_inr: status === "paid" || status === "partially_paid" ? allowedTotal : 0,
    upi_ref: status === "paid" || status === "partially_paid" ? upiRef() : null,
    items,
    channel,
    input_type,
  };
  st.orders.unshift(order);

  if (opts.log !== false) {
    const t0 = new Date(createdAt).getTime();
    const at = (s: number) => new Date(t0 + s * 1000).toISOString();
    const ev = (s: number, type: string, actor: string, summary: string, data?: unknown) =>
      st.events.unshift({ ts: at(s), order_id, type, actor, summary, data });
    const via = channel === "whatsapp" ? "WhatsApp" : "web console";
    ev(0, "message_received", member.name, `${input_type === "image" ? "Parchi photo" : input_type === "voice" ? "Voice note" : "Text"} received on ${via}`, { channel, input_type, member: member.key });
    if (input_type === "voice")
      ev(2, "voice_transcribed", "Amazon Transcribe", "Voice note transcribed (hi-IN)", { language: "hi-IN", transcript: lines.map((l) => `${sku(l.key).keys[0]} ${l.qty}`).join(", ") });
    if (input_type === "image")
      ev(3, "parchi_read", "Claude on Bedrock", `Read ${lines.length} lines from the handwritten parchi`, { lines: lines.map((l) => ({ text: sku(l.key).keys[0], qty: l.qty })) });
    ev(4, "items_extracted", "Claude on Bedrock", `Extracted ${lines.length} items`, { items: lines.map((l) => ({ query: sku(l.key).keys[0], quantity: l.qty })) });
    ev(5, "items_resolved", "catalog", `Resolved ${items.length} items to catalog SKUs`, { resolved: items.map((i) => ({ sku: i.sku, brand: i.brand, price_inr: i.price_inr })) });
    ev(6, "cart_built", "orchestrator", `Cart built, total Rs ${total}`, { order_id, total_inr: total, lines: items.length });
    ev(7, "policy_evaluated", "Cedar", `${items.filter((i) => i.decision === "allow").length} allowed, ${items.filter((i) => i.decision === "deny").length} denied`, {
      decisions: items.map((i) => ({ sku: i.sku, decision: i.decision, policy_ids: i.policy_ids, reason: i.reason })),
      payment_decision: payment,
    });
    if (status === "pending_approval") ev(8, "approval_requested", "orchestrator", "Asked Mom to approve on WhatsApp", { approver: "mom", total_inr: allowedTotal, policy_ids: payment.policy_ids });
    if (status === "denied") ev(8, "order_denied", "Cedar", payment.reason, { policy_ids: payment.policy_ids.length ? payment.policy_ids : items.flatMap((i) => i.policy_ids) });
    if (order.upi_ref)
      ev(9, "payment_captured", "UPI AutoPay (simulated)", `Rs ${order.paid_inr} debited from mandate`, { upi_ref: order.upi_ref, amount_inr: order.paid_inr, mandate_id: "MNDT-GUPTA-0001" });
    ev(10, "reply_sent", "Jhola", `Reply sent to ${member.name}`, { channel });
  }
  return { order, payment };
}

function seed(): State {
  const st: State = { orders: [], events: [], rules: [...BASE_RULES], seq: 0 };
  const m = (k: string) => MEMBERS.find((x) => x.key === k)!;
  buildOrder(st, m("mom"), [{ key: "aashirvaad-shudh-chakki-atta-5kg", qty: 1 }, { key: "tata-salt-iodised-1kg", qty: 1 }, { key: "surf-excel-easy-wash-1kg", qty: 2 }, { key: "india-gate-basmati-rice-classic-5kg", qty: 1 }], "whatsapp", "text", iso(60 * 26));
  buildOrder(st, m("didi"), [{ key: "shampoo", qty: 1 }], "whatsapp", "text", iso(60 * 20));
  buildOrder(st, m("didi"), [{ key: "doodh", qty: 2 }, { key: "dhaniya", qty: 1 }, { key: "aloo", qty: 1 }, { key: "tamatar", qty: 1 }, { key: "dahi", qty: 1 }], "whatsapp", "image", iso(95));
  buildOrder(st, m("teen"), [{ key: "red bull", qty: 4 }, { key: "geometry", qty: 1 }], "whatsapp", "text", iso(42));
  buildOrder(st, m("dad"), [{ key: "rajma", qty: 2 }, { key: "basmati", qty: 1 }, { key: "pyaaz", qty: 1 }, { key: "tamatar", qty: 1 }, { key: "adrak", qty: 1 }, { key: "mirchi", qty: 1 }, { key: "dahi", qty: 1 }], "whatsapp", "voice", iso(12));
  st.events.sort((a, b) => b.ts.localeCompare(a.ts));
  return st;
}

function s(): State {
  if (!state) state = seed();
  return state;
}

const delay = (ms = 350) => new Promise((r) => setTimeout(r, ms + Math.random() * 250));
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

// ---- Endpoint handlers ----

export async function mockHousehold(): Promise<HouseholdResponse> {
  await delay(200);
  const st = s();
  const used = monthSpent(st);
  const month = new Date().toLocaleString("en-IN", { month: "long", year: "numeric" });
  return clone({
    household: { name: "Gupta family" },
    members: MEMBERS.map((m) => ({ id: m.id, name: m.name, role: m.role, phone_masked: m.phone_masked, limits_summary: m.limits_summary })),
    rules: st.rules,
    mandate: { cap_inr: CAP, used_inr: used, remaining_inr: CAP - used, period: month },
  });
}

export async function mockOrders(limit = 20): Promise<{ orders: Order[] }> {
  await delay(200);
  return clone({ orders: s().orders.slice(0, limit) });
}

export async function mockAudit(orderId?: string, limit = 100): Promise<{ events: AuditEvent[] }> {
  await delay(200);
  const ev = s().events.filter((e) => !orderId || e.order_id === orderId);
  return clone({ events: ev.slice(0, limit) });
}

export async function mockApprovals(): Promise<{ pending: PendingApproval[] }> {
  await delay(150);
  return clone({
    pending: s()
      .orders.filter((o) => o.status === "pending_approval")
      .map((o) => ({ order_id: o.order_id, member_name: o.member_name, total_inr: o.total_inr, items_count: o.items.length, created_at: o.created_at })),
  });
}

export async function mockDecide(orderId: string, decision: "approve" | "reject"): Promise<Order> {
  await delay();
  const st = s();
  const o = st.orders.find((x) => x.order_id === orderId);
  if (!o) throw new Error(`Order ${orderId} not found`);
  if (o.status !== "pending_approval") throw new Error(`Order ${orderId} is not waiting for approval`);
  const now = new Date().toISOString();
  st.events.unshift({ ts: now, order_id: orderId, type: "approval_response", actor: "Sunita (Mom)", summary: decision === "approve" ? "Mom approved the order" : "Mom rejected the order", data: { decision, via: "web console" } });
  if (decision === "approve") {
    const allowed = o.items.filter((i) => i.decision === "allow").reduce((sum, i) => sum + i.price_inr * i.qty, 0);
    if (monthSpent(st) + allowed > CAP) {
      o.status = "denied";
      st.events.unshift({ ts: now, order_id: orderId, type: "order_denied", actor: "Cedar", summary: "Approved, but the monthly mandate cap would be exceeded", data: { policy_ids: ["mandate-monthly-cap"] } });
    } else {
      o.status = o.items.some((i) => i.decision === "deny") ? "partially_paid" : "paid";
      o.paid_inr = allowed;
      o.upi_ref = upiRef();
      st.events.unshift({ ts: now, order_id: orderId, type: "policy_evaluated", actor: "Cedar", summary: "approved_pay permitted", data: { action: "approved_pay", policy_ids: ["admin-approved-pay"] } });
      st.events.unshift({ ts: new Date(Date.now() + 1000).toISOString(), order_id: orderId, type: "payment_captured", actor: "UPI AutoPay (simulated)", summary: `Rs ${allowed} debited from mandate`, data: { upi_ref: o.upi_ref, amount_inr: allowed } });
    }
  } else {
    o.status = "rejected";
  }
  return clone(o);
}

const ALIASES: [RegExp, string][] = [
  [/red ?bull|energy drink/, "red bull"],
  [/doodh|milk/, "doodh"],
  [/dahi|curd/, "dahi"],
  [/dhaniya|coriander/, "dhaniya"],
  [/aloo|potato/, "aloo"],
  [/pyaa?z|onion/, "pyaaz"],
  [/tamatar|tomato/, "tamatar"],
  [/adrak|ginger/, "adrak"],
  [/mirchi|chilli/, "mirchi"],
  [/aa?tta/, "atta"],
  [/rajma/, "rajma"],
  [/chawal|rice|basmati/, "chawal"],
  [/namak|salt/, "namak"],
  [/surf|detergent/, "surf"],
  [/geometry/, "geometry"],
  [/notebook|copy/, "notebook"],
  [/chips|lays/, "chips"],
  [/maggi|noodles/, "maggi"],
  [/chocolate|silk/, "chocolate"],
  [/shampoo/, "shampoo"],
];

const NUMBER_WORDS: Record<string, number> = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, ek: 1, do: 2, teen: 3, char: 4, chaar: 4, paanch: 5 };

function parseLines(text: string): Line[] {
  const t = text.toLowerCase();
  const recipe = t.match(/rajma chawal(?: for (\d+))?/);
  if (recipe) {
    const n = Number(recipe[1] ?? 4);
    return [
      { key: "rajma", qty: Math.max(1, Math.ceil(n / 3)) },
      { key: "chawal", qty: 1 },
      { key: "pyaaz", qty: 1 },
      { key: "tamatar", qty: 1 },
      { key: "adrak", qty: 1 },
      { key: "mirchi", qty: 1 },
      { key: "dahi", qty: 1 },
    ];
  }
  const out: Line[] = [];
  for (const chunk of t.split(/,|\band\b|\n|\baur\b/)) {
    const hit = ALIASES.find(([re]) => re.test(chunk));
    if (!hit) continue;
    const num = chunk.match(/\b(\d+)\b(?!\s*(?:kg|g|ml|l)\b)/);
    const word = chunk.split(/\s+/).find((w) => NUMBER_WORDS[w]);
    const qty = num ? Number(num[1]) : word ? NUMBER_WORDS[word] : 1;
    const existing = out.find((l) => l.key === hit[1]);
    if (existing) existing.qty += qty;
    else out.push({ key: hit[1], qty: Math.max(1, Math.min(qty, 20)) });
  }
  return out;
}

const rs = (n: number) => `Rs ${n.toLocaleString("en-IN")}`;

export async function mockChat(req: ChatRequest): Promise<ChatResponse> {
  await delay(900);
  const st = s();
  const member = MEMBERS.find((m) => m.key === req.member) ?? MEMBERS[0];
  const text = (req.text ?? "").trim();

  if (member.key === "mom" && /^(approve|reject)\b/i.test(text)) {
    const pending = st.orders.find((o) => o.status === "pending_approval");
    if (!pending) return { reply_text: "Koi order approval ke liye pending nahi hai." };
    const o = await mockDecide(pending.order_id, /^approve/i.test(text) ? "approve" : "reject");
    return { reply_text: o.status === "rejected" ? `${o.order_id} reject kar diya.` : `${o.order_id} approve ho gaya. ${rs(o.paid_inr)} paid, UPI ref ${o.upi_ref}.`, order: o };
  }

  const lines = req.image_base64
    ? [{ key: "doodh", qty: 2 }, { key: "atta", qty: 1 }, { key: "aloo", qty: 1 }, { key: "pyaaz", qty: 1 }, { key: "dhaniya", qty: 1 }]
    : parseLines(text);
  if (!lines.length)
    return { reply_text: "Namaste! List bhejiye, jaise \"doodh 2, dhaniya, aloo 1 kg\", ya parchi ki photo." };

  const { order, payment } = buildOrder(st, member, lines, "web", req.image_base64 ? "image" : "text", new Date().toISOString());
  const allowed = order.items.filter((i) => i.decision === "allow");
  const denied = order.items.filter((i) => i.decision === "deny");
  const parts: string[] = [];
  if (req.image_base64) parts.push(`Parchi padh li. ${order.items.length} items mile.`);
  if (allowed.length) parts.push(`Cart: ${allowed.map((i) => `${i.brand} ${i.name} x${i.qty}`).join(", ")}.`);
  if (denied.length) parts.push(`Nahi kar sakte: ${denied.map((i) => `${i.brand} ${i.name} (${i.reason})`).join("; ")}`);
  if (order.status === "paid" || order.status === "partially_paid")
    parts.push(`${rs(order.paid_inr)} UPI AutoPay se paid. Ref ${order.upi_ref}.`);
  else if (order.status === "pending_approval")
    parts.push(`Total ${rs(allowed.reduce((a, i) => a + i.price_inr * i.qty, 0))} hai, Rs 1,000 se upar. Mom se approval maanga hai.`);
  else if (order.status === "denied") parts.push(`Order ruk gaya: ${payment.reason}`);

  return {
    reply_text: parts.join("\n"),
    buttons:
      order.status === "pending_approval"
        ? [
            { id: `approve:${order.order_id}`, title: "Approve" },
            { id: `reject:${order.order_id}`, title: "Reject" },
          ]
        : undefined,
    order: clone(order),
    decisions: order.items.map((i) => ({ sku: i.sku, decision: i.decision, policy_ids: i.policy_ids })),
  };
}

const ROLE_WORDS: [RegExp, string, string][] = [
  [/didi|maid|help/, "house_help", "Didi"],
  [/teen|aarav|kid|child|bachch/, "teen", "Aarav"],
  [/dad|papa|rajesh/, "adult", "Dad"],
];
const CATEGORY_WORDS: [RegExp, string][] = [
  [/grocer|ration|staple/, "staples"],
  [/snack|chips/, "snacks"],
  [/energy/, "energy_drinks"],
  [/stationery/, "stationery"],
  [/clean/, "cleaning"],
  [/dairy|milk/, "dairy"],
  [/vegetable|sabzi/, "vegetables"],
  [/personal|shampoo|cosmetic/, "personal_care"],
];

export async function mockDraftRule(text: string): Promise<RuleDraft> {
  await delay(1200);
  const t = text.toLowerCase();
  const role = ROLE_WORDS.find(([re]) => re.test(t));
  const amount = t.match(/(?:rs\.?|₹|inr)\s*(\d[\d,]*)|(\d[\d,]*)\s*(?:rs|rupees)/);
  const cat = CATEGORY_WORDS.find(([re]) => re.test(t));
  const weekend = /weekend|saturday|sunday/.test(t);

  if (!role) {
    return {
      cedar: `forbid (principal, action == Action::"auto_pay", resource)\nwhen { principal.role == ??? };`,
      explanation_en: "I could not tell which family member this rule is about.",
      explanation_hinglish: "Yeh rule kis ke liye hai, samajh nahi aaya.",
      validation: { ok: false, errors: ["Unknown member. Mention Didi, Aarav (teen) or Dad.", "Expected an expression after '==' at line 2."] },
      test_results: [],
    };
  }
  const [, roleName, who] = role;
  const cap = amount ? Number((amount[1] ?? amount[2]).replace(/,/g, "")) : null;
  const conds = [`principal.role == "${roleName}"`];
  if (weekend) conds.push(`context.is_weekend`);
  let cedar: string;
  let en: string;
  let hi: string;
  if (cap !== null) {
    conds.push(`context.order_total_inr > ${cap}`);
    cedar = `@id("custom-${roleName}-cap-${cap}")\n@reason("${who} can order up to Rs ${cap}${weekend ? " on weekends" : ""}.")\nforbid (\n  principal,\n  action in [Action::"auto_pay", Action::"request_approval"],\n  resource\n)\nwhen {\n  ${conds.join(" &&\n  ")}\n};`;
    if (cat) cedar += `\n\n@id("custom-${roleName}-only-${cat[1]}")\nforbid (principal, action == Action::"purchase_item", resource)\nwhen {\n  principal.role == "${roleName}" &&${weekend ? "\n  context.is_weekend &&" : ""}\n  resource.category != "${cat[1]}"\n};`;
    en = `Blocks any order from ${who} above Rs ${cap}${weekend ? " on Saturdays and Sundays" : ""}${cat ? `, and anything outside ${cat[1]}` : ""}.`;
    hi = `${who} ${weekend ? "weekend par " : ""}Rs ${cap} se zyada ka order nahi kar sakte${cat ? `, aur sirf ${cat[1]}` : ""}.`;
  } else if (cat) {
    cedar = `@id("custom-${roleName}-no-${cat[1]}")\n@reason("${who} cannot order ${cat[1]}.")\nforbid (principal, action == Action::"purchase_item", resource)\nwhen {\n  ${conds.join(" &&\n  ")} &&\n  resource.category == "${cat[1]}"\n};`;
    en = `Blocks ${who} from ordering anything in ${cat[1]}${weekend ? " on weekends" : ""}.`;
    hi = `${who} ${cat[1]} order nahi kar sakte${weekend ? " weekend par" : ""}.`;
  } else {
    return {
      cedar: `forbid (principal, action == Action::"purchase_item", resource)\nwhen { principal.role == "${roleName}" };`,
      explanation_en: `This would block every item for ${who}. Add an amount or a category to make it useful.`,
      explanation_hinglish: `Isse ${who} kuch bhi order nahi kar payenge. Amount ya category bataiye.`,
      validation: { ok: true, errors: [] },
      test_results: [{ case: `${who} orders milk`, expected: "deny", actual: "deny", pass: true }],
    };
  }
  const tests = [
    cap !== null
      ? { case: `${who} orders Rs ${cap + 150}${weekend ? " on Sunday" : ""}`, expected: "deny", actual: "deny", pass: true }
      : { case: `${who} orders ${cat![1]}`, expected: "deny", actual: "deny", pass: true },
    cap !== null
      ? { case: `${who} orders Rs ${Math.max(10, cap - 50)}${weekend ? " on Sunday" : ""}`, expected: "allow", actual: "allow", pass: true }
      : { case: `${who} orders something else`, expected: "allow", actual: "allow", pass: true },
    { case: "Mom orders the same cart", expected: "allow", actual: "allow", pass: true },
  ];
  if (weekend) tests.push({ case: `${who} orders Rs ${(cap ?? 200) + 150} on Wednesday`, expected: "allow", actual: "allow", pass: true });
  return { cedar, explanation_en: en, explanation_hinglish: hi, validation: { ok: true, errors: [] }, test_results: tests };
}

export async function mockActivateRule(cedar: string, title: string): Promise<{ ok: boolean; rule: Rule }> {
  await delay();
  const st = s();
  const idMatch = cedar.match(/@id\("([^"]+)"\)/);
  const rule: Rule = { id: idMatch?.[1] ?? `custom-${Date.now()}`, title_en: title, title_hinglish: title, cedar, source: "custom" };
  st.rules = [...st.rules.filter((r) => r.id !== rule.id), rule];
  st.events.unshift({ ts: new Date().toISOString(), order_id: null, type: "rule_activated", actor: "Sunita (Mom)", summary: `Rule ${rule.id} activated`, data: { id: rule.id, cedar } });
  return clone({ ok: true, rule });
}

export async function mockDeleteRule(id: string): Promise<{ ok: boolean }> {
  await delay();
  const st = s();
  const r = st.rules.find((x) => x.id === id);
  if (!r) throw new Error("Rule not found");
  if (r.source === "base") throw new Error("Base rules cannot be deleted");
  st.rules = st.rules.filter((x) => x.id !== id);
  st.events.unshift({ ts: new Date().toISOString(), order_id: null, type: "rule_deleted", actor: "Sunita (Mom)", summary: `Rule ${id} removed`, data: { id } });
  return { ok: true };
}

export async function mockRedteam(attack: AttackKind): Promise<RedteamResult> {
  await delay(1400);
  // Recorded from the real backend's sandboxed red-team run; timestamps refreshed.
  const res = clone(REDTEAM_SAMPLES[attack]) as unknown as RedteamResult;
  const t0 = Date.now();
  (res.audit as { ts: string }[]).forEach((a, i) => (a.ts = new Date(t0 + i * 40).toISOString()));
  return res;
}

export async function mockRefill(): Promise<{ ok: boolean; order?: Order }> {
  await delay();
  const st = s();
  const { order } = buildOrder(st, MEMBERS[0], [{ key: "doodh", qty: 4 }, { key: "atta", qty: 1 }], "whatsapp", "text", new Date().toISOString());
  return clone({ ok: true, order });
}

export async function mockReset(): Promise<{ ok: boolean }> {
  await delay();
  state = seed();
  return { ok: true };
}
