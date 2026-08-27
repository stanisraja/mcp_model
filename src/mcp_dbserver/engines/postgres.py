"""Read-only PostgreSQL + pgvector engine.

Two operations only:
  - run_query: execute a named, allowlisted, parameterized SELECT
  - vector_search: nearest-neighbor search over a pgvector column

No arbitrary SQL, no write access. The DB role/user connected as should
itself be granted SELECT-only privileges as a second layer of defense
beyond what this code enforces.
"""

from __future__ import annotations

from typing import Any

import boto3
import psycopg
from psycopg.rows import dict_row

from ..allowlist import AllowlistedQuery, QueryAllowlist
from ..config import PostgresSettings
from ..guardrails import clamp_limit, enforce_row_limit_sql

# Read-only session guardrails applied on every connection, in addition to
# the app-layer checks in guardrails.py. A misbehaving/compromised query
# that slipped past allowlisting still cannot write or run unbounded.
#
# Two separate statements, not one `;`-joined string: psycopg3 sends a
# parameterized execute() through Postgres's extended query protocol,
# which only permits a single statement per prepared execution -- a
# multi-statement string with a placeholder fails with a syntax error at
# the parameter marker.
_SET_READ_ONLY_SQL = "SET default_transaction_read_only = on"
_SET_STATEMENT_TIMEOUT_SQL = "SET statement_timeout = %s"


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
        with conn.cursor() as cur:
            cur.execute(_SET_READ_ONLY_SQL)
            cur.execute(_SET_STATEMENT_TIMEOUT_SQL, (self._settings.statement_timeout_ms,))
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

        `table`, `vector_column`, and `select_columns` are validated against
        a caller-supplied allowlist by the server layer before this is
        invoked — this method assumes they're already trusted identifiers,
        not raw agent input.
        """
        bounded_limit = clamp_limit(limit, self._settings.max_rows)
        columns_sql = ", ".join(select_columns)
        sql = (
            f"SELECT {columns_sql}, {vector_column} <=> %(embedding)s AS distance "
            f"FROM {table} ORDER BY distance ASC LIMIT %(limit)s"
        )
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, {"embedding": query_embedding, "limit": bounded_limit})
            return cur.fetchall()


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
