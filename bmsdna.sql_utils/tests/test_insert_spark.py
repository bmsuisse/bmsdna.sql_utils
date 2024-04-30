from typing import TYPE_CHECKING
import pytest

if TYPE_CHECKING:
    from .conftest import DB_Connection
    from pyspark.sql import SparkSession


@pytest.mark.asyncio
async def test_insert(connection: "DB_Connection", spark_session: "SparkSession"):
    from bmsdna.sql_utils import insert_into_table
    from bmsdna.sql_utils.db_io.source_spark import SourceSpark
    import pandas as pd
    from deltalake2db import duckdb_create_view_for_delta
    import duckdb

    df = spark_session.sql("select * from default.user2")
    s = SourceSpark(df)
    await insert_into_table(
        source=s, connection_string=connection.conn_str, target_table=("lake_import", "user_not_existing")
    )
    with connection.new_connection() as con:
        df1 = pd.read_sql('SELECT * FROM lake_import.user_not_existing ORDER BY "User_-_iD", __timestamp', con=con)

    with duckdb.connect() as con:
        duckdb_create_view_for_delta(con, "tests/data/user2", "user2")
        df2 = con.execute("SELECT * FROM user2").fetchdf()

    comp = df1.compare(df2)
    assert comp.empty, comp

    with connection.new_connection() as con:
        con.execute('delete from lake_import.user_not_existing where "User_-_iD" IN(1,2,4)')

    await insert_into_table(
        source=s, connection_string=connection.conn_str, target_table=("lake_import", "user_not_existing")
    )
    with connection.new_connection() as con:
        df1 = pd.read_sql('SELECT * FROM lake_import.user_not_existing ORDER BY "User_-_iD", __timestamp', con=con)

    comp = df1.compare(df2)
    assert comp.empty, comp
