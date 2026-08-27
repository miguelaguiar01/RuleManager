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
