"""Read-only MongoDB Atlas engine.

Four operations, all against a fixed registry of collection targets
(`_COLLECTION_TARGETS`) -- the agent supplies a logical `target_name`,
never a raw collection name, and never a raw MongoDB filter or
aggregation document (no `$where`, no arbitrary operators):
  - get_document: fetch one document by its `id` field
  - list_documents: a capped `find({})`
  - count_documents: an exact count (unlike DynamoDB, MongoDB's
    `count_documents` is cheap enough to expose live, not just approximate)
  - semantic_search: Atlas Vector Search (`$vectorSearch`) over a
    pre-registered index/field, embedding query text server-side --
    mirrors `PostgresEngine.semantic_search` against the same demo
    dataset, so the two are directly comparable

No write operation exists in this module. As established for Postgres
and DynamoDB, that is not the real guarantee against a code-capable
client with independent pymongo access and the same credentials -- the
actual guardrail is the Atlas database user's role, which should be
scoped to `read` (not `readWrite`) on this database.
"""

from __future__ import annotations

from dataclasses import dataclass

from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

from ..config import MongoDBSettings
from ..guardrails import clamp_limit

# Fields returned to the agent -- excludes the raw embedding vector, which
# is large and meaningless to an LLM caller.
_DOCUMENT_PROJECTION = {"_id": False, "embedding": False}


class MongoDBTargetError(KeyError):
    """Raised when a target_name isn't in the registered collection allowlist."""


@dataclass(frozen=True)
class MongoCollectionTarget:
    collection_name: str
    vector_index_name: str | None = None
    vector_field: str | None = None


# The fixed set of collections an agent can name via target_name. Adding a
# new one here is the only way to expose a new collection -- there is no
# path from agent input to a raw collection name.
_COLLECTION_TARGETS: dict[str, MongoCollectionTarget] = {
    "documents": MongoCollectionTarget(
        collection_name="documents",
        vector_index_name="documents_vector_index",
        vector_field="embedding",
    ),
}


class MongoDBEngine:
    def __init__(self, settings: MongoDBSettings):
        self._settings = settings
        self._client: MongoClient | None = None

    def _get_database(self):
        if self._client is None:
            self._client = MongoClient(self._settings.uri)
        return self._client[self._settings.database]

    def _resolve_target(self, target_name: str) -> MongoCollectionTarget:
        target = _COLLECTION_TARGETS.get(target_name)
        if target is None:
            raise MongoDBTargetError(f"MongoDB target {target_name!r} is not registered")
        return target

    def list_targets(self) -> list[str]:
        return sorted(_COLLECTION_TARGETS)

    def get_document(self, target_name: str, doc_id: int) -> dict | None:
        target = self._resolve_target(target_name)
        collection = self._get_database()[target.collection_name]
        return collection.find_one({"id": doc_id}, projection=_DOCUMENT_PROJECTION)

    def list_documents(self, target_name: str, limit: int | None = None) -> list[dict]:
        target = self._resolve_target(target_name)
        bounded_limit = clamp_limit(limit, self._settings.max_documents)
        collection = self._get_database()[target.collection_name]
        cursor = collection.find({}, projection=_DOCUMENT_PROJECTION).limit(bounded_limit)
        return list(cursor)

    def count_documents(self, target_name: str) -> int:
        target = self._resolve_target(target_name)
        collection = self._get_database()[target.collection_name]
        return collection.count_documents({})

    def semantic_search(
        self, target_name: str, query_embedding: list[float], limit: int = 10
    ) -> list[dict]:
        target = self._resolve_target(target_name)
        if target.vector_index_name is None or target.vector_field is None:
            raise MongoDBTargetError(f"MongoDB target {target_name!r} has no vector search index configured")
        bounded_limit = clamp_limit(limit, self._settings.max_documents)
        collection = self._get_database()[target.collection_name]
        pipeline = [
            {
                "$vectorSearch": {
                    "index": target.vector_index_name,
                    "path": target.vector_field,
                    "queryVector": query_embedding,
                    "numCandidates": max(bounded_limit * 10, 100),
                    "limit": bounded_limit,
                }
            },
            {
                "$project": {
                    "_id": False,
                    "id": True,
                    "title": True,
                    "body": True,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        return list(collection.aggregate(pipeline))

    def ensure_vector_search_index(self, target_name: str, num_dimensions: int) -> str:
        """Create the target's Atlas Vector Search index if it doesn't already exist.

        Used by scripts/load_demo_dataset_mongodb.py, not by any MCP tool
        -- an operator-run setup step, not something an agent triggers.
        Atlas builds the index asynchronously; it may take a minute or two
        to become queryable after this returns.
        """
        target = self._resolve_target(target_name)
        if target.vector_index_name is None or target.vector_field is None:
            raise MongoDBTargetError(f"MongoDB target {target_name!r} has no vector search index configured")
        collection = self._get_database()[target.collection_name]

        existing = list(collection.list_search_indexes(target.vector_index_name))
        if existing:
            return f"Index {target.vector_index_name!r} already exists"

        model = SearchIndexModel(
            name=target.vector_index_name,
            type="vectorSearch",
            definition={
                "fields": [
                    {
                        "type": "vector",
                        "path": target.vector_field,
                        "numDimensions": num_dimensions,
                        "similarity": "cosine",
                    }
                ]
            },
        )
        collection.create_search_index(model)
        return f"Created index {target.vector_index_name!r} (building asynchronously)"
