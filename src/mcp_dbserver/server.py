"""MCP server entrypoint.

Registers read-only, guardrailed tools for whichever engines have their
required environment variables set. An engine with missing credentials is
simply not registered, rather than the server failing to start — so this
runs fine with only Postgres configured during early development.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import MissingCredentialError, PostgresSettings
from .engines.postgres import PostgresEngine, build_default_allowlist

mcp = FastMCP("multi-engine-db")

_postgres_engine: PostgresEngine | None = None
try:
    _postgres_engine = PostgresEngine(PostgresSettings.from_env(), build_default_allowlist())
except MissingCredentialError:
    _postgres_engine = None


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

    @mcp.tool()
    def vector_search_postgres(
        table: str,
        vector_column: str,
        query_embedding: list[float],
        select_columns: list[str],
        limit: int = 10,
    ) -> list[dict]:
        """Semantic (cosine-distance) nearest-neighbor search over a pgvector column."""
        assert _postgres_engine is not None
        return _postgres_engine.vector_search(table, vector_column, query_embedding, select_columns, limit)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
