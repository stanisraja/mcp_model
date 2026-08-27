import pytest

from mcp_dbserver.guardrails import (
    QueryGuardError,
    assert_read_only_sql,
    clamp_limit,
    enforce_row_limit_sql,
)


class TestAssertReadOnlySql:
    def test_allows_plain_select(self):
        assert_read_only_sql("SELECT * FROM widgets")

    def test_allows_cte(self):
        assert_read_only_sql("WITH recent AS (SELECT 1) SELECT * FROM recent")

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO widgets VALUES (1)",
            "UPDATE widgets SET name = 'x'",
            "DELETE FROM widgets",
            "DROP TABLE widgets",
            "ALTER TABLE widgets ADD COLUMN x int",
            "TRUNCATE widgets",
            "GRANT ALL ON widgets TO public",
            "CREATE TABLE widgets (id int)",
            "SELECT * FROM widgets; DROP TABLE widgets",
            "",
            "   ",
        ],
    )
    def test_rejects_writes_and_multi_statements(self, sql):
        with pytest.raises(QueryGuardError):
            assert_read_only_sql(sql)

    def test_rejects_keyword_disguised_as_identifier_is_fine_but_write_keyword_is_not(self):
        # A column literally named "update_count" should not be rejected --
        # the check is word-boundary based, not substring based.
        assert_read_only_sql("SELECT update_count FROM widgets")


class TestEnforceRowLimitSql:
    def test_appends_limit_when_absent(self):
        result = enforce_row_limit_sql("SELECT * FROM widgets", max_rows=100)
        assert result == "SELECT * FROM widgets LIMIT 100"

    def test_caps_an_existing_limit_that_exceeds_max(self):
        result = enforce_row_limit_sql("SELECT * FROM widgets LIMIT 10000", max_rows=100)
        assert "LIMIT 100" in result
        assert "10000" not in result

    def test_leaves_a_smaller_existing_limit_untouched(self):
        result = enforce_row_limit_sql("SELECT * FROM widgets LIMIT 5", max_rows=100)
        assert "LIMIT 5" in result

    def test_rejects_out_of_range_max_rows(self):
        with pytest.raises(QueryGuardError):
            enforce_row_limit_sql("SELECT 1", max_rows=0)
        with pytest.raises(QueryGuardError):
            enforce_row_limit_sql("SELECT 1", max_rows=999_999)


class TestClampLimit:
    def test_defaults_when_none(self):
        assert clamp_limit(None, max_rows=500) == 500

    def test_clamps_above_max(self):
        assert clamp_limit(10_000, max_rows=500) == 500

    def test_passes_through_within_bounds(self):
        assert clamp_limit(10, max_rows=500) == 10

    def test_rejects_non_positive(self):
        with pytest.raises(QueryGuardError):
            clamp_limit(0, max_rows=500)
        with pytest.raises(QueryGuardError):
            clamp_limit(-5, max_rows=500)
