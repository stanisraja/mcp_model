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
    dsn: str
    statement_timeout_ms: int = 5000
    max_rows: int = 500

    @classmethod
    def from_env(cls) -> PostgresSettings:
        return cls(
            dsn=_require("POSTGRES_DSN"),
            statement_timeout_ms=int(os.environ.get("POSTGRES_STATEMENT_TIMEOUT_MS", "5000")),
            max_rows=int(os.environ.get("POSTGRES_MAX_ROWS", "500")),
        )


@dataclass(frozen=True)
class DynamoDBSettings:
    region: str
    table_prefix: str = ""
    endpoint_url: str | None = None
    max_items: int = 500

    @classmethod
    def from_env(cls) -> DynamoDBSettings:
        return cls(
            region=_require("AWS_REGION"),
            table_prefix=os.environ.get("DYNAMODB_TABLE_PREFIX", ""),
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
