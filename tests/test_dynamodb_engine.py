"""Unit tests for DynamoDBEngine, using a fake boto3 resource/table.

These deliberately don't require live AWS credentials or a real table --
they verify the target registry is the only path to a table name, and
that limits get clamped before reaching the driver. Integration testing
against the real DynamicLinks table happens by hand through a connected
MCP client (see the Phase 5 conversation), not in this automated suite.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mcp_dbserver.config import DynamoDBSettings
from mcp_dbserver.engines.dynamodb import DynamoDBEngine, DynamoDBTargetError


@pytest.fixture
def settings():
    return DynamoDBSettings(region="us-east-1", max_items=50)


def _engine_with_fake_resource(fake_table):
    engine = DynamoDBEngine(DynamoDBSettings(region="us-east-1", max_items=50))
    fake_resource = MagicMock()
    fake_resource.Table.return_value = fake_table
    engine._get_resource = MagicMock(return_value=fake_resource)
    return engine, fake_resource


def test_get_item_rejects_unregistered_target(settings):
    engine = DynamoDBEngine(settings)
    with pytest.raises(DynamoDBTargetError):
        engine.get_item("not_registered", "abc")


def test_get_item_uses_the_registered_table_name_and_partition_key():
    fake_table = MagicMock()
    fake_table.get_item.return_value = {"Item": {"linkId": "abc", "url": "https://example.com"}}
    engine, fake_resource = _engine_with_fake_resource(fake_table)

    result = engine.get_item("dynamic_links", "abc")

    fake_resource.Table.assert_called_once_with("DynamicLinks")
    fake_table.get_item.assert_called_once_with(Key={"linkId": "abc"})
    assert result == {"linkId": "abc", "url": "https://example.com"}


def test_get_item_returns_none_when_missing():
    fake_table = MagicMock()
    fake_table.get_item.return_value = {}  # no "Item" key -- DynamoDB's actual not-found shape
    engine, _ = _engine_with_fake_resource(fake_table)

    assert engine.get_item("dynamic_links", "does-not-exist") is None


def test_list_items_clamps_limit_to_settings_max_items():
    fake_table = MagicMock()
    fake_table.scan.return_value = {"Items": []}
    engine, _ = _engine_with_fake_resource(fake_table)

    engine.list_items("dynamic_links", limit=10_000)

    fake_table.scan.assert_called_once_with(Limit=50)  # settings.max_items


def test_list_items_rejects_unregistered_target(settings):
    engine = DynamoDBEngine(settings)
    with pytest.raises(DynamoDBTargetError):
        engine.list_items("not_registered")


def test_count_items_reports_metadata_count_not_a_live_scan():
    engine = DynamoDBEngine(DynamoDBSettings(region="us-east-1"))
    fake_client = MagicMock()
    fake_client.describe_table.return_value = {"Table": {"ItemCount": 42}}
    fake_resource = MagicMock()
    fake_resource.meta.client = fake_client
    engine._get_resource = MagicMock(return_value=fake_resource)

    result = engine.count_items("dynamic_links")

    fake_client.describe_table.assert_called_once_with(TableName="DynamicLinks")
    assert result["approximate_item_count"] == 42


def test_get_resource_passes_endpoint_url_when_set():
    settings = DynamoDBSettings(region="us-east-1", endpoint_url="http://localhost:8000")
    engine = DynamoDBEngine(settings)

    with patch("mcp_dbserver.engines.dynamodb.boto3.resource") as mock_resource:
        engine._get_resource()

    mock_resource.assert_called_once_with(
        "dynamodb", region_name="us-east-1", endpoint_url="http://localhost:8000"
    )
