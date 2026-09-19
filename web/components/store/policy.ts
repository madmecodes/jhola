// Browser-side preview of the household Cedar policies (items.cedar and payments.cedar in the agent).
// It only drives the live preview in the storefront; checkout is decided by the Jhola agent.

export type Role = "admin" | "adult" | "house_help" | "teen";

export type LineDecision = { decision: "allow" | "deny"; policy_ids: string[]; reason: string };

const HOUSE_HELP = ["staples", "dairy", "vegetables", "fruits", "cleaning"];
const TEEN = ["stationery", "snacks"];

export function checkItem(role: Role, p: { category: string; seller_rating: number }, qty: number): LineDecision {
  const deny: LineDecision[] = [];
  if (qty > 5 && role !== "admin") deny.push({ decision: "deny", policy_ids: ["max-qty-per-line"], reason: "More than 5 units of one item needs the admin." });
  if (p.seller_rating < 4) deny.push({ decision: "deny", policy_ids: ["min-seller-rating"], reason: "Seller rating is below 4.0." });
  if (role === "house_help" && !HOUSE_HELP.includes(p.category))
    deny.push({ decision: "deny", policy_ids: ["house-help-outside-scope"], reason: "Didi can order staples, dairy, vegetables, fruits and cleaning only." });
  if (role === "teen" && p.category === "energy_drinks")
    deny.push({ decision: "deny", policy_ids: ["teen-no-energy-drinks"], reason: "Energy drinks are not allowed for teens." });
  else if (role === "teen" && !TEEN.includes(p.category))
    deny.push({ decision: "deny", policy_ids: ["teen-outside-scope"], reason: "Teens can only order stationery and snacks." });
  if (deny.length)
    return { decision: "deny", policy_ids: deny.flatMap((d) => d.policy_ids), reason: deny.map((d) => d.reason).join(" ") };
  const permit = role === "admin" || role === "adult" ? "adult-any-category" : role === "teen" ? "teen-category-scope" : "house-help-category-scope";
  return { decision: "allow", policy_ids: [permit], reason: "Allowed by household rules." };
}

export type PaymentCheck = {
  outcome: "auto_pay" | "needs_approval" | "blocked" | "empty";
  policy_ids: string[];
  reason: string;
};

export function checkPayment(
  role: Role,
  total: number,
  opts: { remaining_inr: number; approval_above_inr: number; house_help_daily_cap_inr: number },
): PaymentCheck {
  if (total <= 0) return { outcome: "empty", policy_ids: [], reason: "Nothing allowed in the cart yet." };
  const block: PaymentCheck[] = [];
  if (total > opts.remaining_inr)
    block.push({ outcome: "blocked", policy_ids: ["mandate-monthly-cap"], reason: "This order would exceed the monthly UPI AutoPay mandate." });
  if (role === "house_help" && total > opts.house_help_daily_cap_inr)
    block.push({ outcome: "blocked", policy_ids: ["house-help-daily-cap"], reason: `Didi's orders are capped at Rs ${opts.house_help_daily_cap_inr} per day.` });
  if (block.length) return { outcome: "blocked", policy_ids: block.flatMap((b) => b.policy_ids), reason: block.map((b) => b.reason).join(" ") };
  if (total > opts.approval_above_inr && role !== "admin")
    return { outcome: "needs_approval", policy_ids: ["approval-above-threshold"], reason: `Orders above Rs ${opts.approval_above_inr.toLocaleString("en-IN")} need Mom's approval.` };
  return { outcome: "auto_pay", policy_ids: ["mandate-auto-pay"], reason: "Within the mandate and auto-pay limits." };
}
