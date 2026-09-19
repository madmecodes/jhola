// ---------- Payment policies (whole order, against the UPI AutoPay mandate) ----------
// The orchestrator asks, in order:
//   1. auto_pay         -> debit the mandate immediately
//   2. request_approval -> hold the order and ask the admin
//   3. otherwise deny with the forbid reasons.
// After the admin taps Approve, approved_pay is evaluated before any debit.

@id("mandate-auto-pay")
@reason("Order is within the mandate and auto-pay limits.")
@hinglish("Order limit ke andar hai, auto-pay ho gaya.")
permit (principal, action == Action::"auto_pay", resource);

@id("member-may-request-approval")
@reason("Any household member may ask the admin to approve an order.")
@hinglish("{admin} se approval maanga ja sakta hai.")
permit (principal, action == Action::"request_approval", resource);

@id("admin-approved-pay")
@reason("The admin approved this order.")
@hinglish("{admin} ne approve kar diya.")
permit (principal, action == Action::"approved_pay", resource)
when { context.approver_role == "admin" };

@id("approval-above-threshold")
@reason("Orders above Rs {threshold} need admin approval.")
@hinglish("Rs {threshold} se upar ke order ke liye {admin} ka approval chahiye.")
forbid (principal, action == Action::"auto_pay", resource)
when { context.order_total_inr > resource.approval_threshold_inr }
unless { principal.role == "admin" }
unless {
  principal has delegated_cap_inr && principal has delegated_until &&
  context.today <= principal.delegated_until &&
  context.member_spent_delegated_inr + context.order_total_inr <= principal.delegated_cap_inr
};

@id("member-daily-limit")
@reason("This order takes the member above their daily limit, so the admin must approve it.")
@hinglish("Aaj ki personal limit paar ho rahi hai, {admin} ka approval chahiye.")
forbid (principal, action == Action::"auto_pay", resource)
when {
  principal has daily_cap_inr &&
  context.member_spent_today_inr + context.order_total_inr > principal.daily_cap_inr
}
unless {
  principal has delegated_cap_inr && principal has delegated_until &&
  context.today <= principal.delegated_until &&
  context.member_spent_delegated_inr + context.order_total_inr <= principal.delegated_cap_inr
};

@id("member-order-limit")
@reason("This order is above the member's per-order limit, so the admin must approve it.")
@hinglish("Order personal limit se upar hai, {admin} ka approval chahiye.")
forbid (principal, action == Action::"auto_pay", resource)
when { principal has order_cap_inr && context.order_total_inr > principal.order_cap_inr }
unless {
  principal has delegated_cap_inr && principal has delegated_until &&
  context.today <= principal.delegated_until &&
  context.member_spent_delegated_inr + context.order_total_inr <= principal.delegated_cap_inr
};

@id("mandate-monthly-cap")
@reason("This order would exceed the monthly UPI AutoPay mandate of Rs {cap}.")
@hinglish("Is mahine ka UPI AutoPay limit khatam ho jayega.")
forbid (
  principal,
  action in [Action::"auto_pay", Action::"request_approval", Action::"approved_pay"],
  resource
)
when { context.month_spent_inr + context.order_total_inr > resource.monthly_cap_inr };

@id("house-help-daily-cap")
@reason("House help orders are capped at Rs {daily} per day.")
@hinglish("Didi ke orders ki roz ki limit Rs {daily} hai.")
forbid (
  principal,
  action in [Action::"auto_pay", Action::"request_approval", Action::"approved_pay"],
  resource
)
when {
  principal.role == "house_help" &&
  context.member_spent_today_inr + context.order_total_inr > resource.house_help_daily_cap_inr
}
unless { principal has daily_cap_inr }
unless {
  principal has delegated_cap_inr && principal has delegated_until &&
  context.today <= principal.delegated_until &&
  context.member_spent_delegated_inr + context.order_total_inr <= principal.delegated_cap_inr
};
