"""Storage. A tiny key-value repository interface with local implementations.

Collections used: orders, mandate, txns, audit, purchases, sessions (agent history per phone or web
session), demo_acting (WhatsApp demo persona per phone), rules (custom Cedar policies), web_jobs
(console jobs), wa_last_inbound (WhatsApp 24h window), counters (atomic sequences).
"""

from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable


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

    def next_seq(self, name: str, floor: Callable[[], int] = lambda: 0) -> int:
        """Next value of a named counter. A missing counter starts after floor()."""
        doc = self.get("counters", name)
        n = (doc["n"] if doc else floor()) + 1
        self.put("counters", name, {"n": n})
        return n

    def recent(self, collection: str, limit: int) -> list[dict]:
        """The last `limit` documents by key order (newest last)."""
        keys_docs = self.list(collection)
        return keys_docs[-limit:] if limit else keys_docs


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

    def next_seq(self, name: str, floor: Callable[[], int] = lambda: 0) -> int:
        with self._lock:
            c = self._data.setdefault("counters", {})
            n = (c[name]["n"] if name in c else floor()) + 1
            c[name] = {"n": n}
        return n

    def recent(self, collection: str, limit: int) -> list[dict]:
        items = sorted(self._data.get(collection, {}).items())
        return [json.loads(json.dumps(v)) for _, v in (items[-limit:] if limit else items)]

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

    def next_seq(self, name: str, floor: Callable[[], int] = lambda: 0) -> int:
        n = super().next_seq(name, floor)
        with self._lock:
            self._flush()
        return n

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

    def next_seq(self, name: str, floor: Callable[[], int] = lambda: 0) -> int:
        """Atomic counter (pk=counters, numeric attribute n), safe across concurrent Lambdas."""
        from botocore.exceptions import ClientError

        key = {"pk": "counters", "sk": name}
        try:
            r = self.table.update_item(Key=key, UpdateExpression="ADD n :one", ExpressionAttributeValues={":one": 1},
                                       ConditionExpression="attribute_exists(n)", ReturnValues="UPDATED_NEW")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            r = self.table.update_item(Key=key, UpdateExpression="SET n = if_not_exists(n, :floor) + :one",
                                       ExpressionAttributeValues={":floor": floor(), ":one": 1},
                                       ReturnValues="UPDATED_NEW")
        return int(r["Attributes"]["n"])

    def recent(self, collection: str, limit: int) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        args = {"KeyConditionExpression": Key("pk").eq(collection), "ScanIndexForward": False}
        if limit:
            args["Limit"] = limit
        items = self.table.query(**args)["Items"] if limit else [i for r in self._query(collection) for i in r["Items"]][::-1]
        return [json.loads(i["data"]) for i in reversed(items)]

    def delete_collection(self, collection: str) -> None:
        keys = [i["sk"] for r in self._query(collection, ProjectionExpression="sk") for i in r["Items"]]
        with self.table.batch_writer() as bw:
            for k in keys:
                bw.delete_item(Key={"pk": collection, "sk": k})

    def clear(self) -> None:
        raise NotImplementedError("refusing to wipe the whole DynamoDB table; use delete_collection")
