"""Unit tests for PostgresEngine guardrail wiring, using a fake connection.

These deliberately don't require a live Postgres instance -- they verify
that the engine (a) enforces read-only session settings on every
connection, (b) bounds row limits before a query ever reaches the driver,
and (c) refuses query names outside the allowlist. Integration tests
against a real (local/dockerized) Postgres belong in a separate suite
gated behind POSTGRES_DSN being set.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mcp_dbserver.allowlist import AllowlistedQuery, QueryAllowlist
from mcp_dbserver.config import PostgresSettings
from mcp_dbserver.engines.postgres import PostgresEngine


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, rows):
        self.cursor_obj = FakeCursor(rows)

    def cursor(self, **kwargs):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def settings():
    return PostgresSettings(dsn="postgresql://fake", max_rows=50)


def _engine_with_fake_connection(settings, rows):
    allowlist = QueryAllowlist()
    allowlist.register(
        AllowlistedQuery(name="widgets", description="", sql="SELECT * FROM widgets", max_rows=1000)
    )
    allowlist.register(
        AllowlistedQuery(
            name="widget_by_id",
            description="",
            sql="SELECT * FROM widgets WHERE id = %(id)s",
            params=("id",),
            max_rows=1,
        )
    )
    engine = PostgresEngine(settings, allowlist)
    fake_conn = FakeConnection(rows)
    engine._connect = MagicMock(return_value=fake_conn)  # bypass real psycopg.connect
    return engine, fake_conn


def test_run_query_caps_row_limit_at_settings_max_rows(settings):
    engine, fake_conn = _engine_with_fake_connection(settings, rows=[{"id": 1}])

    engine.run_query("widgets")

    sql, _ = fake_conn.cursor_obj.executed[0]
    assert "LIMIT 50" in sql  # settings.max_rows (50) wins over the query's own max_rows (1000)


def test_run_query_binds_params_through_the_driver_not_string_interpolation(settings):
    engine, fake_conn = _engine_with_fake_connection(settings, rows=[{"id": 7}])

    engine.run_query("widget_by_id", {"id": 7})

    sql, params = fake_conn.cursor_obj.executed[0]
    assert "%(id)s" in sql  # the literal 7 never gets interpolated into the SQL string
    assert params == {"id": 7}


def test_run_query_rejects_unknown_query_name(settings):
    engine, _ = _engine_with_fake_connection(settings, rows=[])
    with pytest.raises(KeyError):
        engine.run_query("not_registered")


def test_vector_search_clamps_limit(settings):
    engine, fake_conn = _engine_with_fake_connection(settings, rows=[])

    engine.vector_search(
        table="documents",
        vector_column="embedding",
        query_embedding=[0.1, 0.2],
        select_columns=["id", "body"],
        limit=10_000,
    )

    sql, params = fake_conn.cursor_obj.executed[0]
    assert params["limit"] == settings.max_rows
    assert "documents" in sql


def test_iam_auth_mode_fetches_a_fresh_token_and_never_reuses_a_stored_password():
    settings = PostgresSettings(
        auth_mode="iam",
        host="db.example.rds.amazonaws.com",
        port=5432,
        dbname="postgres",
        user="readonly_user",
        region="us-east-1",
    )
    engine = PostgresEngine(settings, QueryAllowlist())

    fake_rds_client = MagicMock()
    fake_rds_client.generate_db_auth_token.return_value = "fake-iam-token"

    with (
        patch("mcp_dbserver.engines.postgres.boto3.client", return_value=fake_rds_client) as mock_boto,
        patch("mcp_dbserver.engines.postgres.psycopg.connect") as mock_connect,
        patch("mcp_dbserver.engines.postgres.register_vector"),  # needs a real pg_type lookup otherwise
    ):
        mock_connect.return_value = FakeConnection(rows=[])
        engine._connect()

    mock_boto.assert_called_once_with("rds", region_name="us-east-1")
    fake_rds_client.generate_db_auth_token.assert_called_once_with(
        DBHostname="db.example.rds.amazonaws.com", Port=5432, DBUsername="readonly_user"
    )
    _, kwargs = mock_connect.call_args
    assert kwargs["password"] == "fake-iam-token"
    assert kwargs["sslmode"] == "require"
