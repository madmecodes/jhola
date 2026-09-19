"""Hindi / Hinglish aliases resolve to the right product."""

import pytest

from jhola.domain import Catalog, Household, Resolver
from jhola.store import InMemoryRepository

CAT = Catalog.load()


@pytest.mark.parametrize("query,expected", [
    ("arhar ki dal", "toor-dal"),
    ("kothmir", "coriander-leaves"),
    ("pyaj", "onion"),
    ("dudh", "milk"),
])
def test_alias_search_top_hit(query, expected):
    assert expected in CAT.search(query)[0]["id"]


def test_powder_only_when_asked():
    assert "coriander-powder" in CAT.search("dhaniya powder")[0]["id"]


def test_alias_resolves_through_resolver():
    r = Resolver(CAT, Household.load(InMemoryRepository()))
    res = r.resolve("pyaj", amount=1, unit="kg")
    assert res["resolved"] and "onion" in res["sku"] and res["qty"] == 1
    assert "milk" in r.resolve("dudh 2 packet", quantity=2)["sku"]
