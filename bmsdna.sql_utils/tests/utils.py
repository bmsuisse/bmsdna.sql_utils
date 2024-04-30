from typing import TYPE_CHECKING

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
):
    from bmsdna.sql_utils import insert_into_table
    from bmsdna.sql_utils.db_io.source import forbidden_cols
    import pandas as pd
    import os
    from deltalake2db import duckdb_create_view_for_delta
    from bmsdna.sql_utils.query import sql_quote_name

    target_table_sql = sql_quote_name(target_table)

    keys_sql = ", ".join((sql_quote_name(c) for c in keys))

    import duckdb

    def _compare_dfs(df1, df2):
        df1_c = df1.reset_index(drop=True).sort_values(by=keys, ignore_index=True)
        df2_c = df2.reset_index(drop=True).sort_values(by=keys, ignore_index=True)
        return df1_c.compare(df2_c)

    source_cols = [f.column_name for f in source.get_schema() if f.column_name not in forbidden_cols]
    assert len(source_cols) > 0, "nr source columns must be > 0"
    quoted_source_cols = [f'"{c}"' for c in source_cols]
    await insert_into_table(source=source, connection_string=connection.conn_str, target_table=target_table)
    with connection.new_connection() as con:
        df1 = pd.read_sql(
            f'SELECT {", ".join(quoted_source_cols)} FROM {target_table_sql} ORDER BY {keys_sql}',
            con=con,
        )

    with duckdb.connect() as con:
        duckdb_create_view_for_delta(con, delta_path, target_table[1])
        df2 = con.execute(f"SELECT {', '.join(quoted_source_cols)} FROM {sql_quote_name(target_table[1])}").fetchdf()

    comp = _compare_dfs(df1, df2)
    assert comp.empty, comp

    with connection.new_connection() as con:
        con.execute(f"delete from {target_table_sql} where ascii(cast(newid() as varchar(100)))<ascii('A')")

    await insert_into_table(
        source=source,
        connection_string=connection.conn_str,
        target_table=target_table,
        force=True,
    )
    with connection.new_connection() as con:
        df1 = pd.read_sql(
            f'SELECT {", ".join(quoted_source_cols)} FROM {target_table_sql} ORDER BY {keys_sql}',
            con=con,
        )

    comp = _compare_dfs(df1, df2)
    assert comp.empty, comp
