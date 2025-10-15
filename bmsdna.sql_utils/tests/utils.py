from typing import TYPE_CHECKING
from polars.testing import assert_frame_equal
import polars as pl

from bmsdna.sql_utils.query import sql_quote_value

if TYPE_CHECKING:
    from bmsdna.sql_utils.db_io.source import ImportSource
    from .conftest import DB_Connection


async def execute_compare(
    *,
    source: "ImportSource",
    keys: list[str],
    connection: "DB_Connection",
    delta_path: str,
    target_table: tuple[str, str],
    test_data=True,
):
    from bmsdna.sql_utils import insert_into_table
    from bmsdna.sql_utils.db_io.source import forbidden_cols
    import pandas as pd
    import os
    from bmsdna.sql_utils.query import sql_quote_name

    target_table_sql = sql_quote_name(target_table)

    keys_sql = ", ".join((sql_quote_name(c) for c in keys))

    import duckdb

    def _cast_dt(dt: pl.DataFrame):
        for col in dt.get_columns():
            if isinstance(col.dtype, pl.Datetime) and (col.dtype.time_unit != "ms" or col.dtype.time_zone != "UTC"):
                dt = dt.with_columns(**{col.name: dt[col.name].cast(pl.Datetime("ms", "UTC"))})
        return dt

    def _compare_dfs(df1, df2):
        df1_c = df1.reset_index(drop=True).sort_values(by=keys, ignore_index=True)
        df2_c = df2.reset_index(drop=True).sort_values(by=keys, ignore_index=True)

        assert_frame_equal(_cast_dt(pl.DataFrame(df1_c)), _cast_dt(pl.DataFrame(df2_c)))

    source_cols = [f.column_name for f in source.get_schema() if f.column_name not in forbidden_cols]

    assert len(source_cols) > 0, "nr source columns must be > 0"
    quoted_source_cols = [f'"{c}"' for c in source_cols]
    await insert_into_table(source=source, connection_string=connection.conn_str, target_table=target_table)
    with connection.new_connection() as con:
        df1 = pd.read_sql(
            f"SELECT {', '.join(quoted_source_cols)} FROM {target_table_sql} ORDER BY {keys_sql}",
            con=con,
        )

    with duckdb.connect() as con:
        con.execute(
            f"create view {sql_quote_name(target_table[1])} as select * from delta_scan({sql_quote_value(delta_path)})"
        )
        df2 = con.execute(f"SELECT {', '.join(quoted_source_cols)} FROM {sql_quote_name(target_table[1])}").fetchdf()
    if test_data:
        _compare_dfs(df1, df2)
    else:
        assert df1.shape == df2.shape, "shape must equal"

    with connection.new_connection() as con:
        with con.cursor() as cur:
            cur.execute(f"delete from {target_table_sql} where ascii(cast(newid() as varchar(100)))<ascii('A')")

    await insert_into_table(
        source=source,
        connection_string=connection.conn_str,
        target_table=target_table,
        force=True,
    )
    with connection.new_connection() as con:
        df1 = pd.read_sql(
            f"SELECT {', '.join(quoted_source_cols)} FROM {target_table_sql} ORDER BY {keys_sql}",
            con=con,
        )
    if test_data:
        _compare_dfs(df1, df2)
    else:
        assert df1.shape == df2.shape, "shape must equal"
