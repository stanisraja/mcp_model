"""Named, parameterized query allowlist.

Agents never send raw SQL. They call a tool with a `query_name` (from this
registry) plus typed parameters; the server looks up the matching template,
binds parameters positionally/by-name through the driver's own
parameterization (never string interpolation), and runs it under the
guardrails in `guardrails.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .guardrails import assert_read_only_sql


@dataclass(frozen=True)
class AllowlistedQuery:
    name: str
    description: str
    sql: str
    params: tuple[str, ...] = field(default_factory=tuple)
    max_rows: int = 500

    def __post_init__(self) -> None:
        assert_read_only_sql(self.sql)


class QueryAllowlist:
    """A registry of named queries a given engine instance is permitted to run."""

    def __init__(self) -> None:
        self._queries: dict[str, AllowlistedQuery] = {}

    def register(self, query: AllowlistedQuery) -> None:
        if query.name in self._queries:
            raise ValueError(f"Query {query.name!r} is already registered")
        self._queries[query.name] = query

    def get(self, name: str) -> AllowlistedQuery:
        try:
            return self._queries[name]
        except KeyError as exc:
            raise KeyError(f"Query {name!r} is not in the allowlist") from exc

    def names(self) -> list[str]:
        return sorted(self._queries)
