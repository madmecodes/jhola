"""Storage. A tiny key-value repository interface with local implementations.

Collections used: orders, mandate, txns, audit, purchases, sessions (agent history per phone),\ndemo_acting (WhatsApp demo persona per phone).
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

    def delete(self, collection: str, key: str) -> None:
        raise NotImplementedError

    def count(self, collection: str) -> int:
        return len(self.list(collection))

    def delete_collection(self, collection: str) -> None:
        raise NotImplementedError


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

    def delete(self, collection: str, key: str) -> None:
        with self._lock:
            self._data.get(collection, {}).pop(key, None)

    def delete_collection(self, collection: str) -> None:
        with self._lock:
            self._data.pop(collection, None)

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

    def delete(self, collection: str, key: str) -> None:
        super().delete(collection, key)
        with self._lock:
            self._flush()

    def delete_collection(self, collection: str) -> None:
        super().delete_collection(collection)
        with self._lock:
            self._flush()

    def clear(self) -> None:
        super().clear()
        self._flush()


class DynamoDBRepository(Repository):
    """Single-table DynamoDB repository: pk = collection, sk = key, data = the JSON document.

    Documents are stored as a JSON string, which sidesteps Decimal conversion and keeps
    arbitrary nested values (audit events, agent conversation history) intact.
    """

    def __init__(self, table_name: str, session: Any = None, region: str | None = None) -> None:
        import boto3

        self.table_name = table_name
        self.table = (session or boto3.Session(region_name=region)).resource("dynamodb").Table(table_name)

    def get(self, collection: str, key: str) -> dict | None:
        item = self.table.get_item(Key={"pk": collection, "sk": key}, ConsistentRead=True).get("Item")
        return json.loads(item["data"]) if item else None

    def put(self, collection: str, key: str, value: dict) -> None:
        self.table.put_item(Item={"pk": collection, "sk": key, "data": json.dumps(value, ensure_ascii=False)})

    def delete(self, collection: str, key: str) -> None:
        self.table.delete_item(Key={"pk": collection, "sk": key})

    def _query(self, collection: str, **kw: Any):
        from boto3.dynamodb.conditions import Key

        args = {"KeyConditionExpression": Key("pk").eq(collection), "ConsistentRead": True, **kw}
        while True:
            resp = self.table.query(**args)
            yield resp
            if "LastEvaluatedKey" not in resp:
                return
            args["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def list(self, collection: str) -> list[dict]:
        return [json.loads(i["data"]) for r in self._query(collection) for i in r["Items"]]

    def count(self, collection: str) -> int:
        return sum(r["Count"] for r in self._query(collection, Select="COUNT"))

    def delete_collection(self, collection: str) -> None:
        keys = [i["sk"] for r in self._query(collection, ProjectionExpression="sk") for i in r["Items"]]
        with self.table.batch_writer() as bw:
            for k in keys:
                bw.delete_item(Key={"pk": collection, "sk": k})

    def clear(self) -> None:
        raise NotImplementedError("refusing to wipe the whole DynamoDB table; use delete_collection")
