"""Configuration and clock."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
DATA_DIR = PKG_DIR / "data"
POLICY_DIR = PKG_DIR / "policies"
STATE_PATH = Path(os.environ.get("JHOLA_STATE_PATH", PKG_DIR.parents[1] / ".state" / "jhola.json"))

IST = timezone(timedelta(hours=5, minutes=30))

# Bedrock (LLM) account. Kept separate from the infra/WhatsApp account.
MODEL_ID = os.environ.get("JHOLA_MODEL_ID", "global.anthropic.claude-sonnet-5")
BEDROCK_PROFILE = os.environ.get("JHOLA_BEDROCK_PROFILE", "default")
BEDROCK_REGION = os.environ.get("JHOLA_BEDROCK_REGION", "us-east-1")
# Cross-account Bedrock: when set, assume this role (in the Bedrock account) with the ambient
# credentials (e.g. the Lambda execution role). Unset it once the infra account has Bedrock.
BEDROCK_ROLE_ARN = os.environ.get("JHOLA_BEDROCK_ROLE_ARN", "")

# Infra account (WhatsApp webhook, DynamoDB later).
INFRA_PROFILE = os.environ.get("AWS_PROFILE", "ayush-aws-bits-hack")
INFRA_REGION = os.environ.get("JHOLA_INFRA_REGION", "ap-south-1")

# Demo household (Gupta family): the phone that plays Mom, its admin.
ADMIN_PHONE = os.environ.get("JHOLA_ADMIN_PHONE", "+919999900001")

# "off": ask Bedrock to skip extended thinking (about half the latency). "default": model default.
THINKING = os.environ.get("JHOLA_THINKING", "off").lower()

_bedrock_session = None
_bedrock_session_at = 0.0


def bedrock_session():
    """boto3 Session for Bedrock: assumed cross-account role, named profile, or ambient credentials.

    Assumed-role credentials are refreshed every 45 minutes (they last 1 hour).
    """
    global _bedrock_session, _bedrock_session_at
    import time

    import boto3

    if _bedrock_session is not None and time.time() - _bedrock_session_at < 45 * 60:
        return _bedrock_session
    if BEDROCK_ROLE_ARN:
        creds = boto3.client("sts").assume_role(
            RoleArn=BEDROCK_ROLE_ARN, RoleSessionName="jhola-agent", DurationSeconds=3600
        )["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"], aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"], region_name=BEDROCK_REGION,
        )
    elif BEDROCK_PROFILE:
        session = boto3.Session(profile_name=BEDROCK_PROFILE, region_name=BEDROCK_REGION)
    else:
        session = boto3.Session(region_name=BEDROCK_REGION)
    _bedrock_session, _bedrock_session_at = session, time.time()
    return session


class Clock:
    """Wall clock in IST, optionally frozen (scenarios and tests freeze it)."""

    def __init__(self, frozen: datetime | None = None) -> None:
        self.frozen = frozen

    def now(self) -> datetime:
        return self.frozen or datetime.now(IST)

    def today(self):
        return self.now().date()

    def advance(self, **kw) -> None:
        if self.frozen:
            self.frozen = self.frozen + timedelta(**kw)


DEMO_NOW = datetime(2026, 9, 20, 10, 0, tzinfo=IST)  # Sunday
