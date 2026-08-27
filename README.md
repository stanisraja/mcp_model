# mcp-dbserver

A self-built [MCP](https://modelcontextprotocol.io) server exposing
read-only, security-scoped access to multiple database engines —
PostgreSQL, DynamoDB, and MongoDB Atlas — for use by AI agents (Claude
Code, Claude Desktop, or any MCP-compatible client).

Status: early scaffolding + Postgres tools in progress. See
[ARCHITECTURE.md](./ARCHITECTURE.md) for the full design, security model,
and current tool inventory, and the phase checklist below for what's done
vs. planned.

## Why this project

A demonstration of applying production-grade, multi-cloud database
architecture discipline — least privilege, explicit guardrails, no
ambient trust — to the AI/agentic tooling space. See
[ARCHITECTURE.md](./ARCHITECTURE.md) for the reasoning behind the
security model in detail.

No employer data, schemas, or business logic (current or former) appears
anywhere in this repo — only public or synthetic data.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in your own, personal, non-work credentials
```

Run the test suite (no live database required — guardrail/allowlist logic
is unit tested against fakes):

```bash
pytest
```

Run the MCP server (stdio transport, for local use with Claude Code /
Claude Desktop):

```bash
mcp-dbserver
```

Tools are only registered for engines whose required environment
variables are set — e.g. with only `POSTGRES_DSN` set, only the Postgres
tools appear.

## Postgres demo dataset

`data/demo_documents.jsonl` is a small, synthetic set of ~30 short
software/infra explainer snippets (written for this project — not from
any employer). To load it into your configured Postgres instance and
generate embeddings locally (via `fastembed`'s ONNX runtime — fully
offline, no external API key needed, and no torch/torchvision dependency):

```bash
pip install -e ".[demo]"
python scripts/load_demo_dataset.py
```

Then verify connectivity and the read-only guardrail against your real
database:

```bash
python scripts/smoke_test_postgres.py
```

This creates a `documents` table (with a pgvector `embedding` column) and
backs the `count_documents`, `list_documents`, and `get_document_by_id`
entries in the Postgres query allowlist, plus `vector_search_postgres`.

Once loaded, sanity-check the data actually made it in and that semantic
search returns sensible (not just error-free) results:

```bash
python scripts/verify_demo_dataset.py
```

## Project layout

```
src/mcp_dbserver/
  guardrails.py       # read-only + row-limit enforcement, engine-agnostic
  allowlist.py         # named, parameterized query registry
  config.py            # env-var credential loading, per engine
  engines/
    postgres.py         # implemented
    dynamodb.py          # planned
    mongodb.py            # planned
  server.py            # MCP entrypoint, registers tools per configured engine
tests/                  # guardrail/allowlist/engine unit tests (no live DB needed)
```

## Roadmap

- [x] Phase 0 — project skeleton
- [x] Phase 1 — architecture & security design (`ARCHITECTURE.md`)
- [ ] Phase 2 — Postgres/pgvector tools against a real demo dataset
- [ ] Phase 3 — DynamoDB
- [ ] Phase 4 — MongoDB Atlas
- [ ] Phase 5 — wired up and tested with a real MCP client
- [ ] Phase 6 — full README with architecture diagram, tool table, "what
      I'd do differently at production scale"
