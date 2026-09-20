"""Product Q&A: details, comparisons, alternatives, better-value packs, through the agent tools."""

from jhola import products
from jhola.agent import JholaAgent
from jhola.stub_model import Call, Say, ScriptedModel

PANEER = "amul-fresh-paneer-200g"


def _tool(app, phone, name, args):
    def script():
        r = yield Call(name, args)
        yield Say(str(r[0])[:200])

    reply = JholaAgent(app, vision=None).handle_message(phone, "q", model=ScriptedModel(script))
    return reply.tool_calls[0]["output"]


def test_details_have_nutrition_diet_and_links(app, members):
    p = app.catalog.get(PANEER) or app.catalog.search("paneer")[0]
    d = products.details(app.catalog, p)
    assert d["nutrition_approx"]["protein_g"] > 10 and d["disclaimer"].startswith("approximate")
    assert d["diet"].get("veg") and d["amazon_search_url"].startswith("https://www.amazon.in/")
    assert d["unit_price"] and d["fulfilment"] and d["protein_g_per_rupee"] > 0
    out = _tool(app, members["dad"].phone, "get_product_details", {"sku_or_query": "paneer"})
    assert out["nutrition_approx"]["protein_g"] > 10


def test_details_non_food_has_no_nutrition(app):
    d = products.details(app.catalog, app.catalog.get("camlin-geometry-box-scholar-1pcs"))
    assert "nutrition_approx" not in d and "disclaimer" not in d


def test_better_value_pack_over_10_percent(app):
    small = app.catalog.get("aashirvaad-shudh-chakki-atta-1kg")
    bv = products.better_value(app.catalog, small)
    assert bv and bv["sku"] == "aashirvaad-shudh-chakki-atta-10kg" and bv["saves_pct"] >= 10
    big = app.catalog.get("aashirvaad-shudh-chakki-atta-10kg")
    assert products.better_value(app.catalog, big) is None
    # under 10% is not worth a line
    assert products.better_value(app.catalog, app.catalog.get("nescafe-classic-coffee-50g")) is None


def test_resolve_item_mentions_better_value(app, members):
    out = _tool(app, members["dad"].phone, "resolve_item", {"query": "aashirvaad atta", "amount": 1, "unit": "kg"})
    if out["sku"] != "aashirvaad-shudh-chakki-atta-1kg":  # the household's usual pack is the 5 kg one
        out = _tool(app, members["dad"].phone, "get_product_details", {"sku_or_query": "aashirvaad-shudh-chakki-atta-1kg"})
    assert out.get("better_value_pack", {}).get("sku") == "aashirvaad-shudh-chakki-atta-10kg"


def test_compare_protein_sugar_unit_price(app, members):
    out = _tool(app, members["dad"].phone, "compare_products",
                {"skus_or_queries": ["tata sampann toor dal", "tata sampann moong dal", "india gate basmati"]})
    assert len(out["products"]) == 3 and out["best"]["most_protein_per_rupee"]
    assert all(r["protein_g_per_rupee"] is not None for r in out["products"])
    assert out["disclaimer"]
    err = _tool(app, members["dad"].phone, "compare_products", {"skus_or_queries": ["no such thing xyz"]})
    assert "error" in err


def test_alternatives_sugar_free_biscuit(app, members):
    out = _tool(app, members["dad"].phone, "find_alternatives", {"sku_or_query": "biscuit", "sugar_free": True})
    assert out["alternatives"] and all(a["sugar_free"] for a in out["alternatives"])


def test_alternatives_jain_namkeen_and_allergy_of_beneficiary(app, members):
    out = _tool(app, members["didi"].phone, "find_alternatives",
                {"sku_or_query": "haldiram-s-navratan-mix-400g", "jain": True, "for_member": "Dadi"})
    assert out["for"] == "Dadi" and out["alternatives"]
    assert all("jain_friendly" in a["diet"] for a in out["alternatives"])
    out2 = _tool(app, members["dad"].phone, "find_alternatives", {"sku_or_query": "snickers", "for_member": "Aarav"})
    assert out2["alternatives"] and all("peanut" not in a["allergens"] for a in out2["alternatives"])


def test_alternatives_cheaper_atta_per_kg(app, members):
    out = _tool(app, members["dad"].phone, "find_alternatives",
                {"sku_or_query": "aashirvaad-shudh-chakki-atta-5kg", "cheaper_per_unit": True})
    base = app.catalog.get("aashirvaad-shudh-chakki-atta-5kg")["unit_price_inr"]
    assert out["alternatives"]
    assert all(float(a["unit_price"].split()[1]) < base for a in out["alternatives"])


def test_alternatives_max_price_and_high_protein(app):
    rows = products.alternatives(app.catalog, None, "dal", high_protein=True, max_price=150)
    assert rows and all(a["protein_g_per_100"] >= 10 for a in rows)
