"""Read-only Postgres adapter. The only module that touches a database.

Four layers keep it read-only: (1) the recommended setup is a SELECT-only role;
(2) the session is opened read-only so the server itself rejects any write;
(3) statement and idle timeouts bound every query; (4) the module issues only
SELECT — enforced by tests/test_analysis_security.py, which fails the build if
any data-modifying keyword ever appears here.

Identifiers come from the validated ProviderSchema and are still passed through
psycopg.sql.Identifier for defense in depth; values go through parameters.
"""
from typing import Dict, Iterable, Iterator, List

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .schema import ProviderSchema, validate_identifier


def connect(config: Dict):
    """Open a read-only connection from a [connection] config block."""
    conn_cfg = config.get("connection", {})
    dsn = conn_cfg.get("dsn")
    kwargs = {}
    if "service" in conn_cfg:
        kwargs["service"] = conn_cfg["service"]

    conn = psycopg.connect(dsn, **kwargs) if dsn else psycopg.connect(**kwargs)
    conn.read_only = True
    conn.autocommit = True

    timeout = int(conn_cfg.get("statement_timeout_ms", 30000))
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SET default_transaction_read_only = on"))
        cur.execute(sql.SQL("SET statement_timeout = %s"), (timeout,))
        cur.execute(sql.SQL("SET idle_in_transaction_session_timeout = %s"), (timeout,))
    return conn


def fetch_base(conn, schema: ProviderSchema) -> Iterator[Dict]:
    """Yield {ca_id, mnemonic, swift_code} for every CA."""
    query = sql.SQL(
        "SELECT {ca} AS ca_id, {mn} AS mnemonic, {sw} AS swift_code FROM {tbl}"
    ).format(
        ca=sql.Identifier(schema.ca_id),
        mn=sql.Identifier(schema.mnemonic),
        sw=sql.Identifier(schema.swift_code),
        tbl=sql.Identifier(schema.ca_table),
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query)
        yield from cur


def fetch_attributes(conn, schema: ProviderSchema, columns: Iterable[str]) -> Iterator[Dict]:
    """Yield {ca_id, attribute, value} across the matchable typed tables,
    restricted to the attributes the ruleset actually references."""
    wanted: List[str] = list(columns)
    if not wanted:
        return

    parts, params = [], []
    for table_name in schema.matchable_attribute_tables().values():
        parts.append(
            sql.SQL(
                "SELECT {ca} AS ca_id, {attr} AS attribute, {val} AS value "
                "FROM {tbl} WHERE {attr} = ANY(%s)"
            ).format(
                ca=sql.Identifier(schema.ca_id),
                attr=sql.Identifier(schema.attribute_name),
                val=sql.Identifier(schema.attribute_value),
                tbl=sql.Identifier(table_name),
            )
        )
        params.append(wanted)

    query = sql.SQL(" UNION ALL ").join(parts)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        yield from cur


def fetch_mv(conn, schema: ProviderSchema, columns: Iterable[str]) -> Iterator[Dict]:
    """Yield one condensed row per CA from the materialized view. MV columns are
    the lowercased rule column names; caller remaps them (records.build_records_from_mv)."""
    lowers = []
    for col in columns:
        low = col.lower()
        if low == schema.mnemonic:
            continue  # selected explicitly below
        lowers.append(validate_identifier(low, "mv_column"))

    select_cols = [
        sql.SQL("{} AS ca_id").format(sql.Identifier(schema.ca_id)),
        sql.SQL("{} AS mnemonic").format(sql.Identifier(schema.mnemonic)),
        sql.SQL("{} AS swift_code").format(sql.Identifier(schema.swift_code)),
    ]
    select_cols.extend(sql.Identifier(low) for low in lowers)

    query = sql.SQL("SELECT {cols} FROM {tbl}").format(
        cols=sql.SQL(", ").join(select_cols),
        tbl=sql.Identifier(schema.materialized_view),
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query)
        yield from cur
