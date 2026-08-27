# Architecture

## Overview

`mcp-dbserver` is a personal, publicly-shareable MCP (Model Context
Protocol) server that gives an AI agent (Claude Code, Claude Desktop, or
any MCP-compatible client) **read-only, security-scoped** access to
several database engines: PostgreSQL (with pgvector), DynamoDB, and
MongoDB Atlas (with Atlas Vector Search). MySQL is a stated stretch goal
and will follow the same pattern as Postgres if added.

The project exists to demonstrate the same architectural discipline used
for production multi-cloud database estates — least privilege, explicit
guardrails, no ambient trust — applied to an agentic-tooling context
where the "caller" is an LLM instead of a service.

No data, schema, table name, or business logic from any employer (current
or former) appears anywhere in this repo. All datasets are public or
synthetic, generated specifically for this project.

## Supported engines

| Engine | Status | Notes |
|---|---|---|
| PostgreSQL + pgvector | In progress (Phase 2) | Allowlisted queries + cosine-distance vector search |
| DynamoDB | Planned (Phase 3) | `get_item` / `query_table`, table-name allowlist |
| MongoDB Atlas + Vector Search | Planned (Phase 4) | Scoped `find`, `$vectorSearch` |

## Tool inventory

Tools are the only surface an agent ever sees — there is no generic
"run arbitrary query" tool for any engine, on purpose.

| Tool | Engine | Description |
|---|---|---|
| `query_postgres(query_name, params)` | Postgres | Runs one named, allowlisted, parameterized SELECT |
| `list_postgres_queries()` | Postgres | Lists the query names `query_postgres` will accept |
| `vector_search_postgres(table, vector_column, query_embedding, select_columns, limit)` | Postgres | pgvector cosine-distance nearest-neighbor search |
| `get_dynamodb_item(table, key)` | DynamoDB | Planned |
| `query_dynamodb_table(table, key_condition, limit)` | DynamoDB | Planned |
| `list_collections_mongodb()` | MongoDB | Planned |
| `vector_search_mongodb(collection, index, query_embedding, limit)` | MongoDB | Planned |

## Security model

This is the part of the project that's meant to differentiate it from a
typical "point an agent at a database" demo. Every layer below is
deliberate, and each is independently sufficient to stop a write —
they're stacked so that no single bug is enough to break the read-only
guarantee.

### 1. Read-only only, in v1

No write, update, or delete tool is registered for any engine. This is a
deliberate scope decision, not a missing feature: an agent that can only
read cannot cause data loss, and it removes an entire class of
authorization bugs (partial-write races, missing-confirmation flows,
prompt-injection-driven destructive actions) from consideration entirely.
A write-capable v2, if it ever exists, is a separate, explicitly-scoped
project with its own threat model — not an incremental unlock of this one.

### 2. No raw queries from the agent — named allowlisted queries only

The agent never sends free-form SQL, a MongoDB filter document, or a
DynamoDB key condition expression directly. For Postgres, every query the
agent can run is a pre-registered `AllowlistedQuery` (`allowlist.py`): a
fixed SQL template with a fixed parameter list, validated to be read-only
at *registration time* (`AllowlistedQuery.__post_init__` calls
`assert_read_only_sql`, so a write template can't even be added to the
allowlist by a coding mistake). The agent picks a query by name and
supplies parameter *values*, which are bound through the driver's native
parameterization (`psycopg` placeholders) — never string interpolation,
so SQL injection through a parameter value isn't a meaningful attack
surface here.

The same pattern will carry over to DynamoDB (table-name allowlist plus
typed key conditions) and MongoDB (collection allowlist plus a restricted
filter/projection shape with no `$where`/raw JS) in Phases 3–4.

### 3. Defense in depth at the query-execution layer

Even though every query reaching the engine already came from the
allowlist, `guardrails.py` re-validates it independently before
execution:

- `assert_read_only_sql` rejects anything that isn't a `SELECT`/`WITH`
  statement, rejects stacked statements (`;`-separated), and rejects a
  fixed set of forbidden keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`,
  `ALTER`, `TRUNCATE`, `GRANT`, `CREATE`, `COPY`, ...) as whole words —
  not substrings, so a column named `update_count` isn't a false
  positive.
- `enforce_row_limit_sql` clamps or injects a `LIMIT` clause so a query
  can't return an unbounded result set, regardless of what the query
  template or the caller's requested limit says. The effective cap is
  `min(query.max_rows, engine_settings.max_rows)` — the server's
  configured ceiling always wins.
- Every Postgres connection additionally runs
  `SET default_transaction_read_only = on` and a `statement_timeout`
  before any query executes, so even a guardrail bug can't produce a
  write or a runaway query at the database level.

This is belt-and-suspenders on purpose: the allowlist should be
sufficient on its own, but the execution-layer checks mean a mistake in
one allowlist entry doesn't become a live vulnerability.

### 4. Credential handling

- All credentials are read from environment variables (`config.py`), via
  `python-dotenv` for local development. `.env` is gitignored; only
  `.env.example` (placeholder values) is committed.
- Each engine's settings (`PostgresSettings`, `DynamoDBSettings`,
  `MongoDBSettings`) are constructed lazily and only when that engine's
  tools are registered — a missing credential means that engine's tools
  simply aren't exposed, not a crash.
- Credentials are never logged. No tool or engine method logs connection
  strings, parameter values, or raw query results at a level above
  debug, and none of that ever includes the DSN/URI itself.
- The database role/user behind each connection should itself be
  provisioned read-only wherever the engine supports it (a Postgres role
  with only `SELECT` granted, a DynamoDB IAM policy scoped to
  `dynamodb:GetItem`/`Query`, a MongoDB Atlas database user with the
  built-in `read` role) — this is a deployment-time requirement, not
  something the code can enforce, and is called out explicitly here so
  it isn't skipped.

### 5. Client ↔ server authentication (design intent, not yet implemented)

For local development, the MCP server runs over stdio, launched directly
by the client (Claude Code / Claude Desktop) as a subprocess — there is
no network boundary to authenticate across, and the OS process boundary
is the trust boundary.

For a real deployment (the server running as a long-lived HTTP/SSE
process reachable by more than one local client), the intended design is:

- Per-client **API keys**, issued out-of-band, sent as a bearer token on
  every MCP request and checked before any tool call is dispatched.
- Keys scoped per-engine (a client can be issued a Postgres-only key),
  mirroring the tool-registration pattern already used for missing
  credentials.
- TLS termination in front of the server; no plaintext HTTP in any
  non-local deployment.
- mTLS is a plausible upgrade for a tighter-trust deployment (e.g.
  service-to-service, not human-in-the-loop) but is overkill for a
  single-operator portfolio deployment and isn't planned for v1.

This is documented here so the gap is visible and deliberate, not
accidental — the v1 deployment target is "local stdio only," and this
section is what changes first if that target changes.

## Open design decisions

- **MySQL**: explicitly out of scope for v1; if added, it follows the
  same allowlist + guardrail pattern as Postgres.
- **Observability**: no query logging/metrics yet. Before any networked
  deployment, at minimum: which query name was called, by when, and
  whether it succeeded (never parameter values or row contents).
- **Rate limiting**: not implemented. Relevant once the server is
  reachable by more than a single local stdio client.
- **DynamoDB/MongoDB allowlist shape**: the Postgres allowlist is a fixed
  SQL template per name. The equivalent for DynamoDB (key-condition
  shape) and MongoDB (filter/projection shape) needs its own validation
  design in Phases 3–4 — likely a typed schema per allowlisted operation
  rather than accepting an open-ended filter dict, to avoid quietly
  reintroducing "raw query" access through a permissive filter shape.
