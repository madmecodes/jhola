"""Catalog, household memory, item resolution, pantry, recipes and refill prediction.

Pure Python, no network. Everything here is deterministic and unit-testable.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import config
from .config import DATA_DIR
from .store import Repository

DEMO_HOUSEHOLD_ID = "demo-gupta"
ROLES = ("admin", "adult", "house_help", "teen", "elder")
CATEGORIES = ("staples", "dairy", "vegetables", "fruits", "snacks", "beverages", "energy_drinks", "stationery",
              "personal_care", "cleaning", "pooja")
GROCERIES = ("staples", "dairy", "vegetables", "fruits")

MIN_RATING = 4.0
QTY_WORDS = {"kg", "g", "gm", "gram", "grams", "l", "ltr", "litre", "ml", "packet", "packets", "pkt",
             "pcs", "piece", "pieces", "x", "half", "dozen", "ek", "do", "teen", "char"}
INJECTION_PATTERNS = re.compile(
    r"(system note|ignore (all|previous)|to assistant|pre-approved|add \d+ units)", re.I
)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def to_base(amount: float, unit: str) -> tuple[float, str]:
    unit = unit.lower()
    if unit == "kg":
        return amount * 1000, "g"
    if unit == "l":
        return amount * 1000, "ml"
    return amount, unit


class Catalog:
    def __init__(self, items: list[dict]) -> None:
        self.items = items
        self.by_id = {i["id"]: i for i in items}

    @classmethod
    def load(cls, path: Path = DATA_DIR / "catalog.json") -> "Catalog":
        return cls(json.loads(path.read_text()))

    def get(self, sku: str) -> dict | None:
        return self.by_id.get(sku)

    def search(self, query: str, category: str | None = None, limit: int = 8) -> list[dict]:
        return [it for _, _, it in self.search_scored(query, category, limit)]

    def search_scored(self, query: str, category: str | None = None, limit: int = 8) -> list[tuple]:
        """(score, relevance, item), best first. relevance ignores stock and seller rating."""
        words = [w for w in _norm(query).split() if w]
        scored = []
        for it in self.items:
            if category and it["category"] != category:
                continue
            hay_tags = set(it["tags"])
            aliases = it.get("aliases", [])
            alias_words = {w for a in aliases for w in _norm(a).split()}
            alias_phrases = {_norm(a) for a in aliases}
            hay = _norm(f"{it['brand']} {it['name']} {' '.join(it['tags'])}")
            hay_words = hay.split()
            score = 3 if _norm(query) in alias_phrases else 0
            for w in words:
                if w in hay_tags:
                    score += 3
                elif w in alias_words:
                    score += 2.5
                elif w in hay_words:
                    score += 2
                elif w in hay:
                    score += 1
            if score:
                # A processed form (powder) the member did not ask for ranks below the fresh item:
                # "kothmir" / "dhaniya" mean coriander leaves, "dhaniya powder" means the powder.
                if "powder" in hay_tags and "powder" not in words:
                    score -= 0.5
                rel = score
                score += 0.5 if it["in_stock"] else 0
                score += it["seller_rating"] / 10
                scored.append((score, rel, it))
        scored.sort(key=lambda t: -t[0])
        return scored[:limit]


def describe(it: dict) -> str:
    return f"{it['brand']} {it['name']} {it['pack_size']}{it['unit']} (Rs {it['price_inr']})"


def suspicious(text: str) -> bool:
    return bool(INJECTION_PATTERNS.search(text or ""))


def pref_key(query: str) -> str:
    """Generic word a preference is stored under: "2 kg Atta" -> "atta"."""
    return " ".join(w for w in _norm(query).split() if w not in QTY_WORDS and not w.isdigit())


@dataclass
class Member:
    id: str
    name: str
    display: str
    role: str
    phone: str
    language: str
    # Personal limits (per-member memory). None / empty means "the role template applies".
    daily_cap_inr: int | None = None        # above this per day the admin must approve
    order_cap_inr: int | None = None        # above this per order the admin must approve
    allowed_categories: list[str] = field(default_factory=list)
    welcomed: bool = True
    # Active temporary delegation (filled by Jhola from the rules collection), enforced by Cedar
    # through context.today: {"cap_inr", "starts_on", "until"}.
    delegation: dict | None = None

    @classmethod
    def from_doc(cls, m: dict) -> "Member":
        phone = config.ADMIN_PHONE if m.get("phone") == "ADMIN_PHONE_PLACEHOLDER" else m.get("phone", "")
        return cls(m["id"], m["name"], m.get("display") or m["name"], m["role"], phone,
                   m.get("language", "hinglish"), m.get("daily_cap_inr"), m.get("order_cap_inr"),
                   list(m.get("allowed_categories") or []), bool(m.get("welcomed", True)))

    def to_doc(self) -> dict:
        return {"id": self.id, "name": self.name, "display": self.display, "role": self.role, "phone": self.phone,
                "language": self.language, "daily_cap_inr": self.daily_cap_inr, "order_cap_inr": self.order_cap_inr,
                "allowed_categories": self.allowed_categories, "welcomed": self.welcomed}


def demo_household_raw() -> dict:
    raw = json.loads((DATA_DIR / "household.json").read_text())
    raw["household_id"] = DEMO_HOUSEHOLD_ID
    raw["demo"] = True
    return raw


class Household:
    """One household: profile, members, mandate settings and learned preferences.

    raw: {household_id, name, city?, demo?, members[], mandate{}, preferences{}, purchase_history[]?}
    repo: the household's scoped repository (purchases and learned preferences are written there).
    """

    def __init__(self, raw: dict, repo: Repository) -> None:
        self.raw = raw
        self.repo = repo
        self.id = raw["household_id"]
        self.name = raw["name"]
        self.demo = bool(raw.get("demo"))
        self.members = [Member.from_doc(m) for m in raw["members"]]
        self.mandate = raw["mandate"]
        self.preferences: dict[str, dict] = dict(raw.get("preferences") or {})

    @classmethod
    def load(cls, repo: Repository, path: Path | None = None) -> "Household":
        """The seeded demo household (Gupta family) straight from the data file."""
        raw = json.loads(path.read_text()) if path else demo_household_raw()
        return cls(raw, repo)

    def member_by_phone(self, phone: str) -> Member | None:
        p = re.sub(r"[^0-9+]", "", phone or "")
        if not p.lstrip("+"):
            return None
        for m in self.members:
            if m.phone and (m.phone == p or m.phone.lstrip("+") == p.lstrip("+")):
                return m
        return None

    def member(self, member_id: str) -> Member:
        m = self.find(member_id)
        if m is None:
            raise KeyError(f"no member {member_id}")
        return m

    def find(self, member_id: str) -> Member | None:
        return next((m for m in self.members if m.id == member_id), None)

    def find_by_name(self, ref: str) -> Member | None:
        """Member by id, display name or (part of the) name, case-insensitive."""
        r = _norm(ref or "")
        if not r:
            return None
        for m in self.members:
            if r in (m.id, _norm(m.display), _norm(m.name)):
                return m
        hits = [m for m in self.members if r in _norm(m.name).split() or r in _norm(m.display).split()
                or _norm(m.name).startswith(r)]
        return hits[0] if len(hits) == 1 else None

    def display_of(self, member_id: str) -> str:
        m = self.find(member_id)
        return m.display if m else member_id

    def admins(self) -> list[Member]:
        return [m for m in self.members if m.role == "admin"]

    def admin_label(self) -> str:
        a = self.admins()
        return a[0].display if a else "the admin"

    def history(self) -> list[dict]:
        recorded = self.repo.list("purchases")
        return sorted(self.raw.get("purchase_history", []) + recorded, key=lambda r: r["date"])

    def record_purchase(self, when: date, sku: str, qty: int, by: str, order_id: str) -> None:
        key = f"{order_id}:{sku}"
        self.repo.put("purchases", key, {"date": when.isoformat(), "sku": sku, "qty": qty, "by": by})

    # ---------- learned usual brands (household memory) ----------
    def learn_preference(self, word: str, sku: str, qty: int = 1, source: str = "choice", by: str = "",
                         at: str = "") -> dict | None:
        """Remember "<generic word> means this product for us". An explicit choice always wins;
        a preference inferred from a paid order never overwrites an explicit choice."""
        key = pref_key(word)
        if not key or len(key) > 60:
            return None
        old = self.preferences.get(key)
        if old and source == "order" and (old.get("source", "choice") != "order" or old.get("sku") == sku):
            return None
        doc = {"word": key, "sku": sku, "qty": max(1, int(qty or 1)), "source": source, "by": by, "at": at}
        self.preferences[key] = doc
        self.repo.put("prefs", key, doc)
        return doc


class Resolver:
    """Turns a free-text item ("atta", "doodh 2 packet", "rajma 750 g") into a SKU."""

    def __init__(self, catalog: Catalog, household: Household) -> None:
        self.catalog = catalog
        self.hh = household

    def _pref(self, query: str) -> tuple[str, dict] | None:
        q = pref_key(query)
        return (q, self.hh.preferences[q]) if q in self.hh.preferences else None

    def _default(self, query: str) -> dict | None:
        """No household preference yet: among the most relevant matches pick a sensible default,
        in stock, well rated and mid-priced (neither the cheapest nor the premium pack)."""
        scored = self.catalog.search_scored(query, limit=12)
        if not scored:
            return None
        top = max(rel for _, rel, _ in scored)
        band = [it for _, rel, it in scored if rel >= top - 0.5]
        ok = [it for it in band if self._ok(it)]
        if not ok:
            return scored[0][2]
        prices = sorted(it["price_inr"] for it in ok)
        median = prices[len(prices) // 2]
        if len(ok) >= 3:
            lo, hi = prices[len(prices) // 3], prices[-(len(prices) // 3) - 1]
            ok = [it for it in ok if lo <= it["price_inr"] <= hi] or ok
        return sorted(ok, key=lambda it: (-it["seller_rating"], abs(it["price_inr"] - median), it["id"]))[0]

    def _ok(self, it: dict) -> bool:
        return it["in_stock"] and it["seller_rating"] >= MIN_RATING

    def _substitute(self, base: dict) -> dict | None:
        """Same brand first, then same category + overlapping tags; prefer closest pack size."""
        cands = [
            it
            for it in self.catalog.items
            if it["id"] != base["id"]
            and it["category"] == base["category"]
            and set(it["tags"]) & set(base["tags"][:2])
            and self._ok(it)
        ]
        if not cands:
            return None
        bsize, bunit = to_base(base["pack_size"], base["unit"])

        def key(it):
            size, unit = to_base(it["pack_size"], it["unit"])
            return (
                0 if it["brand"] == base["brand"] else 1,
                0 if unit == bunit else 1,
                abs(size - bsize),
                -it["seller_rating"],
            )

        return sorted(cands, key=key)[0]

    def resolve(
        self, query: str, quantity: int | None = None, amount: float | None = None, unit: str | None = None
    ) -> dict:
        note = []
        pref = self._pref(query)
        source = "preference"
        if pref:
            alias, p = pref
            item = self.catalog.get(p["sku"])
            default_qty = p.get("qty", 1)
            if item is None:  # the remembered product left the catalog
                pref, item, default_qty, source = None, self._default(query), 1, "search"
                if item is None:
                    return {"query": query, "resolved": False, "reason": "no matching product"}
        else:
            item = self._default(query)
            if item is None:
                return {"query": query, "resolved": False, "reason": "no matching product"}
            default_qty = 1
            source = "search"
        if not self._ok(item):
            why = "out of stock" if not item["in_stock"] else f"seller rating {item['seller_rating']}"
            sub = self._substitute(item)
            if not sub:
                return {"query": query, "resolved": False, "reason": f"{describe(item)} is {why}, no substitute"}
            note.append(f"{describe(item)} is {why}; substituted {describe(sub)}")
            item = sub
            source += "+substitute"
        qty = quantity or default_qty
        if amount and unit:
            need, nunit = to_base(amount, unit)
            size, sunit = to_base(item["pack_size"], item["unit"])
            if nunit == sunit and size:
                qty = max(1, math.ceil(need / size - 1e-9))
        return {
            "query": query,
            "resolved": True,
            "sku": item["id"],
            "label": describe(item),
            "category": item["category"],
            "qty": int(qty),
            "unit_price_inr": item["price_inr"],
            "source": source,
            "note": "; ".join(note),
        }


class Pantry:
    """Estimates what is still at home from purchase history."""

    DEFAULT_DAYS = {"staples": 30, "dairy": 3, "vegetables": 7, "fruits": 5, "snacks": 10, "cleaning": 30}

    def __init__(self, catalog: Catalog, household: Household) -> None:
        self.catalog = catalog
        self.hh = household

    def _by_sku(self) -> dict[str, list[date]]:
        out: dict[str, list[date]] = {}
        for r in self.hh.history():
            out.setdefault(r["sku"], []).append(date.fromisoformat(r["date"]))
        return out

    def cycle_days(self, sku: str, dates: list[date]) -> float:
        ds = sorted(set(dates))
        if len(ds) >= 2:
            gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
            return sum(gaps) / len(gaps)
        it = self.catalog.get(sku) or {"category": "staples"}
        return self.DEFAULT_DAYS.get(it["category"], 14)

    def status(self, sku: str, today: date) -> dict:
        dates = self._by_sku().get(sku)
        if not dates:
            return {"sku": sku, "in_pantry": False, "reason": "never bought"}
        last = max(dates)
        cycle = self.cycle_days(sku, dates)
        runs_out = last + timedelta(days=round(cycle))
        return {
            "sku": sku,
            "in_pantry": runs_out > today + timedelta(days=1),
            "last_bought": last.isoformat(),
            "cycle_days": round(cycle, 1),
            "expected_run_out": runs_out.isoformat(),
        }

    def status_for_query(self, query: str, resolver: Resolver, today: date) -> dict:
        """Pantry check by alias: looks at every SKU sharing the resolved item's tags."""
        r = resolver.resolve(query)
        if not r.get("resolved"):
            return {"query": query, "in_pantry": False, "reason": "unknown item"}
        base = self.catalog.get(r["sku"])
        related = [it["id"] for it in self.catalog.items if set(it["tags"][:2]) & set(base["tags"][:2])
                   and it["category"] == base["category"]]
        best = None
        for sku in related:
            s = self.status(sku, today)
            if s.get("in_pantry"):
                best = s
                break
            if best is None and s.get("last_bought"):
                best = s
        best = best or {"sku": r["sku"], "in_pantry": False, "reason": "never bought"}
        best["query"] = query
        return best

    def predict_refill(self, today: date, horizon_days: int = 2) -> list[dict]:
        out = []
        for sku, dates in self._by_sku().items():
            if len(set(dates)) < 2:
                continue
            s = self.status(sku, today)
            runs_out = date.fromisoformat(s["expected_run_out"])
            if runs_out <= today + timedelta(days=horizon_days):
                qtys = [r["qty"] for r in self.hh.history() if r["sku"] == sku]
                it = self.catalog.get(sku)
                out.append(
                    {
                        "sku": sku,
                        "label": describe(it),
                        "qty": round(sum(qtys) / len(qtys)),
                        "last_bought": s["last_bought"],
                        "cycle_days": s["cycle_days"],
                        "due": runs_out.isoformat(),
                    }
                )
        return sorted(out, key=lambda r: r["due"])


class Recipes:
    def __init__(self, raw: dict) -> None:
        self.raw = raw

    @classmethod
    def load(cls, path: Path = DATA_DIR / "recipes.json") -> "Recipes":
        return cls(json.loads(path.read_text()))

    def find(self, dish: str) -> tuple[str, dict] | None:
        d = _norm(dish)
        for name, r in self.raw.items():
            if any(a in d or d in a for a in r["aliases"]):
                return name, r
        return None

    def expand(self, dish: str, servings: int) -> dict:
        hit = self.find(dish)
        if not hit:
            return {"dish": dish, "found": False, "known_dishes": list(self.raw)}
        name, r = hit
        return {
            "dish": name,
            "found": True,
            "servings": servings,
            "ingredients": [
                {"alias": i["alias"], "amount": round(i["amount"] * servings, 1), "unit": i["unit"]}
                for i in r["per_serving"]
            ],
        }
