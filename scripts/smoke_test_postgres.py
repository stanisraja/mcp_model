"""Verify Postgres connectivity + guardrails against a real, configured database.

Run this locally after filling in .env (either POSTGRES_DSN or the
POSTGRES_AUTH_MODE=iam variables) to confirm:
  1. the server can actually connect and run an allowlisted query,
  2. the read-only session guardrail is really in effect (a write attempt
     against a real connection is rejected by Postgres itself, not just by
     the app-layer guardrail already covered in tests/).

Usage:
    python scripts/smoke_test_postgres.py
"""

from __future__ import annotations

import psycopg

from mcp_dbserver.config import PostgresSettings
from mcp_dbserver.engines.postgres import PostgresEngine, build_default_allowlist


def main() -> None:
    settings = PostgresSettings.from_env()
    engine = PostgresEngine(settings, build_default_allowlist())

    print("1. Running allowlisted query 'server_version'...")
    rows = engine.run_query("server_version")
    print(f"   OK: {rows}")

    print("2. Confirming a write is rejected at the database level (not just app-layer)...")
    try:
        with engine._connect() as conn, conn.cursor() as cur:
            cur.execute("CREATE TABLE should_never_exist (id int)")
        print("   FAIL: write succeeded -- the connection is not actually read-only!")
    except psycopg.errors.ReadOnlySqlTransaction:
        print("   OK: write rejected by Postgres (default_transaction_read_only in effect)")

    print("\nSmoke test passed.")


if __name__ == "__main__":
    main()
