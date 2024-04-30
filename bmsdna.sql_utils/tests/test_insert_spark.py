from typing import TYPE_CHECKING
import pytest

if TYPE_CHECKING:
    from .conftest import DB_Connection
    from pyspark.sql import SparkSession


@pytest.mark.asyncio
async def test_insert(connection: "DB_Connection", spark_session: "SparkSession"):
    from bmsdna.sql_utils import insert_into_table
    from bmsdna.sql_utils.db_io.source_spark import SourceSpark
    from bmsdna.sql_utils.db_io.source import forbidden_cols
    import pandas as pd
    from deltalake2db import duckdb_create_view_for_delta

    import duckdb

    def _compare_dfs(df1, df2):
        df1_c = df1.reset_index(drop=True).sort_values(by=["User_-_iD", "__timestamp"], ignore_index=True)
        df2_c = df2.reset_index(drop=True).sort_values(by=["User_-_iD", "__timestamp"], ignore_index=True)
        return df1_c.compare(df2_c)

    df = spark_session.sql("select * from default.user2")
    source_cols = [f for f in df.columns if f not in forbidden_cols]
    quoted_source_cols = [f"{c}" for c in source_cols]
    s = SourceSpark(df)
    await insert_into_table(
        source=s, connection_string=connection.conn_str, target_table=("lake_import", "user_not_existing")
    )
    with connection.new_connection() as con:
        df1 = pd.read_sql(
            f'SELECT {", ".join(quoted_source_cols)} FROM lake_import.user_not_existing ORDER BY "User_-_iD", __timestamp',
            con=con,
        )

    with duckdb.connect() as con:
        duckdb_create_view_for_delta(con, "tests/data/user2", "user2")
        df2 = con.execute(f"SELECT {', '.join(quoted_source_cols)} FROM user2").fetchdf()

    comp = _compare_dfs(df1, df2)
    assert comp.empty, comp

    with connection.new_connection() as con:
        con.execute('delete from lake_import.user_not_existing where "User_-_iD" IN(1,2,4)')

    await insert_into_table(
        source=s, connection_string=connection.conn_str, target_table=("lake_import", "user_not_existing")
    )
    with connection.new_connection() as con:
        df1 = pd.read_sql(
            f'SELECT {", ".join(quoted_source_cols)} FROM lake_import.user_not_existing ORDER BY "User_-_iD", __timestamp',
            con=con,
        )

    comp = _compare_dfs(df1, df2)
    assert comp.empty, comp
