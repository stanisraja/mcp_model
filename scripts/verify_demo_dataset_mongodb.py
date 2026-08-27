"""Sanity-check the loaded MongoDB demo dataset: count, list, semantic search.

Mirrors scripts/verify_demo_dataset.py exactly, including the same
"how do I scale database reads across more servers" query with zero
keyword overlap with any document body -- run both scripts and compare
their top-5 results directly (same data, same embedding model, two
different vector search implementations).

Run this after scripts/load_demo_dataset_mongodb.py. If semantic search
returns an empty list, the Atlas Vector Search index is probably still
building (can take a minute or two) -- wait and re-run.

Usage:
    python scripts/verify_demo_dataset_mongodb.py
"""

from __future__ import annotations

from mcp_dbserver.config import MongoDBSettings
from mcp_dbserver.engines.mongodb import MongoDBEngine

EXPECTED_DOCUMENT_COUNT = 30
SEARCH_QUERY = "how do I scale database reads across more servers"


def main() -> None:
    settings = MongoDBSettings.from_env()
    engine = MongoDBEngine(settings)

    print("1. count_documents...")
    actual_count = engine.count_documents("documents")
    print(f"   {actual_count} documents")
    if actual_count != EXPECTED_DOCUMENT_COUNT:
        print(
            f"   WARNING: expected {EXPECTED_DOCUMENT_COUNT} -- "
            "did scripts/load_demo_dataset_mongodb.py run to completion?"
        )

    print("\n2. list_documents (first 5 of up to 100)...")
    docs = engine.list_documents("documents")
    for doc in docs[:5]:
        print(f"   [{doc['id']}] {doc['title']}")
    print(f"   ... {len(docs)} documents returned")

    print(f"\n3. semantic_search_mongodb for: {SEARCH_QUERY!r}")
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    query_embedding = next(model.embed([SEARCH_QUERY])).tolist()

    results = engine.semantic_search("documents", query_embedding, limit=5)
    if not results:
        print("   No results -- the Atlas Vector Search index is likely still building. Wait and re-run.")
    for doc in results:
        print(f"   score={doc['score']:.4f}  [{doc['id']}] {doc['title']}")

    print("\nVerification complete.")


if __name__ == "__main__":
    main()
