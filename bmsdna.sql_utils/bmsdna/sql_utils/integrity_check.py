from typing import Literal, TYPE_CHECKING, cast, Any
from bmsdna.sql_utils.query import sql_quote_name
from bmsdna.sql_utils.result import make_class_from_cursor

if TYPE_CHECKING:
    from bmsdna.sql_utils.dbapi import Connection


def get_integrity_sum_sql_all(
    sql_table_name: str | tuple[str, str], partition_columns: list[str], dialect: Literal["mssql", "duckdb_polars"]
):
    division_operator = "/" if dialect == "mssql" else "//"
    if len(partition_columns) >= 1:
        part_cols = ", ".join(sql_quote_name(pc) for pc in partition_columns)
        sql = f"SELECT {part_cols}, SUM(integrity_value{division_operator}100000000) as integrity_sum, COUNT(*) AS _count FROM {sql_quote_name(sql_table_name)} GROUP BY {part_cols}"
    else:
        sql = f"SELECT SUM(integrity_value{division_operator}100000000) as integrity_sum, COUNT(*) AS _count FROM {sql_quote_name(sql_table_name)}"
    return sql


def get_integrity_sum_all_mssql(
    conn: "Connection",
    sql_table_name: tuple[str, str],
    partition_columns: list[str],
) -> list[dict]:
    sql = get_integrity_sum_sql_all(sql_table_name, partition_columns, dialect="mssql")
    with conn.cursor() as cur:
        cur.execute(sql)
        return make_class_from_cursor(dict, cast(Any, cur.description), cur.fetchall())
