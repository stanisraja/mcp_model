import pytest

from mcp_dbserver.allowlist import AllowlistedQuery, QueryAllowlist
from mcp_dbserver.guardrails import QueryGuardError


def test_registering_a_write_query_is_rejected_at_construction_time():
    with pytest.raises(QueryGuardError):
        AllowlistedQuery(name="evil", description="", sql="DELETE FROM widgets")


def test_register_and_lookup_round_trip():
    allowlist = QueryAllowlist()
    query = AllowlistedQuery(name="widgets", description="all widgets", sql="SELECT * FROM widgets")
    allowlist.register(query)

    assert allowlist.get("widgets") is query
    assert allowlist.names() == ["widgets"]


def test_duplicate_registration_is_rejected():
    allowlist = QueryAllowlist()
    allowlist.register(AllowlistedQuery(name="widgets", description="", sql="SELECT 1"))
    with pytest.raises(ValueError):
        allowlist.register(AllowlistedQuery(name="widgets", description="", sql="SELECT 2"))


def test_unknown_query_name_is_rejected():
    allowlist = QueryAllowlist()
    with pytest.raises(KeyError):
        allowlist.get("does_not_exist")
