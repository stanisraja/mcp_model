"""Read-only DynamoDB engine (Phase 3 — not yet implemented).

Planned surface:
  - get_item(table, key) -> dict | None
  - query_table(table, key_condition, limit) -> list[dict]

Both will enforce a table-name allowlist (via `DYNAMODB_TABLE_PREFIX`),
a hard item-count cap, and read-only IAM credentials.
"""

from __future__ import annotations

from ..config import DynamoDBSettings


class DynamoDBEngine:
    def __init__(self, settings: DynamoDBSettings):
        self._settings = settings

    def get_item(self, table: str, key: dict) -> dict | None:
        raise NotImplementedError("DynamoDB support lands in Phase 3")

    def query_table(self, table: str, key_condition: dict, limit: int | None = None) -> list[dict]:
        raise NotImplementedError("DynamoDB support lands in Phase 3")
