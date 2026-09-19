// Jhola API client. Talks to the real backend when NEXT_PUBLIC_JHOLA_API is set at build time,
// otherwise to the in-browser mock in ./mock.ts. Calls go through the /jhola-api rewrite
// (see next.config.ts) so the browser never needs CORS from the backend.

import * as mock from "./mock";
import type {
  AttackKind,
  AuditEvent,
  ChatRequest,
  ChatResponse,
  HouseholdResponse,
  Order,
  PendingApproval,
  RedteamResult,
  Rule,
  RuleDraft,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_JHOLA_API?.replace(/\/+$/, "") ?? "";
const DIRECT = process.env.NEXT_PUBLIC_JHOLA_DIRECT === "1";

export const IS_LIVE = API_BASE.length > 0;

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

// ---- Connection status (drives the "Live" indicator in the header) ----

type Conn = "unknown" | "up" | "down";
let conn: Conn = "unknown";
const listeners = new Set<() => void>();
function setConn(next: Conn) {
  if (next === conn) return;
  conn = next;
  listeners.forEach((l) => l());
}
export const connectionStore = {
  subscribe(l: () => void) {
    listeners.add(l);
    return () => listeners.delete(l);
  },
  get: () => conn,
  getServer: (): Conn => "unknown",
};

async function request<T>(path: string, init: RequestInit & { adminKey?: string } = {}): Promise<T> {
  const { adminKey, headers, ...rest } = init;
  const url = `${DIRECT ? API_BASE : "/jhola-api"}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      ...rest,
      headers: {
        ...(rest.body ? { "content-type": "application/json" } : {}),
        ...(adminKey ? { "x-jhola-demo-key": adminKey } : {}),
        ...headers,
      },
      cache: "no-store",
    });
  } catch {
    setConn("down");
    throw new ApiError("Could not reach the Jhola backend.", 0);
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    if (res.status >= 500 || res.status === 404) setConn(res.status >= 500 ? "down" : "up");
    else setConn("up");
    const msg =
      (body && typeof body === "object" && ("error" in body || "message" in body || "detail" in body)
        ? String((body as Record<string, unknown>).error ?? (body as Record<string, unknown>).message ?? (body as Record<string, unknown>).detail)
        : null) ?? (res.status === 401 || res.status === 403 ? "Admin key rejected." : `Request failed (${res.status}).`);
    throw new ApiError(msg, res.status);
  }
  setConn("up");
  return body as T;
}

function guard(adminKey: string | undefined) {
  if (!adminKey) throw new ApiError("Enter the admin key to do this.", 401);
}

const q = (params: Record<string, string | number | undefined>) => {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") sp.set(k, String(v));
  const str = sp.toString();
  return str ? `?${str}` : "";
};

export const api = {
  household(): Promise<HouseholdResponse> {
    return IS_LIVE ? request("/api/household") : mock.mockHousehold();
  },
  orders(limit = 20): Promise<{ orders: Order[] }> {
    return IS_LIVE ? request(`/api/orders${q({ limit })}`) : mock.mockOrders(limit);
  },
  audit(orderId?: string, limit = 100): Promise<{ events: AuditEvent[] }> {
    return IS_LIVE ? request(`/api/audit${q({ order_id: orderId, limit })}`) : mock.mockAudit(orderId, limit);
  },
  approvals(): Promise<{ pending: PendingApproval[] }> {
    return IS_LIVE ? request("/api/approvals") : mock.mockApprovals();
  },
  decide(orderId: string, decision: "approve" | "reject", adminKey?: string): Promise<Order> {
    guard(adminKey);
    return IS_LIVE
      ? request(`/api/approvals/${encodeURIComponent(orderId)}`, { method: "POST", body: JSON.stringify({ decision }), adminKey })
      : mock.mockDecide(orderId, decision);
  },
  chat(req: ChatRequest): Promise<ChatResponse> {
    return IS_LIVE ? request("/api/chat", { method: "POST", body: JSON.stringify(req) }) : mock.mockChat(req);
  },
  draftRule(text: string): Promise<RuleDraft> {
    return IS_LIVE ? request("/api/rules/draft", { method: "POST", body: JSON.stringify({ text }) }) : mock.mockDraftRule(text);
  },
  activateRule(cedar: string, title: string, adminKey?: string): Promise<{ ok: boolean; rule: Rule }> {
    guard(adminKey);
    return IS_LIVE
      ? request("/api/rules/activate", { method: "POST", body: JSON.stringify({ cedar, title }), adminKey })
      : mock.mockActivateRule(cedar, title);
  },
  deleteRule(id: string, adminKey?: string): Promise<unknown> {
    guard(adminKey);
    return IS_LIVE ? request(`/api/rules/${encodeURIComponent(id)}`, { method: "DELETE", adminKey }) : mock.mockDeleteRule(id);
  },
  redteam(attack: AttackKind): Promise<RedteamResult> {
    return IS_LIVE ? request("/api/redteam", { method: "POST", body: JSON.stringify({ attack }) }) : mock.mockRedteam(attack);
  },
  refill(adminKey?: string): Promise<unknown> {
    guard(adminKey);
    return IS_LIVE ? request("/api/refill/run", { method: "POST", adminKey }) : mock.mockRefill();
  },
  reset(adminKey?: string): Promise<unknown> {
    guard(adminKey);
    return IS_LIVE ? request("/api/demo/reset", { method: "POST", adminKey }) : mock.mockReset();
  },
};

export function errorMessage(e: unknown) {
  return e instanceof Error ? e.message : "Something went wrong.";
}
