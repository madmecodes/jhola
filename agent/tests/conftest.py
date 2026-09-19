import pytest

from jhola.config import DEMO_NOW, Clock
from jhola.orders import Jhola
from jhola.store import InMemoryRepository


@pytest.fixture
def app():
    return Jhola(InMemoryRepository(), Clock(DEMO_NOW))


@pytest.fixture
def members(app):
    return {m.id: m for m in app.hh.members}
