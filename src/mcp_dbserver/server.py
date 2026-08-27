"""MCP server entrypoint.

Registers read-only, guardrailed tools for whichever engines have their
required environment variables set. An engine with missing credentials is
simply not registered, rather than the server failing to start — so this
runs fine with only Postgres configured during early development.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import DynamoDBSettings, MissingCredentialError, PostgresSettings
from .engines.dynamodb import DynamoDBEngine
from .engines.postgres import PostgresEngine, build_default_allowlist

mcp = FastMCP("multi-engine-db")

_postgres_engine: PostgresEngine | None = None
try:
    _postgres_engine = PostgresEngine(PostgresSettings.from_env(), build_default_allowlist())
except MissingCredentialError:
    _postgres_engine = None

_dynamodb_engine: DynamoDBEngine | None = None
try:
    _dynamodb_engine = DynamoDBEngine(DynamoDBSettings.from_env())
except MissingCredentialError:
    _dynamodb_engine = None


if _postgres_engine is not None:

    @mcp.tool()
    def query_postgres(query_name: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Run a named, allowlisted, read-only Postgres query and return rows.

        query_name must be one of the server's registered allowlisted
        queries (never raw SQL). Row counts are capped server-side
        regardless of what's requested.
        """
        assert _postgres_engine is not None
        return _postgres_engine.run_query(query_name, params)

    @mcp.tool()
    def list_postgres_queries() -> list[str]:
        """List the names of allowlisted Postgres queries available to query_postgres."""
        assert _postgres_engine is not None
        return _postgres_engine.allowlist.names()

    _embedding_model_cache: dict[str, Any] = {}

    def _get_embedding_model():
        if "model" not in _embedding_model_cache:
            from fastembed import TextEmbedding

            _embedding_model_cache["model"] = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        return _embedding_model_cache["model"]

    @mcp.tool()
    def semantic_search_documents(query_text: str, limit: int = 10) -> list[dict]:
        """Semantic (cosine-distance) search over the demo documents table.

        query_text is any natural-language string; the server embeds it
        locally (offline, no external API call) and searches -- the agent
        never supplies a table name, column name, or a raw embedding vector.
        """
        assert _postgres_engine is not None
        embedding = next(_get_embedding_model().embed([query_text])).tolist()
        return _postgres_engine.semantic_search("documents", embedding, limit)


if _dynamodb_engine is not None:

    @mcp.tool()
    def list_dynamodb_tables() -> list[str]:
        """List the DynamoDB target names available to the other dynamodb_* tools."""
        assert _dynamodb_engine is not None
        return _dynamodb_engine.list_targets()

    @mcp.tool()
    def get_dynamodb_item(target_name: str, partition_key_value: str) -> dict | None:
        """Fetch one item by its partition key from a registered DynamoDB target.

        target_name must be one from list_dynamodb_tables() -- never a raw
        AWS table name.
        """
        assert _dynamodb_engine is not None
        return _dynamodb_engine.get_item(target_name, partition_key_value)

    @mcp.tool()
    def list_dynamodb_items(target_name: str, limit: int = 100) -> list[dict]:
        """List items from a registered DynamoDB target (a capped Scan). Row count is capped server-side."""
        assert _dynamodb_engine is not None
        return _dynamodb_engine.list_items(target_name, limit)

    @mcp.tool()
    def count_dynamodb_items(target_name: str) -> dict:
        """Approximate item count for a registered DynamoDB target (not a live count)."""
        assert _dynamodb_engine is not None
        return _dynamodb_engine.count_items(target_name)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
