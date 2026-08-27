"""Sanity-check the loaded demo dataset: row count, list_documents, vector_search_postgres.

Run this after scripts/load_demo_dataset.py to confirm the data actually
made it in and semantic search returns sensible results -- not just that
queries execute without error.

Usage:
    python scripts/verify_demo_dataset.py
"""

from __future__ import annotations

from mcp_dbserver.config import PostgresSettings
from mcp_dbserver.engines.postgres import PostgresEngine, build_default_allowlist

EXPECTED_DOCUMENT_COUNT = 30

# A query with no exact keyword overlap with any document body -- if
# vector search is working semantically (not falling back to something
# keyword-like), this should still surface "Read replicas" and/or
# "Sharding" near the top, since both are about scaling database reads.
SEARCH_QUERY = "how do I scale database reads across more servers"


def main() -> None:
    settings = PostgresSettings.from_env()
    engine = PostgresEngine(settings, build_default_allowlist())

    print("1. count_documents...")
    count_rows = engine.run_query("count_documents")
    actual_count = count_rows[0]["document_count"]
    print(f"   {actual_count} documents")
    if actual_count != EXPECTED_DOCUMENT_COUNT:
        print(
            f"   WARNING: expected {EXPECTED_DOCUMENT_COUNT} -- "
            "did scripts/load_demo_dataset.py run to completion?"
        )

    print("\n2. list_documents (first 5 of up to 100)...")
    doc_rows = engine.run_query("list_documents")
    for row in doc_rows[:5]:
        print(f"   [{row['id']}] {row['title']}")
    print(f"   ... {len(doc_rows)} rows returned")

    print(f"\n3. vector_search_postgres for: {SEARCH_QUERY!r}")
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    query_embedding = next(model.embed([SEARCH_QUERY])).tolist()

    results = engine.vector_search(
        table="documents",
        vector_column="embedding",
        query_embedding=query_embedding,
        select_columns=["id", "title"],
        limit=5,
    )
    for row in results:
        print(f"   distance={row['distance']:.4f}  [{row['id']}] {row['title']}")

    distances = [row["distance"] for row in results]
    if distances != sorted(distances):
        print("   WARNING: results are not sorted by ascending distance -- check the ORDER BY")
    else:
        print("   OK: results are ordered nearest-first")

    print("\nVerification complete.")


if __name__ == "__main__":
    main()
