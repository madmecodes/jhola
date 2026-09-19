"""AWS Lambda entry point: SNS (WhatsApp events) -> WhatsAppChannel -> Jhola agent.

Env:
  JHOLA_TABLE            DynamoDB state table (pk=collection or hh#<household_id>#collection, sk=key)
  JHOLA_DEDUPE_TABLE     DynamoDB table of processed WhatsApp message ids (TTL)
  JHOLA_MEDIA_BUCKET     S3 bucket for inbound media
  JHOLA_PHONE_NUMBER_ID  origination phone number id (phone-number-id-...)
  JHOLA_BEDROCK_ROLE_ARN cross-account Bedrock role to assume (unset to use this account)
"""

from __future__ import annotations

import logging
import os

from .agent import JholaAgent
from .orders import Jhola
from .store import DynamoDBRepository
from .phones import mask_phones
from .whatsapp import AwsTransport, DryRunTransport, DynamoDedupe, WhatsAppChannel, parse_sns_event

logging.getLogger().setLevel(logging.INFO)
for noisy in ("botocore", "boto3", "urllib3", "strands", "opentelemetry"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("jhola.lambda")

_repo: DynamoDBRepository | None = None
_transport: AwsTransport | None = None
_dedupe: DynamoDedupe | None = None


def _deps():
    global _repo, _transport, _dedupe
    if _repo is None:
        _repo = DynamoDBRepository(os.environ["JHOLA_TABLE"])
        _transport = AwsTransport(os.environ["JHOLA_PHONE_NUMBER_ID"], os.environ["JHOLA_MEDIA_BUCKET"])
        _dedupe = DynamoDedupe(os.environ["JHOLA_DEDUPE_TABLE"])
    return _repo, _transport, _dedupe


def handler(event, context):
    """SNS event from End User Messaging Social. A direct invocation (needs lambda:InvokeFunction) may add
    "jhola_dry_run": true to run the full pipeline against the real table WITHOUT sending any WhatsApp
    message; the outbound payloads come back in the response with phone numbers masked."""
    repo, transport, dedupe = _deps()
    dry = DryRunTransport() if isinstance(event, dict) and event.get("jhola_dry_run") is True else None
    transport = dry or transport
    channel = WhatsAppChannel(repo, transport, dedupe, lambda hid: JholaAgent(Jhola(repo, household_id=hid)))
    msgs = parse_sns_event(event)
    log.info("event_received", extra={"messages": len(msgs)})
    for m in msgs:
        channel.handle(m)
    out = {"processed": len(msgs), "sent": channel.sent}
    if dry is not None:
        out["dry_run_outbound"] = mask_phones(dry.payloads)
    return out
