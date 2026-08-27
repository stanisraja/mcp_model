"""Read-only PostgreSQL + pgvector engine.

Two operations only:
  - run_query: execute a named, allowlisted, parameterized SELECT
  - semantic_search: nearest-neighbor search against a named, pre-registered
    vector search target (table/column/select-list are never agent input --
    see `vector_search` for why that boundary matters)

No arbitrary SQL, no write access. The DB role/user connected as should
itself be granted SELECT-only privileges as a second layer of defense
beyond what this code enforces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import boto3
import psycopg
from pgvector.psycopg import register_vector
from psycopg import sql
from psycopg.rows import dict_row

from ..allowlist import AllowlistedQuery, QueryAllowlist
from ..config import PostgresSettings
from ..guardrails import clamp_limit, enforce_row_limit_sql

# Read-only session guardrails applied on every connection, in addition to
# the app-layer checks in guardrails.py. A misbehaving/compromised query
# that slipped past allowlisting still cannot write or run unbounded.
#
# `SET` is a configuration command, not a regular DML statement -- Postgres
# doesn't accept a bind parameter ($1) for it at the wire-protocol level at
# all, so the timeout value has to be part of the SQL text itself. We still
# never do raw string interpolation: `sql.Literal` asks psycopg to quote/
# escape the value client-side before composing the query, the same
# safety property parameterization gives us, just via a different psycopg
# API because `SET` doesn't support the placeholder form.
_SET_READ_ONLY_SQL = "SET default_transaction_read_only = on"


class PostgresEngine:
    def __init__(self, settings: PostgresSettings, allowlist: QueryAllowlist | None = None):
        self._settings = settings
        self._allowlist = allowlist or QueryAllowlist()

    @property
    def allowlist(self) -> QueryAllowlist:
        return self._allowlist

    def _connect(self) -> psycopg.Connection:
        if self._settings.auth_mode == "iam":
            conn = psycopg.connect(
                host=self._settings.host,
                port=self._settings.port,
                dbname=self._settings.dbname,
                user=self._settings.user,
                password=self._generate_iam_auth_token(),
                sslmode=self._settings.sslmode,
                row_factory=dict_row,
            )
        else:
            conn = psycopg.connect(self._settings.dsn, row_factory=dict_row)

        # Without this, psycopg sends a Python list/array as a generic
        # `double precision[]`, and Postgres has no implicit cast from
        # that to `vector` -- the `<=>` operator in vector_search() fails
        # to resolve at all. register_vector teaches psycopg the `vector`
        # wire type explicitly, independent of any column context.
        register_vector(conn)

        timeout_ms = int(self._settings.statement_timeout_ms)  # guarantee a plain int reaches SQL text
        set_timeout = sql.SQL("SET statement_timeout = {}").format(sql.Literal(timeout_ms))
        with conn.cursor() as cur:
            cur.execute(_SET_READ_ONLY_SQL)
            cur.execute(set_timeout)
        return conn

    def _generate_iam_auth_token(self) -> str:
        """Mint a short-lived (15 min) RDS IAM auth token; never cached or logged."""
        client = boto3.client("rds", region_name=self._settings.region)
        return client.generate_db_auth_token(
            DBHostname=self._settings.host,
            Port=self._settings.port,
            DBUsername=self._settings.user,
        )

    def run_query(self, query_name: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Run a named allowlisted query and return rows as a list of dicts."""
        query = self._allowlist.get(query_name)
        bounded_sql = enforce_row_limit_sql(query.sql, min(query.max_rows, self._settings.max_rows))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(bounded_sql, params or {})
            return cur.fetchall()

    def vector_search(
        self,
        table: str,
        vector_column: str,
        query_embedding: list[float],
        select_columns: list[str],
        limit: int = 10,
    ) -> list[dict]:
        """Nearest-neighbor search using pgvector's `<=>` cosine distance operator.

        Not exposed directly as an MCP tool: `table`, `vector_column`, and
        `select_columns` get f-string-interpolated into the query, so this
        must only ever be called with server-trusted identifiers -- e.g.
        from `semantic_search`, which resolves them from a fixed registry,
        never from agent-supplied arguments. Passing agent input straight
        through here would be a SQL injection hole.
        """
        bounded_limit = clamp_limit(limit, self._settings.max_rows)
        columns_sql = ", ".join(select_columns)
        # Explicit ::vector cast: psycopg sends a plain Python list as a
        # generic array type (register_vector's dumper only intercepts
        # numpy.ndarray/Vector, not list), and Postgres won't implicitly
        # cast an array to `vector` for operator resolution. pgvector
        # defines an *explicit* cast from array types to vector, which
        # this invokes directly rather than depending on the parameter's
        # inferred wire type.
        query_sql = (
            f"SELECT {columns_sql}, {vector_column} <=> %(embedding)s::vector AS distance "
            f"FROM {table} ORDER BY distance ASC LIMIT %(limit)s"
        )
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query_sql, {"embedding": query_embedding, "limit": bounded_limit})
            return cur.fetchall()

    def semantic_search(
        self, search_name: str, query_embedding: list[float], limit: int = 10
    ) -> list[dict]:
        """Run a named, pre-registered vector search. This is what MCP tools call.

        `search_name` selects a `VectorSearchTarget` from `_VECTOR_SEARCH_TARGETS`
        below -- the agent supplies a query embedding and a name, never a
        table, column, or select-list.
        """
        target = _VECTOR_SEARCH_TARGETS.get(search_name)
        if target is None:
            raise KeyError(f"Vector search target {search_name!r} is not registered")
        return self.vector_search(
            table=target.table,
            vector_column=target.vector_column,
            query_embedding=query_embedding,
            select_columns=list(target.select_columns),
            limit=limit,
        )


@dataclass(frozen=True)
class VectorSearchTarget:
    table: str
    vector_column: str
    select_columns: tuple[str, ...]


# The fixed set of vector searches an agent can name via semantic_search().
# Adding a new one here is the only way to expose a new table/column pair --
# there is no path from agent input to a table or column name.
_VECTOR_SEARCH_TARGETS: dict[str, VectorSearchTarget] = {
    "documents": VectorSearchTarget(
        table="documents", vector_column="embedding", select_columns=("id", "title", "body")
    ),
}


def build_default_allowlist() -> QueryAllowlist:
    """The allowlist backing `query_postgres`, against the demo `documents` table.

    Load the demo dataset first with `scripts/load_demo_dataset.py`.
    """
    allowlist = QueryAllowlist()
    allowlist.register(
        AllowlistedQuery(
            name="server_version",
            description="Sanity-check query returning the connected Postgres server version.",
            sql="SELECT version() AS version",
            max_rows=1,
        )
    )
    allowlist.register(
        AllowlistedQuery(
            name="count_documents",
            description="Total number of rows in the demo documents table.",
            sql="SELECT count(*) AS document_count FROM documents",
            max_rows=1,
        )
    )
    allowlist.register(
        AllowlistedQuery(
            name="list_documents",
            description="List demo documents (id, title, body), most recently inserted first.",
            sql="SELECT id, title, body FROM documents ORDER BY id",
            max_rows=100,
        )
    )
    allowlist.register(
        AllowlistedQuery(
            name="get_document_by_id",
            description="Fetch a single demo document by its integer id.",
            sql="SELECT id, title, body FROM documents WHERE id = %(id)s",
            params=("id",),
            max_rows=1,
        )
    )
    return allowlist
