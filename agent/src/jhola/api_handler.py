"""Lambda entry point for the console API (API Gateway HTTP API, payload v2) and background jobs.

Events:
  HTTP API v2 request            -> route()           (routes under /api, see ROUTES)
  {"jhola_job": "web_job", ...}  -> run a deferred console job (chat, rules draft, refill)
  {"jhola_job": "weekly_refill"} -> EventBridge Scheduler, Sunday 09:00 IST

Env:
  JHOLA_TABLE, JHOLA_DEDUPE_TABLE, JHOLA_MEDIA_BUCKET, JHOLA_PHONE_NUMBER_ID, JHOLA_ADMIN_PHONE
  JHOLA_DEMO_KEY_PARAM   SSM SecureString holding the demo key (x-jhola-demo-key header)
  JHOLA_RATE_READ / JHOLA_RATE_WRITE   per-IP requests per minute (GETs / chat, draft, red team)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from typing import Any, Callable

from .api import ApiError, ConsoleApi, new_job_id
from .store import DynamoDBRepository, Repository

logging.getLogger().setLevel(logging.INFO)
for noisy in ("botocore", "boto3", "urllib3", "strands", "opentelemetry"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("jhola.api")

WAIT_S = 24.0  # measured from request arrival; API Gateway HTTP API integrations time out at 30 s
MAX_BODY = 6 * 1024 * 1024


# ---------- demo key ----------
_demo_key: str | None = None


def demo_key() -> str:
    global _demo_key
    if _demo_key is None:
        if os.environ.get("JHOLA_DEMO_KEY"):
            _demo_key = os.environ["JHOLA_DEMO_KEY"]
        else:
            import boto3

            _demo_key = boto3.client("ssm").get_parameter(
                Name=os.environ.get("JHOLA_DEMO_KEY_PARAM", "/jhola/demo-key"), WithDecryption=True
            )["Parameter"]["Value"]
    return _demo_key


def check_demo_key(headers: dict) -> None:
    given = headers.get("x-jhola-demo-key", "")
    if not given or not hmac.compare_digest(given.encode(), demo_key().encode()):
        raise ApiError(401, "missing or wrong x-jhola-demo-key")


# ---------- rate limit ----------
class RateLimiter:
    """Fixed one-minute window per IP and bucket. DynamoDB counter with TTL, or in memory locally."""

    def __init__(self, table_name: str | None = None) -> None:
        self.table = None
        self.mem: dict[str, int] = {}
        if table_name:
            import boto3

            self.table = boto3.resource("dynamodb").Table(table_name)

    def allow(self, bucket: str, ip: str, limit: int) -> bool:
        minute = int(time.time() // 60)
        key = f"rl#{bucket}#{ip}#{minute}"
        if self.table is None:
            self.mem[key] = self.mem.get(key, 0) + 1
            return self.mem[key] <= limit
        try:
            r = self.table.update_item(
                Key={"id": key}, UpdateExpression="ADD n :one SET expires_at = :exp",
                ExpressionAttributeValues={":one": 1, ":exp": (minute + 2) * 60}, ReturnValues="UPDATED_NEW")
            return int(r["Attributes"]["n"]) <= limit
        except Exception as e:  # noqa: BLE001  never fail closed on the limiter itself
            log.warning("rate_limit_error", extra={"error": str(e)})
            return True


# ---------- deferred jobs ----------
class LambdaDeferrer:
    """Stores the job, invokes this function asynchronously to run it, and waits up to WAIT_S."""

    def __init__(self, repo: Repository, function_name: str, bucket: str | None, started: float | None = None) -> None:
        self.repo = repo
        self.function_name = function_name
        self.bucket = bucket
        self.started = started or time.time()

    def run(self, kind: str, payload: dict) -> dict:
        import boto3

        jid = new_job_id()
        payload = dict(payload)
        if payload.get("image_base64") and self.bucket:  # DynamoDB items are capped at 400 KB
            key = f"inbound/web/{jid}"
            boto3.client("s3").put_object(Bucket=self.bucket, Key=key,
                                          Body=base64.b64decode(payload.pop("image_base64").split(",", 1)[-1]),
                                          ContentType=payload.get("media_type") or "image/jpeg")
            payload["image_s3_key"] = key
        self.repo.put("web_jobs", jid, {"job_id": jid, "kind": kind, "status": "running", "input": payload,
                                        "created_at": int(time.time())})
        boto3.client("lambda").invoke(FunctionName=self.function_name, InvocationType="Event",
                                      Payload=json.dumps({"jhola_job": "web_job", "job_id": jid}).encode())
        deadline = self.started + WAIT_S
        delay = 0.3
        while time.time() < deadline:
            time.sleep(delay)
            delay = min(delay * 1.3, 1.0)
            j = self.repo.get("web_jobs", jid)
            if j and j["status"] == "done":
                return {**j["result"], "job_id": jid}
            if j and j["status"] == "error":
                raise ApiError(j.get("http_status", 500), j.get("error", "job failed"))
        return {"pending": True, "job_id": jid, "reply_text": "Jhola is still working on this. "
                "Poll GET /api/jobs/" + jid + " for the result."}


def run_web_job(api: ConsoleApi, repo: Repository, job_id: str, bucket: str | None) -> dict:
    j = repo.get("web_jobs", job_id)
    if not j or j["status"] != "running":
        return {"skipped": job_id}
    payload = j["input"]
    if payload.get("image_s3_key") and bucket:
        import boto3

        body = boto3.client("s3").get_object(Bucket=bucket, Key=payload["image_s3_key"])["Body"].read()
        payload["image_base64"] = base64.b64encode(body).decode()
    t0 = time.time()
    try:
        result = api.execute_job(j["kind"], payload)
        j.update(status="done", result=result)
    except ApiError as e:
        j.update(status="error", error=e.message, http_status=e.status)
    except Exception as e:  # noqa: BLE001
        log.exception("job_failed", extra={"job_id": job_id, "kind": j["kind"]})
        j.update(status="error", error=f"{type(e).__name__}: {e}"[:500], http_status=500)
    j["input"] = {k: v for k, v in payload.items() if k != "image_base64"}
    j["duration_s"] = round(time.time() - t0, 2)
    repo.put("web_jobs", job_id, j)
    log.info("job_done", extra={"job_id": job_id, "kind": j["kind"], "status": j["status"],
                                "duration_s": j["duration_s"]})
    return {"job_id": job_id, "status": j["status"]}


# ---------- routing ----------
Route = tuple[str, re.Pattern, str, str]  # method, path regex, handler name, access
ROUTES: list[Route] = [
    ("GET", re.compile(r"^/api/household$"), "household", "read"),
    ("GET", re.compile(r"^/api/orders$"), "orders", "read"),
    ("GET", re.compile(r"^/api/audit$"), "audit", "read"),
    ("GET", re.compile(r"^/api/approvals$"), "approvals", "read"),
    ("GET", re.compile(r"^/api/jobs/(?P<id>[a-f0-9]{16})$"), "job", "read"),
    ("POST", re.compile(r"^/api/approvals/(?P<id>[A-Za-z0-9-]{1,40})$"), "decide", "key"),
    ("POST", re.compile(r"^/api/chat$"), "chat", "write"),
    ("POST", re.compile(r"^/api/rules/draft$"), "rules_draft", "write"),
    ("POST", re.compile(r"^/api/rules/activate$"), "rules_activate", "key"),
    ("DELETE", re.compile(r"^/api/rules/(?P<id>[A-Za-z0-9_-]{1,40})$"), "rules_delete", "key"),
    ("POST", re.compile(r"^/api/redteam$"), "redteam", "write"),
    ("POST", re.compile(r"^/api/refill/run$"), "refill_run", "key"),
    ("POST", re.compile(r"^/api/demo/reset$"), "demo_reset", "key"),
]


def _int(q: dict, name: str, default: int) -> int:
    try:
        return int(q.get(name, default))
    except (TypeError, ValueError):
        raise ApiError(400, f"{name} must be an integer")


def dispatch(api: ConsoleApi, method: str, path: str, query: dict, headers: dict, body: dict, ip: str,
             limiter: RateLimiter | None = None, key_check: Callable[[dict], None] = check_demo_key) -> dict:
    path = path.rstrip("/") or "/"
    allowed_methods = []
    for m, rx, name, access in ROUTES:
        match = rx.match(path)
        if not match:
            continue
        if m != method:
            allowed_methods.append(m)
            continue
        if access == "key":
            key_check(headers)
        elif limiter is not None:
            limit = int(os.environ.get("JHOLA_RATE_READ" if access == "read" else "JHOLA_RATE_WRITE",
                                       "120" if access == "read" else "20"))
            if not limiter.allow(access, ip, limit):
                raise ApiError(429, "rate limit exceeded, try again in a minute")
        rid = match.groupdict().get("id")
        if name == "orders":
            return api.orders(_int(query, "limit", 20))
        if name == "audit":
            return api.audit(query.get("order_id") or None, _int(query, "limit", 100))
        if name == "job":
            return api.job(rid)
        if name == "decide":
            return api.decide(rid, body)
        if name == "rules_delete":
            return api.rules_delete(rid)
        if name in ("chat",):
            return api.chat(body, client_id=hashlib.sha256(ip.encode()).hexdigest()[:16])
        if name in ("household", "approvals", "demo_reset"):
            return getattr(api, name)()
        return getattr(api, name)(body)
    if allowed_methods:
        raise ApiError(405, "method not allowed")
    raise ApiError(404, "not found")


# ---------- Lambda wiring ----------
_repo: DynamoDBRepository | None = None
_limiter: RateLimiter | None = None
_function_name = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "jhola-console-api")


def _sender(to: str, text: str, buttons: list[dict]) -> list[str]:
    from .whatsapp import AwsTransport, outbound_payloads

    t = AwsTransport(os.environ["JHOLA_PHONE_NUMBER_ID"], os.environ["JHOLA_MEDIA_BUCKET"])
    ids = []
    for p in outbound_payloads(to, text, buttons):
        ids.append(t.send(p))
        log.info("whatsapp_sent", extra={"type": p["type"], "message_id": ids[-1]})
    return ids


def _api(defer: bool = True, started: float | None = None) -> tuple[ConsoleApi, DynamoDBRepository]:
    global _repo, _limiter
    if _repo is None:
        _repo = DynamoDBRepository(os.environ["JHOLA_TABLE"])
        _limiter = RateLimiter(os.environ.get("JHOLA_DEDUPE_TABLE"))
    bucket = os.environ.get("JHOLA_MEDIA_BUCKET")
    deferrer = LambdaDeferrer(_repo, _function_name, bucket, started) if defer else None
    return ConsoleApi(_repo, deferrer=deferrer, sender=_sender), _repo


def respond(status: int, body: Any) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json", "cache-control": "no-store"},
            "body": json.dumps(body, ensure_ascii=False, default=str)}


def http(event: dict) -> dict:
    ctx = event.get("requestContext", {}).get("http", {})
    method, path, ip = ctx.get("method", "GET"), event.get("rawPath", "/"), ctx.get("sourceIp", "unknown")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    t0 = time.time()
    try:
        raw = event.get("body") or ""
        if event.get("isBase64Encoded") and raw:
            raw = base64.b64decode(raw).decode()
        if len(raw) > MAX_BODY:
            raise ApiError(413, "body too large")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            raise ApiError(400, "body must be JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "body must be a JSON object")
        api, _ = _api(started=t0)
        out = dispatch(api, method, path, event.get("queryStringParameters") or {}, headers, body, ip, _limiter)
        status = 202 if isinstance(out, dict) and out.get("pending") is True else 200
        resp = respond(status, out)
    except ApiError as e:
        status, resp = e.status, respond(e.status, {"error": e.message})
    except Exception as e:  # noqa: BLE001
        log.exception("api_failed", extra={"path": path})
        status, resp = 500, respond(500, {"error": f"internal error: {type(e).__name__}"})
    log.info("api_request", extra={"method": method, "path": path, "status": status,
                                   "ms": int((time.time() - t0) * 1000)})
    return resp


def handler(event: dict, context: Any = None) -> dict:
    global _function_name
    if context is not None and getattr(context, "function_name", None):
        _function_name = context.function_name
    job = event.get("jhola_job") if isinstance(event, dict) else None
    if job == "web_job":
        api, repo = _api(defer=False)
        return run_web_job(api, repo, event["job_id"], os.environ.get("JHOLA_MEDIA_BUCKET"))
    if job == "weekly_refill":
        api, _ = _api(defer=False)
        res = api.execute_job("refill", {"send": True})
        log.info("weekly_refill", extra={"sent": res.get("sent"), "skipped": res.get("skipped")})
        return {k: v for k, v in res.items() if k in ("sent", "skipped", "message_ids", "model")}
    return http(event)
