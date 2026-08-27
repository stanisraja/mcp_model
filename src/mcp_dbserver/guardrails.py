"""Engine-agnostic read-only enforcement shared by every tool.

Defense in depth, in this order:
  1. Tools never accept raw, free-form SQL/queries from the agent — only a
     named, allowlisted query (see `allowlist.py`) with typed parameters.
  2. Even so, every allowlisted statement is re-validated here before it
     runs: it must parse as a read-only statement, and a row limit is
     enforced regardless of what the statement itself requests.
"""

from __future__ import annotations

import re

DEFAULT_MAX_ROWS = 500
HARD_MAX_ROWS = 5000

_READ_ONLY_PREFIXES = ("select", "with")

_FORBIDDEN_KEYWORDS = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "grant",
    "revoke",
    "create",
    "replace",
    "merge",
    "call",
    "exec",
    "execute",
    "vacuum",
    "copy",
    "into outfile",
)

_LIMIT_RE = re.compile(r"\blimit\s+(\d+)\b", re.IGNORECASE)


class QueryGuardError(ValueError):
    """Raised when a query fails a read-only or row-limit guardrail check."""


def assert_read_only_sql(sql: str) -> None:
    """Reject anything that isn't a plain read-only SELECT/CTE statement."""
    normalized = sql.strip().lower()
    if not normalized:
        raise QueryGuardError("Empty query is not allowed")
    if not normalized.startswith(_READ_ONLY_PREFIXES):
        raise QueryGuardError("Only SELECT / WITH statements are permitted")
    if ";" in normalized.rstrip(";"):
        raise QueryGuardError("Multiple statements are not permitted")
    for keyword in _FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", normalized):
            raise QueryGuardError(f"Forbidden keyword detected: {keyword!r}")


def enforce_row_limit_sql(sql: str, max_rows: int = DEFAULT_MAX_ROWS) -> str:
    """Return `sql` with a LIMIT clause clamped to at most `max_rows`.

    If the statement already has a LIMIT, it is capped down to max_rows;
    if it has none, one is appended.
    """
    if max_rows <= 0 or max_rows > HARD_MAX_ROWS:
        raise QueryGuardError(f"max_rows must be between 1 and {HARD_MAX_ROWS}")

    match = _LIMIT_RE.search(sql)
    if match:
        requested = int(match.group(1))
        capped = min(requested, max_rows)
        return _LIMIT_RE.sub(f"LIMIT {capped}", sql, count=1)

    stripped = sql.rstrip().rstrip(";")
    return f"{stripped} LIMIT {max_rows}"


def clamp_limit(requested: int | None, max_rows: int = DEFAULT_MAX_ROWS) -> int:
    """Clamp a caller-supplied item/row limit (e.g. for DynamoDB/MongoDB) to a safe bound."""
    if requested is None:
        return max_rows
    if requested <= 0:
        raise QueryGuardError("limit must be a positive integer")
    return min(requested, max_rows)
