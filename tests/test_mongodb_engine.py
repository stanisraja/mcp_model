"""Unit tests for MongoDBEngine, using a fake pymongo collection.

These deliberately don't require a live Atlas cluster -- they verify the
target registry is the only path to a collection name, that limits get
clamped, and that the vector search pipeline is shaped correctly.
Integration testing against the real Atlas cluster happens by hand
through scripts/verify_demo_dataset_mongodb.py and a connected MCP
client, not in this automated suite.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcp_dbserver.config import MongoDBSettings
from mcp_dbserver.engines.mongodb import MongoDBEngine, MongoDBTargetError


@pytest.fixture
def settings():
    return MongoDBSettings(uri="mongodb://fake", database="testdb", max_documents=50)


def _engine_with_fake_collection(settings, fake_collection):
    engine = MongoDBEngine(settings)
    fake_db = MagicMock()
    fake_db.__getitem__.return_value = fake_collection
    engine._get_database = MagicMock(return_value=fake_db)
    return engine


def test_get_document_rejects_unregistered_target(settings):
    engine = MongoDBEngine(settings)
    with pytest.raises(MongoDBTargetError):
        engine.get_document("not_registered", 1)


def test_get_document_queries_by_id_field_and_excludes_embedding(settings):
    fake_collection = MagicMock()
    fake_collection.find_one.return_value = {"id": 1, "title": "x", "body": "y"}
    engine = _engine_with_fake_collection(settings, fake_collection)

    result = engine.get_document("documents", 1)

    fake_collection.find_one.assert_called_once_with(
        {"id": 1}, projection={"_id": False, "embedding": False}
    )
    assert result == {"id": 1, "title": "x", "body": "y"}


def test_list_documents_clamps_limit_to_settings_max_documents(settings):
    fake_collection = MagicMock()
    fake_cursor = MagicMock()
    fake_cursor.limit.return_value = []
    fake_collection.find.return_value = fake_cursor
    engine = _engine_with_fake_collection(settings, fake_collection)

    engine.list_documents("documents", limit=10_000)

    fake_cursor.limit.assert_called_once_with(50)  # settings.max_documents


def test_list_documents_rejects_unregistered_target(settings):
    engine = MongoDBEngine(settings)
    with pytest.raises(MongoDBTargetError):
        engine.list_documents("not_registered")


def test_count_documents_uses_exact_count(settings):
    fake_collection = MagicMock()
    fake_collection.count_documents.return_value = 30
    engine = _engine_with_fake_collection(settings, fake_collection)

    assert engine.count_documents("documents") == 30
    fake_collection.count_documents.assert_called_once_with({})


def test_semantic_search_builds_a_vector_search_pipeline(settings):
    fake_collection = MagicMock()
    fake_collection.aggregate.return_value = [{"id": 1, "title": "x", "score": 0.9}]
    engine = _engine_with_fake_collection(settings, fake_collection)

    results = engine.semantic_search("documents", query_embedding=[0.1, 0.2], limit=5)

    pipeline = fake_collection.aggregate.call_args[0][0]
    vector_search_stage = pipeline[0]["$vectorSearch"]
    assert vector_search_stage["index"] == "documents_vector_index"
    assert vector_search_stage["path"] == "embedding"
    assert vector_search_stage["queryVector"] == [0.1, 0.2]
    assert vector_search_stage["limit"] == 5
    assert results == [{"id": 1, "title": "x", "score": 0.9}]


def test_semantic_search_clamps_limit(settings):
    fake_collection = MagicMock()
    fake_collection.aggregate.return_value = []
    engine = _engine_with_fake_collection(settings, fake_collection)

    engine.semantic_search("documents", query_embedding=[0.1], limit=10_000)

    pipeline = fake_collection.aggregate.call_args[0][0]
    assert pipeline[0]["$vectorSearch"]["limit"] == 50  # settings.max_documents
