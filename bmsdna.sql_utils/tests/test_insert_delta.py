from typing import TYPE_CHECKING
import pytest

if TYPE_CHECKING:
    from .conftest import DB_Connection


@pytest.mark.asyncio
async def test_logging(connection: "DB_Connection"):
    from bmsdna.sql_utils.db_io.db_logging import init_logging, insert_into_log

    with connection.new_connection() as con:
        init_logging(con)

        with con.cursor() as cur:
            cur.execute("select column_name from information_schema.columns where table_name='_log'")
            col_names = [c[0] for c in cur.fetchall()]
        assert "table_name" in col_names
        assert "type" in col_names

        insert_into_log(con, ("dbo", "i_want_log"), "skip_load")
        from bmsdna.sql_utils.db_io.db_logging import warned_logging

        assert not warned_logging

        with con.cursor() as cur:
            cur.execute("select count(*) as cnt FROM lake_import._log")
            cnt = cur.fetchone()[0]
            assert cnt > 0


@pytest.mark.asyncio
async def test_insert(connection: "DB_Connection"):
    from bmsdna.sql_utils import insert_into_table
    from bmsdna.sql_utils.db_io.delta_source import DeltaSource
    import pandas as pd
    from deltalake2db import duckdb_create_view_for_delta
    import duckdb

    s = DeltaSource("tests/data/user2")
    await insert_into_table(
        source=s, connection_string=connection.conn_str, target_table=("lake_import", "user_not_existing")
    )
    with connection.new_connection() as con:
        df1 = pd.read_sql('SELECT * FROM lake_import.user_not_existing ORDER BY "User_-_iD", __timestamp', con=con)

    with duckdb.connect() as con:
        duckdb_create_view_for_delta(con, "tests/data/user2", "user2")
        df2 = con.execute('SELECT * FROM user2 ORDER BY "User_-_iD", __timestamp').fetchdf()

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
