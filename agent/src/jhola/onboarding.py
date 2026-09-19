"""WhatsApp onboarding for a phone number Jhola has never seen.

A short deterministic conversation (no LLM, so it is instant and cannot be talked into anything):
at most 3 questions, then a new household is created with this phone as its admin.

  1/3  name, and what to call the home
  2/3  monthly grocery budget for the SIMULATED UPI AutoPay mandate   (default Rs 5000)
  3/3  orders above which amount need the admin's approval            (default Rs 1000)

State lives in the global collection "onboarding" keyed by phone until the household exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .household import DEFAULT_BUDGET_INR, DEFAULT_THRESHOLD_INR, Directory
from .phones import mask_phone

PRIVACY_URL = "https://jhola-phi.vercel.app/privacy"
DEFAULT_BUTTON = "onb:default"
STOP_WORDS = {"stop", "cancel", "quit", "exit", "band karo", "nahi chahiye", "delete my data", "leave"}

WELCOME = (
    "Namaste! Main *Jhola* hoon, aapke ghar ka kirana assistant, yahin WhatsApp par.\n"
    "Setup mein bas 3 chhote sawaal hain. Hindi, Hinglish ya English, jaise aap chahein.\n"
    f"Privacy: sirf order chalane ke liye zaroori data rakha jaata hai. {PRIVACY_URL}\n\n"
    "*1/3* Aapka naam kya hai, aur ghar ko kya bulayein?\n"
    "(jaise: \"Priya, Sharma home\")"
)


@dataclass
class OnboardReply:
    text: str
    buttons: list[dict] = field(default_factory=list)
    household_id: str | None = None  # set when the household was just created


def parse_amount(text: str | None) -> int | None:
    """"5000", "Rs 5,000", "5k", "8 hazaar", "2.5k" -> rupees. None when there is no number."""
    t = (text or "").lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(k\b|hazaar|hazar|hajar|thousand|lakh|lac)?", t)
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2) or ""
    if unit in ("lakh", "lac"):
        n *= 100000
    elif unit:
        n *= 1000
    return int(n)


def parse_name(text: str | None) -> tuple[str, str]:
    """"I am Priya, Sharma home" -> ("Priya", "Sharma home"). Home defaults to "<name>'s home"."""
    t = re.sub(r"[^\w ,.'&-]", " ", (text or "").strip(), flags=re.U)
    t = re.sub(r"\s+", " ", t).strip(" .,-")
    parts = [p.strip() for p in re.split(r",|\band call (?:it|the home|home)\b|\baur ghar\b|\n", t, maxsplit=1, flags=re.I)]
    name = re.sub(r"^(hi|hello|hey|namaste|ji)\b[ ,]*", "", parts[0], flags=re.I)
    name = re.sub(r"^(my name is|myself|i am|i'm|im|this is|mera naam|mera name|main|naam)\b\s*", "", name, flags=re.I)
    name = re.sub(r"\s*\b(hai|hoon|hu|hun|here)$", "", name, flags=re.I).strip(" .,-")
    home = parts[1].strip(" .,-") if len(parts) > 1 else ""
    home = re.sub(r"^(ghar ko|call it|home is|ghar ka naam)\b\s*", "", home, flags=re.I)
    home = re.sub(r"\s*\b(bulao|bulayein|bolo)$", "", home, flags=re.I).strip()
    words = name.split()
    if not home and len(words) >= 2 and words[-1].lower() in ("family", "home", "ghar", "house", "parivar", "niwas"):
        home, name = name, " ".join(words[:-1])
    name = " ".join(w if w.isupper() else w.capitalize() for w in name.split()[:3])
    return name[:40], home[:60]


class Onboarding:
    def __init__(self, directory: Directory, audit=None) -> None:
        self.dir = directory
        self.repo = directory.repo
        self.audit = audit

    def in_progress(self, phone: str) -> bool:
        return self.repo.get("onboarding", phone) is not None

    def _log(self, event: str, phone: str, **data) -> None:
        if self.audit:
            self.audit.log(event, actor=mask_phone(phone), **data)

    def handle(self, phone: str, text: str | None, button_id: str | None = None) -> OnboardReply:
        st = self.repo.get("onboarding", phone)
        if st is None:
            self.repo.put("onboarding", phone, {"phone": phone, "step": "name",
                                                "started_at": self.dir.clock.now().isoformat()})
            self._log("onboarding_started", phone)
            return OnboardReply(WELCOME)
        said = (text or "").strip()
        if said.lower() in STOP_WORDS:
            self.repo.delete("onboarding", phone)
            self._log("onboarding_cancelled", phone)
            return OnboardReply("Theek hai, setup rok diya aur kuch save nahi kiya. Jab chahein \"hi\" bhejiye.")
        use_default = button_id == DEFAULT_BUTTON
        step = st["step"]
        if step == "name":
            name, home = parse_name(said)
            if not name or use_default:
                return OnboardReply("*1/3* Bas apna naam likh dijiye (jaise: \"Priya, Sharma home\").")
            st.update(step="budget", name=name, home=home)
            self.repo.put("onboarding", phone, st)
            return OnboardReply(
                f"Shukriya {name}!\n*2/3* Mahine ka grocery budget kitna rakhein? Yeh ek SIMULATED UPI AutoPay "
                f"limit hai, asli paisa nahi katega. Amount bhejiye (jaise 8000) ya default chuniye.",
                [{"id": DEFAULT_BUTTON, "title": f"Rs {DEFAULT_BUDGET_INR} theek hai"}])
        if step == "budget":
            amount = None if use_default else parse_amount(said)
            st.update(step="threshold", budget=min(max(amount or DEFAULT_BUDGET_INR, 100), 200000))
            self.repo.put("onboarding", phone, st)
            return OnboardReply(
                f"Budget Rs {st['budget']} per month.\n*3/3* Kitne rupaye se upar ke order par aapka approval "
                f"zaroori ho? Usse chhote order family ke log seedhe kar payenge.",
                [{"id": DEFAULT_BUTTON, "title": f"Rs {DEFAULT_THRESHOLD_INR} theek hai"}])
        amount = None if use_default else parse_amount(said)
        threshold = min(max(amount if amount is not None else DEFAULT_THRESHOLD_INR, 0), st.get("budget", DEFAULT_BUDGET_INR))
        hh = self.dir.create_household(phone, st.get("name", ""), st.get("home", ""),
                                       st.get("budget", DEFAULT_BUDGET_INR), threshold)
        self.repo.delete("onboarding", phone)
        self._log("onboarding_completed", phone, household_id=hh.id)
        return OnboardReply(ready_text(hh.name, hh.admins()[0].display, st.get("budget", DEFAULT_BUDGET_INR), threshold),
                            household_id=hh.id)


def ready_text(home: str, name: str, budget: int, threshold: int) -> str:
    return (
        f"*{home}* taiyaar hai, {name}. Aap admin hain: budget Rs {budget} a month, Rs {threshold} se upar ke "
        f"orders par aapka approval.\n"
        "1. List ki photo, voice note ya text bhejiye (\"2 doodh, atta, pyaaz\"). Main cart banata hoon aur aapke "
        "pasand ke brand yaad rakhta hoon.\n"
        "2. Family jodiye: \"Add Sunita didi 98765 43210, groceries only, 500 a day\".\n"
        "3. Rules seedhi bhasha mein: \"No energy drinks for Aarav\", \"Didi can spend 1500 this week\".\n"
        f"Payments SIMULATED hain, asli paisa nahi katta. Privacy: {PRIVACY_URL} "
        "(\"delete my data\" kabhi bhi bhej sakte hain)."
    )
