"""Credential and settings loading.

All credentials come from environment variables (optionally via a local
.env file during development). Nothing is ever hardcoded or logged. Each
engine's settings are only constructed when that engine is actually used,
so a partially configured environment (e.g. Postgres only) still works.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class MissingCredentialError(RuntimeError):
    """Raised when a required environment variable is not set."""


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingCredentialError(f"Required environment variable {name} is not set")
    return value


@dataclass(frozen=True)
class PostgresSettings:
    """Two auth modes:

    - "password": a plain connection string in POSTGRES_DSN.
    - "iam": RDS IAM database authentication — the engine generates a
      short-lived (15 min) auth token per connection via
      `rds:GenerateDBAuthToken` instead of using a stored password. This is
      the preferred mode against RDS: no long-lived DB credential exists
      anywhere, and access is governed by the same IAM policy/role as the
      rest of AWS. Requires the target Postgres user to have the `rds_iam`
      role granted, and the RDS instance to have IAM auth enabled.
    """

    auth_mode: str = "password"
    dsn: str | None = None
    host: str | None = None
    port: int = 5432
    dbname: str | None = None
    user: str | None = None
    region: str | None = None
    sslmode: str = "require"
    statement_timeout_ms: int = 5000
    max_rows: int = 500

    @classmethod
    def from_env(cls) -> PostgresSettings:
        auth_mode = os.environ.get("POSTGRES_AUTH_MODE", "password").lower()
        statement_timeout_ms = int(os.environ.get("POSTGRES_STATEMENT_TIMEOUT_MS", "5000"))
        max_rows = int(os.environ.get("POSTGRES_MAX_ROWS", "500"))

        if auth_mode == "iam":
            return cls(
                auth_mode="iam",
                host=_require("POSTGRES_HOST"),
                port=int(os.environ.get("POSTGRES_PORT", "5432")),
                dbname=os.environ.get("POSTGRES_DBNAME", "postgres"),
                user=_require("POSTGRES_USER"),
                region=_require("AWS_REGION"),
                sslmode=os.environ.get("POSTGRES_SSLMODE", "require"),
                statement_timeout_ms=statement_timeout_ms,
                max_rows=max_rows,
            )

        return cls(
            auth_mode="password",
            dsn=_require("POSTGRES_DSN"),
            statement_timeout_ms=statement_timeout_ms,
            max_rows=max_rows,
        )


@dataclass(frozen=True)
class DynamoDBSettings:
    """No table name lives here -- accessible tables come from a fixed
    registry in engines/dynamodb.py (`_TABLE_TARGETS`), the same pattern
    Postgres uses for vector search targets. The agent selects a table by
    a logical target name, never a raw AWS table name.
    """

    region: str
    endpoint_url: str | None = None
    max_items: int = 500

    @classmethod
    def from_env(cls) -> DynamoDBSettings:
        return cls(
            region=_require("AWS_REGION"),
            endpoint_url=os.environ.get("DYNAMODB_ENDPOINT_URL"),
            max_items=int(os.environ.get("DYNAMODB_MAX_ITEMS", "500")),
        )


@dataclass(frozen=True)
class MongoDBSettings:
    uri: str
    database: str
    max_documents: int = 500

    @classmethod
    def from_env(cls) -> MongoDBSettings:
        return cls(
            uri=_require("MONGODB_URI"),
            database=_require("MONGODB_DATABASE"),
            max_documents=int(os.environ.get("MONGODB_MAX_DOCUMENTS", "500")),
        )
