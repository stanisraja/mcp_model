"""Read-only MongoDB Atlas engine (Phase 4 — not yet implemented).

Planned surface:
  - list_collections() -> list[str]
  - find(collection, filter, projection, limit) -> list[dict], filter/projection
    restricted to an allowlisted shape (no $where, no raw JS)
  - vector_search(collection, index, query_embedding, limit) -> list[dict]
    via Atlas Vector Search's $vectorSearch aggregation stage
"""

from __future__ import annotations

from ..config import MongoDBSettings


class MongoDBEngine:
    def __init__(self, settings: MongoDBSettings):
        self._settings = settings

    def list_collections(self) -> list[str]:
        raise NotImplementedError("MongoDB support lands in Phase 4")

    def find(
        self,
        collection: str,
        filter: dict,
        projection: dict | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        raise NotImplementedError("MongoDB support lands in Phase 4")

    def vector_search(
        self,
        collection: str,
        index: str,
        query_embedding: list[float],
        limit: int = 10,
    ) -> list[dict]:
        raise NotImplementedError("MongoDB support lands in Phase 4")
