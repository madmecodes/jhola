"""Phone number helpers: E.164 normalization (default country India, +91) and masking."""

from __future__ import annotations

import json
import re
from typing import Any

PHONE_RE = re.compile(r"\+?\d{10,13}")
PHONE_IN_TEXT_RE = re.compile(r"(?<![\w.])\+?\d[\d \-()]{8,16}\d(?![\w])")


def to_e164(p: str | None, default_cc: str = "91") -> str:
    """"98765 43210", "09876543210", "+91 98765-43210", "919876543210" -> "+919876543210".

    Numbers written with a + keep their country code. Anything shorter than 10 digits is returned
    as +<digits> (never matches a real member).
    """
    raw = (p or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return f"+{digits}"
    if digits.startswith("00"):
        return f"+{digits[2:]}"
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"+{default_cc}{digits}"
    return f"+{digits}"


def valid_mobile(e164: str) -> bool:
    """A plausible mobile number: Indian numbers are +91 and 10 digits starting 6-9."""
    if e164.startswith("+91"):
        return bool(re.fullmatch(r"\+91[6-9]\d{9}", e164))
    return bool(re.fullmatch(r"\+\d{8,15}", e164))


def mask_phone(p: str | None) -> str:
    digits = re.sub(r"\D", "", p or "")
    if len(digits) < 6:
        return ""
    return f"+{digits[:2]}******{digits[-4:]}"


def mask_phones(obj: Any) -> Any:
    """Mask phone numbers anywhere in a JSON-able value (audit events carry sender phones)."""
    return json.loads(PHONE_RE.sub(lambda m: mask_phone(m.group(0)), json.dumps(obj, ensure_ascii=False)))


def mask_in_text(text: str) -> str:
    return PHONE_IN_TEXT_RE.sub(lambda m: mask_phone(m.group(0)) or m.group(0), text or "")
