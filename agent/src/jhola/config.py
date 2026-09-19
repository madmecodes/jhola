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

# Infra account (WhatsApp webhook, DynamoDB later).
INFRA_PROFILE = os.environ.get("AWS_PROFILE", "ayush-aws-bits-hack")
INFRA_REGION = os.environ.get("JHOLA_INFRA_REGION", "ap-south-1")

ADMIN_PHONE = os.environ.get("JHOLA_ADMIN_PHONE", "+919999900001")


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
