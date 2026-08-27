"""Runtime read-only guard and connection-param handling in analysis.db.

No database is used: _assert_read_only inspects plain SQL text, and
_connection_params is pure. (These test strings contain write-SQL on purpose;
the security scanner only inspects analysis/ sources, not tests/.)
"""
import pytest

from analysis import db


@pytest.mark.parametrize("query", [
    "SELECT 1",
    "  select * from t",
    "WITH x AS (select 1) SELECT * FROM x",
    "SET statement_timeout = 100",
    "SHOW all",
])
def test_guard_allows_reads(query):
    db._assert_read_only(query, None)  # must not raise


@pytest.mark.parametrize("query", [
    "INSERT INTO t VALUES (1)",
    "update t set x = 1",
    "delete from t",
    "DROP TABLE t",
    "truncate t",
    "CREATE TABLE t (a int)",
    "COPY t FROM stdin",
])
def test_guard_blocks_writes(query):
    with pytest.raises(db.WriteAttemptError):
        db._assert_read_only(query, None)


def test_connection_params_discrete_fields():
    dsn, kwargs = db._connection_params({
        "host": "localhost", "port": 5432, "dbname": "d",
        "user": "u", "password": "p", "statement_timeout_ms": 1000,
    })
    assert dsn is None
    assert kwargs == {"host": "localhost", "port": 5432, "dbname": "d", "user": "u", "password": "p"}


def test_connection_params_dsn_kept_separate():
    dsn, kwargs = db._connection_params({"dsn": "postgresql://u@h/d", "sslmode": "disable"})
    assert dsn == "postgresql://u@h/d"
    assert kwargs == {"sslmode": "disable"}


def test_connection_params_service():
    dsn, kwargs = db._connection_params({"service": "mysvc"})
    assert dsn is None
    assert kwargs == {"service": "mysvc"}


def test_qualified_table_includes_schema():
    from analysis import schema as sc
    naming = sc.Naming(
        ca_table="corporate_actions_{provider}",
        attribute_table="{type}_attribute_values_{provider}",
        materialized_view="mv_{provider}",
        attribute_types=["int"],
        ca_id="{provider}_ca_id",
        db_schema="mdm_ca",
    )
    prov = sc.build_provider_schema("bb", naming)
    assert db._qualified(prov, prov.ca_table).as_string(None) == '"mdm_ca"."corporate_actions_bb"'


def test_attributes_query_casts_value_and_excludes_object():
    from analysis import schema as sc
    naming = sc.Naming(
        ca_table="corporate_actions_{provider}",
        attribute_table="{type}_attribute_values_{provider}",
        materialized_view="mv_{provider}",
        attribute_types=["date", "int", "string", "decimal", "object"],
        ca_id="{provider}_ca_id",
        db_schema="mdm_ca",
    )
    prov = sc.build_provider_schema("bb", naming)
    query, params = db._attributes_query(prov, ["CP_STOCK_OPT"])
    text = query.as_string(None)

    # value cast to text so the UNION of differently-typed tables is valid
    assert 'CAST("value" AS text)' in text
    # one branch per matchable typed table; object is excluded
    assert text.count("UNION ALL") == 3          # 4 tables -> 3 joins
    assert "object_attribute_values_bb" not in text
    assert '"mdm_ca"."int_attribute_values_bb"' in text
    assert params == [["CP_STOCK_OPT"]] * 4


def _schema_for(**col_overrides):
    from analysis import schema as sc
    n = sc.Naming(
        ca_table="corporate_actions_{provider}",
        attribute_table="{type}_attribute_values_{provider}",
        materialized_view="mv_{provider}",
        attribute_types=["int", "string"],
        ca_id="{provider}_ca_id",
        db_schema="mdm_ca",
        **col_overrides,
    )
    provider = "wm" if col_overrides.get("mnemonic") == "" else "bb"
    return sc.build_provider_schema(provider, n)


def test_base_query_selects_present_rule_columns():
    prov = _schema_for()  # bb, ca_id bb_ca_id
    # base table has mnemonic + isin; rules reference mnemonic (base) and CP_STOCK_OPT (attribute)
    text = db._base_query(prov, ["bb_ca_id", "mnemonic", "swift_code", "isin"],
                          ["mnemonic", "CP_STOCK_OPT"]).as_string(None)
    assert '"bb_ca_id" AS ca_id' in text and '"swift_code" AS swift_code' in text
    assert '"mnemonic" AS "mnemonic"' in text       # base column pulled
    assert "CP_STOCK_OPT" not in text               # not a base column -> comes from EAV
    assert "isin" not in text                        # base column not referenced by rules


def test_base_query_matches_rule_columns_case_insensitively():
    # WM: no mnemonic; rules reference CATEGORY which exists as base column "category"
    prov = _schema_for(mnemonic="")
    text = db._base_query(prov, ["wm_ca_id", "swift_code", "category", "isin"],
                          ["CATEGORY", "CP_RATIO"]).as_string(None)
    assert '"category" AS "CATEGORY"' in text        # matched case-insensitively, aliased to rule name
    assert "mnemonic" not in text
    assert '"wm_ca_id" AS ca_id' in text


def test_mv_query_selects_lowercased_rule_columns():
    prov = _schema_for()
    text = db._mv_query(prov, ["CP_STOCK_OPT", "mnemonic"]).as_string(None)
    assert '"cp_stock_opt"' in text and '"mnemonic"' in text
    assert '"bb_ca_id" AS ca_id' in text and '"swift_code" AS swift_code' in text


def test_session_statements_inline_timeout_no_bind_params():
    # SET rejects bind parameters ($1); the timeout must be inlined as a literal.
    texts = [s.as_string(None) for s in db._session_statements(30000)]
    assert "SET statement_timeout = 30000" in texts
    assert "SET idle_in_transaction_session_timeout = 30000" in texts
    for t in texts:
        assert "%s" not in t and "$1" not in t
        db._assert_read_only(t, None)   # still passes the read-only guard
