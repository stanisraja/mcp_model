"""Load the synthetic demo dataset (data/demo_documents.jsonl) into Postgres.

Creates the pgvector extension and a `documents` table if they don't
already exist, generates a local embedding for each document's body via
sentence-transformers (all-MiniLM-L6-v2, 384 dims, runs fully offline --
no external API calls or keys needed), and upserts every row.

This connects directly with psycopg using the same PostgresSettings the
MCP server itself uses (POSTGRES_DSN or the POSTGRES_AUTH_MODE=iam
variables), so it picks up whatever is in your local .env. It intentionally
does NOT go through PostgresEngine / the guardrails -- those exist to keep
the *agent* read-only; this is an operator-run data-loading script, the
one place in this project that's allowed to write.

Usage:
    python scripts/load_demo_dataset.py
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg

from mcp_dbserver.config import PostgresSettings
from mcp_dbserver.engines.postgres import PostgresEngine

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "demo_documents.jsonl"
EMBEDDING_DIM = 384

_CREATE_TABLE_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    embedding VECTOR(384) NOT NULL
);
"""

_UPSERT_SQL = """
INSERT INTO documents (id, title, body, embedding)
VALUES (%(id)s, %(title)s, %(body)s, %(embedding)s)
ON CONFLICT (id) DO UPDATE
SET title = EXCLUDED.title, body = EXCLUDED.body, embedding = EXCLUDED.embedding;
"""


def _load_documents() -> list[dict]:
    with DATA_FILE.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _connect_for_write(settings: PostgresSettings) -> psycopg.Connection:
    # Reuses the same connection settings/IAM-token logic as the read-only
    # engine, but a plain connection (no `default_transaction_read_only`)
    # since this script is the operator-run loader, not an agent tool.
    engine = PostgresEngine(settings)
    if settings.auth_mode == "iam":
        return psycopg.connect(
            host=settings.host,
            port=settings.port,
            dbname=settings.dbname,
            user=settings.user,
            password=engine._generate_iam_auth_token(),
            sslmode=settings.sslmode,
        )
    return psycopg.connect(settings.dsn)


def main() -> None:
    from sentence_transformers import SentenceTransformer

    settings = PostgresSettings.from_env()
    documents = _load_documents()
    print(f"Loaded {len(documents)} documents from {DATA_FILE}")

    print("Loading embedding model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = model.encode([doc["body"] for doc in documents], normalize_embeddings=True)
    assert embeddings.shape[1] == EMBEDDING_DIM, (
        f"expected {EMBEDDING_DIM}-dim embeddings, got {embeddings.shape[1]}"
    )

    with _connect_for_write(settings) as conn, conn.cursor() as cur:
        cur.execute(_CREATE_TABLE_SQL)
        for doc, embedding in zip(documents, embeddings):
            cur.execute(
                _UPSERT_SQL,
                {
                    "id": doc["id"],
                    "title": doc["title"],
                    "body": doc["body"],
                    "embedding": embedding.tolist(),
                },
            )
        conn.commit()

    print(f"Upserted {len(documents)} rows into documents.")


if __name__ == "__main__":
    main()
