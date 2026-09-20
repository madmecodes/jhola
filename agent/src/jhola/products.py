"""Product Q&A: details, comparisons, alternatives and better-value packs.

Pure functions over the catalog. Nutrition values are approximate label data (nutrition_source in the
catalog) and are returned as numbers the agent quotes with "approx."; nothing here gives medical advice.
"""

from __future__ import annotations

from .domain import Catalog, describe, to_base

VALUE_GAP = 0.10  # suggest the other pack when its unit price is at least 10% lower


def _nutrition(p: dict) -> dict | None:
    return p.get("nutrition_per_100g") or p.get("nutrition_per_100ml")


def pack_grams(p: dict) -> float | None:
    """Pack size in g or ml (None for pieces)."""
    size, unit = to_base(float(p["pack_size"]), p["unit"])
    return size if unit in ("g", "ml") else None


def nutrition_per_pack(p: dict, key: str) -> float | None:
    n = _nutrition(p)
    g = pack_grams(p)
    if not n or g is None or n.get(key) is None:
        return None
    return round(n[key] * g / 100, 1)


def protein_per_rupee(p: dict) -> float | None:
    """Grams of protein per rupee (label protein x pack size / price)."""
    per_pack = nutrition_per_pack(p, "protein_g")
    return round(per_pack / p["price_inr"], 2) if per_pack is not None and p["price_inr"] else None


def is_sugar_free(p: dict) -> bool:
    n = _nutrition(p) or {}
    contains = set(p.get("contains") or [])
    name = f"{p['name']} {' '.join(p.get('tags', []))}".lower()
    if "added_sugar" in contains:
        return False
    if any(w in name for w in ("sugar free", "sugarfree", "sugar-free", "unsweetened", "no added sugar", "diet ",
                                "zero sugar")):
        return True
    return n.get("sugar_g") is not None and n["sugar_g"] <= 1.0


def is_high_protein(p: dict) -> bool:
    n = _nutrition(p) or {}
    return (n.get("protein_g") or 0) >= 10


def same_product_packs(catalog: Catalog, p: dict) -> list[dict]:
    """Other pack sizes of the same brand + product name, in stock."""
    return [it for it in catalog.items if it["id"] != p["id"] and it["brand"] == p["brand"]
            and it["name"] == p["name"] and it["in_stock"]]


def better_value(catalog: Catalog, p: dict) -> dict | None:
    """The pack of the same product with the lowest unit price, if it beats this one by >10%."""
    others = [it for it in same_product_packs(catalog, p) if it.get("unit_price_inr") and p.get("unit_price_inr")
              and it.get("unit_price_basis") == p.get("unit_price_basis")]
    if not others:
        return None
    best = min(others, key=lambda it: it["unit_price_inr"])
    gap = (p["unit_price_inr"] - best["unit_price_inr"]) / p["unit_price_inr"]
    if gap < VALUE_GAP:
        return None
    return {"sku": best["id"], "label": describe(best), "unit_price_inr": best["unit_price_inr"],
            "basis": best["unit_price_basis"].replace("_", " "), "saves_pct": round(gap * 100),
            "note": f"Rs {best['unit_price_inr']} {best['unit_price_basis'].replace('per_', 'per ')} vs "
                    f"Rs {p['unit_price_inr']}, about {round(gap * 100)}% cheaper per unit"}


def details(catalog: Catalog, p: dict) -> dict:
    """Everything the agent may quote about a product. Nutrition is approximate label data."""
    n = _nutrition(p)
    diet = p.get("diet") or {}
    out = {
        "sku": p["id"], "label": describe(p), "brand": p["brand"], "name": p["name"], "category": p["category"],
        "pack": f"{p['pack_size']}{p['unit']}", "price_inr": p["price_inr"], "mrp_inr": p.get("mrp_inr"),
        "unit_price": f"Rs {p['unit_price_inr']} {p.get('unit_price_basis', '').replace('_', ' ')}"
        if p.get("unit_price_inr") else None,
        "in_stock": p["in_stock"], "seller_rating": p["seller_rating"], "fulfilment": p.get("fulfilment"),
        "amazon_search_url": p.get("amazon_search_url"), "shelf_life_days": p.get("shelf_life_days"),
        "is_food": p.get("is_food", False),
    }
    if p.get("is_food"):
        out.update({
            "diet": {k: v for k, v in diet.items() if v} or {"none_of": "veg, vegan, jain, vrat"},
            "allergens": p.get("allergens") or [], "contains": p.get("contains") or [],
            "sugar_free": is_sugar_free(p), "high_protein": is_high_protein(p),
        })
        if p.get("caffeine_mg_per_serving"):
            out["caffeine_mg_per_serving"] = p["caffeine_mg_per_serving"]
        if n:
            out["nutrition_approx"] = {"basis": p.get("nutrition_basis", "100g"), **n}
            per_pack = nutrition_per_pack(p, "protein_g")
            if per_pack is not None:
                out["protein_g_per_pack_approx"] = per_pack
                out["protein_g_per_rupee"] = protein_per_rupee(p)
        if p.get("nutrition_note"):
            out["nutrition_note"] = p["nutrition_note"]
        out["disclaimer"] = "approximate label values, not medical advice"
    bv = better_value(catalog, p)
    if bv:
        out["better_value_pack"] = bv
    return out


def compare(catalog: Catalog, products: list[dict]) -> dict:
    rows = []
    for p in products:
        n = _nutrition(p) or {}
        rows.append({
            "sku": p["id"], "label": describe(p), "price_inr": p["price_inr"],
            "unit_price": f"Rs {p['unit_price_inr']} {p.get('unit_price_basis', '').replace('_', ' ')}"
            if p.get("unit_price_inr") else None,
            "unit_price_inr": p.get("unit_price_inr"),
            "protein_g_per_100": n.get("protein_g"), "protein_g_per_rupee": protein_per_rupee(p),
            "sugar_g_per_100": n.get("sugar_g"), "sodium_mg_per_100": n.get("sodium_mg"),
            "energy_kcal_per_100": n.get("energy_kcal"), "fiber_g_per_100": n.get("fiber_g"),
            "sugar_free": is_sugar_free(p) if p.get("is_food") else None,
            "diet": {k: v for k, v in (p.get("diet") or {}).items() if v}, "allergens": p.get("allergens") or [],
            "seller_rating": p["seller_rating"], "in_stock": p["in_stock"],
        })

    def best(key, lowest=False):
        cands = [r for r in rows if r.get(key) is not None]
        if len(cands) < 2:
            return None
        return (min if lowest else max)(cands, key=lambda r: r[key])["sku"]

    return {"products": rows, "best": {
        "most_protein_per_rupee": best("protein_g_per_rupee"), "least_sugar": best("sugar_g_per_100", lowest=True),
        "least_sodium": best("sodium_mg_per_100", lowest=True), "cheapest_per_unit": best("unit_price_inr", lowest=True),
    }, "disclaimer": "approximate label values, not medical advice"}


def alternatives(catalog: Catalog, base: dict | None, query: str = "", sugar_free: bool = False,
                 high_protein: bool = False, jain: bool = False, vegan: bool = False, vrat: bool = False,
                 cheaper_per_unit: bool = False, max_price: int | None = None, avoid_allergens: list[str] | None = None,
                 limit: int = 5) -> list[dict]:
    """Products like `base` (or matching `query`) that satisfy the constraints, best first."""
    if base:
        tags = set(base["tags"][:3])
        pool = [it for it in catalog.items if it["id"] != base["id"] and it["category"] == base["category"]
                and set(it["tags"]) & tags]
        if len(pool) < 3:  # widen: same subcategory
            pool += [it for it in catalog.items if it["id"] != base["id"] and it not in pool
                     and it.get("subcategory") == base.get("subcategory")]
    else:
        pool = catalog.search(query, limit=40) if query else []
    avoid = set(avoid_allergens or [])
    out = []
    for it in pool:
        if not it["in_stock"] or it["seller_rating"] < 4.0:
            continue
        d = it.get("diet") or {}
        if sugar_free and not is_sugar_free(it):
            continue
        if high_protein and not is_high_protein(it):
            continue
        if jain and not d.get("jain_friendly"):
            continue
        if vegan and not d.get("vegan"):
            continue
        if vrat and not d.get("vrat_friendly"):
            continue
        if max_price is not None and it["price_inr"] > max_price:
            continue
        if avoid and avoid & set(it.get("allergens") or []):
            continue
        if cheaper_per_unit and base and base.get("unit_price_inr") and it.get("unit_price_inr") and (
                it.get("unit_price_basis") != base.get("unit_price_basis")
                or it["unit_price_inr"] >= base["unit_price_inr"]):
            continue
        out.append(it)
    if cheaper_per_unit:
        out.sort(key=lambda it: it.get("unit_price_inr") or 1e9)
    elif high_protein:
        out.sort(key=lambda it: -(protein_per_rupee(it) or 0))
    else:
        out.sort(key=lambda it: (-it["seller_rating"], it["price_inr"]))
    rows = []
    for it in out[:limit]:
        n = _nutrition(it) or {}
        rows.append({"sku": it["id"], "label": describe(it),
                     "unit_price": f"Rs {it['unit_price_inr']} {it.get('unit_price_basis', '').replace('_', ' ')}"
                     if it.get("unit_price_inr") else None,
                     "protein_g_per_100": n.get("protein_g"), "sugar_g_per_100": n.get("sugar_g"),
                     "sugar_free": is_sugar_free(it) if it.get("is_food") else None,
                     "diet": [k for k, v in (it.get("diet") or {}).items() if v], "allergens": it.get("allergens") or []})
    return rows
