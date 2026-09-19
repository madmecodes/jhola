"""AWS Lambda entry point: SNS (WhatsApp events) -> WhatsAppChannel -> Jhola agent.

Env:
  JHOLA_TABLE            DynamoDB state table (pk=collection, sk=key)
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
from .whatsapp import AwsTransport, DynamoDedupe, WhatsAppChannel, parse_sns_event

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
    repo, transport, dedupe = _deps()
    channel = WhatsAppChannel(repo, transport, dedupe, lambda: JholaAgent(Jhola(repo)))
    msgs = parse_sns_event(event)
    log.info("event_received", extra={"messages": len(msgs)})
    for m in msgs:
        channel.handle(m)
    return {"processed": len(msgs), "sent": channel.sent}
