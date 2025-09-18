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
            cnt = cur.fetchall()[0][0]
            assert cnt > 0

    with connection.new_connection() as con:
        init_logging(con)  # do it twice, should not reset logs

        with con.cursor() as cur:
            cur.execute("select count(*) as cnt FROM lake_import._log")
            cnt = cur.fetchall()[0][0]
            assert cnt > 0


@pytest.mark.asyncio
async def test_insert_user2_delta(connection: "DB_Connection"):
    from bmsdna.sql_utils.db_io.delta_source import DeltaSource

    s = DeltaSource("tests/data/user2", use_json_insert=True)
    from .utils import execute_compare

    await execute_compare(
        source=s,
        keys=["User_-_iD", "__timestamp"],
        connection=connection,
        delta_path="tests/data/user2",
        target_table=("lake_import", "user_delta"),
    )


@pytest.mark.asyncio
async def test_insert_user2_delta_json(connection: "DB_Connection"):
    from bmsdna.sql_utils.db_io.delta_source import DeltaSource

    s = DeltaSource("tests/data/user2")
    s.use_json_insert = True
    from .utils import execute_compare

    await execute_compare(
        source=s,
        keys=["User_-_iD", "__timestamp"],
        connection=connection,
        delta_path="tests/data/user2",
        target_table=("lake_import", "user_delta"),
    )


@pytest.mark.asyncio
async def test_insert_faker_delta_json(connection: "DB_Connection"):
    from bmsdna.sql_utils.db_io.delta_source import DeltaSource

    s = DeltaSource("tests/data/faker")
    s.use_json_insert = True
    from .utils import execute_compare

    await execute_compare(
        source=s,
        keys=["id"],
        connection=connection,
        delta_path="tests/data/faker",
        target_table=("lake_import", "faker_delta"),
        test_data=False,  # date types / unicode seems to be broken by pandas
    )


@pytest.mark.asyncio
# @pytest.mark.skip("invalid characters, must be fixed in lakeapi2sql")
async def test_insert_faker_delta(connection: "DB_Connection"):
    from bmsdna.sql_utils.db_io.delta_source import DeltaSource

    s = DeltaSource("tests/data/faker")
    from .utils import execute_compare

    await execute_compare(
        source=s,
        keys=["id"],
        connection=connection,
        delta_path="tests/data/faker",
        target_table=("lake_import", "faker_delta"),
        test_data=False,  # date types / unicode seems to be broken by pandas
    )
