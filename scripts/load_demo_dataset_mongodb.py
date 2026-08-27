"""Load the synthetic demo dataset (data/demo_documents.jsonl) into MongoDB Atlas.

Mirrors scripts/load_demo_dataset.py exactly -- same dataset, same
fastembed model (BAAI/bge-small-en-v1.5, 384 dims, offline ONNX runtime)
-- so semantic_search_mongodb and semantic_search_documents (pgvector)
are directly comparable against identical data and identical embeddings.

Upserts every document into the `documents` collection, then creates the
Atlas Vector Search index if it doesn't already exist. Index builds are
asynchronous on Atlas -- semantic_search_mongodb may return empty results
for a minute or two after this script finishes; re-run
scripts/verify_demo_dataset_mongodb.py to check when it's ready.

This connects directly with pymongo using the same MongoDBSettings the
MCP server itself uses, so it picks up whatever is in your local .env.
It intentionally does NOT go through MongoDBEngine's read-only surface --
this is an operator-run data-loading script, the one place in this
project that's allowed to write.

Usage:
    python scripts/load_demo_dataset_mongodb.py
"""

from __future__ import annotations

import json
from pathlib import Path

from pymongo import MongoClient, ReplaceOne

from mcp_dbserver.config import MongoDBSettings
from mcp_dbserver.engines.mongodb import MongoDBEngine

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "demo_documents.jsonl"
EMBEDDING_DIM = 384


def _load_documents() -> list[dict]:
    with DATA_FILE.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    from fastembed import TextEmbedding

    settings = MongoDBSettings.from_env()
    documents = _load_documents()
    print(f"Loaded {len(documents)} documents from {DATA_FILE}")

    print("Loading embedding model (BAAI/bge-small-en-v1.5)...")
    model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    embeddings = list(model.embed([doc["body"] for doc in documents]))
    assert len(embeddings[0]) == EMBEDDING_DIM, (
        f"expected {EMBEDDING_DIM}-dim embeddings, got {len(embeddings[0])}"
    )

    client = MongoClient(settings.uri)
    collection = client[settings.database]["documents"]

    operations = [
        ReplaceOne(
            {"id": doc["id"]},
            {"id": doc["id"], "title": doc["title"], "body": doc["body"], "embedding": embedding.tolist()},
            upsert=True,
        )
        for doc, embedding in zip(documents, embeddings)
    ]
    result = collection.bulk_write(operations)
    print(f"Upserted {result.upserted_count + result.modified_count} documents into 'documents'.")

    print("Ensuring Atlas Vector Search index exists...")
    engine = MongoDBEngine(settings)
    engine._client = client  # reuse the connection already open above
    message = engine.ensure_vector_search_index("documents", num_dimensions=EMBEDDING_DIM)
    print(f"  {message}")


if __name__ == "__main__":
    main()
