"""Storage. A tiny key-value repository interface with local implementations.

Collections used: orders, mandate, audit, purchases, spend.
"""

from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class Repository(ABC):
    @abstractmethod
    def get(self, collection: str, key: str) -> dict | None: ...

    @abstractmethod
    def put(self, collection: str, key: str, value: dict) -> None: ...

    @abstractmethod
    def list(self, collection: str) -> list[dict]: ...

    @abstractmethod
    def clear(self) -> None: ...


class InMemoryRepository(Repository):
    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

    def get(self, collection: str, key: str) -> dict | None:
        v = self._data.get(collection, {}).get(key)
        return json.loads(json.dumps(v)) if v is not None else None

    def put(self, collection: str, key: str, value: dict) -> None:
        with self._lock:
            self._data.setdefault(collection, {})[key] = json.loads(json.dumps(value))

    def list(self, collection: str) -> list[dict]:
        return [json.loads(json.dumps(v)) for v in self._data.get(collection, {}).values()]

    def clear(self) -> None:
        self._data.clear()


class JsonFileRepository(InMemoryRepository):
    """One JSON file holding every collection. Good enough for a single-process demo."""

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self.path = Path(path)
        if self.path.exists():
            self._data = json.loads(self.path.read_text())

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=1, ensure_ascii=False))
        tmp.replace(self.path)

    def put(self, collection: str, key: str, value: dict) -> None:
        super().put(collection, key, value)
        with self._lock:
            self._flush()

    def clear(self) -> None:
        super().clear()
        self._flush()


class DynamoDBRepository(Repository):
    """TODO: single-table DynamoDB implementation (pk=collection, sk=key).

    Planned for deployment on AWS; not needed for the local demo.
    """

    def __init__(self, table_name: str, **_: Any) -> None:
        self.table_name = table_name

    def get(self, collection: str, key: str) -> dict | None:
        raise NotImplementedError("DynamoDBRepository is not implemented yet")

    def put(self, collection: str, key: str, value: dict) -> None:
        raise NotImplementedError("DynamoDBRepository is not implemented yet")

    def list(self, collection: str) -> list[dict]:
        raise NotImplementedError("DynamoDBRepository is not implemented yet")

    def clear(self) -> None:
        raise NotImplementedError("DynamoDBRepository is not implemented yet")
