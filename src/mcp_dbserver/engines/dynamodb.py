"""Read-only DynamoDB engine.

Three operations, all against a fixed registry of table targets
(`_TABLE_TARGETS`) -- the agent supplies a logical `target_name`, never a
raw AWS table name:
  - get_item: fetch one item by its partition key
  - list_items: a capped Scan (there's no cheaper "list everything" op in
    DynamoDB without a sort key/GSI to Query against)
  - count_items: an approximate, zero-cost item count from table metadata

No write operation exists in this module at all -- but per the lesson
from Phase 5 testing the Postgres engine (an agent with independent boto3
access bypassed the read-only *tool* guardrail entirely and only failed
because the DB role lacked write privilege), the code-level absence of a
delete/put method is not the real guarantee. The actual guardrail is the
IAM policy behind whatever credentials this process runs with: it should
be scoped to exactly `dynamodb:GetItem`, `dynamodb:Scan`, and
`dynamodb:DescribeTable` on the specific table ARN(s) in `_TABLE_TARGETS`,
nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass

import boto3

from ..config import DynamoDBSettings
from ..guardrails import clamp_limit


class DynamoDBTargetError(KeyError):
    """Raised when a target_name isn't in the registered table allowlist."""


@dataclass(frozen=True)
class DynamoDBTableTarget:
    table_name: str
    partition_key: str


# The fixed set of tables an agent can name via target_name. Adding a new
# one here is the only way to expose a new table -- there is no path from
# agent input to a raw AWS table name.
_TABLE_TARGETS: dict[str, DynamoDBTableTarget] = {
    "dynamic_links": DynamoDBTableTarget(table_name="DynamicLinks", partition_key="linkId"),
}


class DynamoDBEngine:
    def __init__(self, settings: DynamoDBSettings):
        self._settings = settings
        self._resource = None

    def _get_resource(self):
        if self._resource is None:
            kwargs = {"region_name": self._settings.region}
            if self._settings.endpoint_url:
                kwargs["endpoint_url"] = self._settings.endpoint_url
            self._resource = boto3.resource("dynamodb", **kwargs)
        return self._resource

    def _resolve_target(self, target_name: str) -> DynamoDBTableTarget:
        target = _TABLE_TARGETS.get(target_name)
        if target is None:
            raise DynamoDBTargetError(f"DynamoDB target {target_name!r} is not registered")
        return target

    def list_targets(self) -> list[str]:
        return sorted(_TABLE_TARGETS)

    def get_item(self, target_name: str, partition_key_value: str) -> dict | None:
        target = self._resolve_target(target_name)
        table = self._get_resource().Table(target.table_name)
        response = table.get_item(Key={target.partition_key: partition_key_value})
        return response.get("Item")

    def list_items(self, target_name: str, limit: int | None = None) -> list[dict]:
        target = self._resolve_target(target_name)
        bounded_limit = clamp_limit(limit, self._settings.max_items)
        table = self._get_resource().Table(target.table_name)
        response = table.scan(Limit=bounded_limit)
        return response.get("Items", [])

    def count_items(self, target_name: str) -> dict:
        """Approximate item count from table metadata (zero read-capacity cost).

        DynamoDB updates this figure roughly every six hours -- it is not
        a live count. An exact count requires a full table Scan, which is
        expensive and unbounded, so it's deliberately not offered here.
        """
        target = self._resolve_target(target_name)
        client = self._get_resource().meta.client
        description = client.describe_table(TableName=target.table_name)
        return {
            "approximate_item_count": description["Table"]["ItemCount"],
            "note": "Updated periodically by DynamoDB, not a live count",
        }
