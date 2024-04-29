from typing import TYPE_CHECKING
import pytest

if TYPE_CHECKING:
    from .conftest import DB_Connection


@pytest.mark.asyncio
async def test_insert(connection: "DB_Connection"):
    from bmsdna.sql_utils import insert_into_table
    from bmsdna.sql_utils.db_io.delta_source import DeltaSource

    s = DeltaSource("tests/data/user2")
    await insert_into_table(
        source=s, connection_string=connection.conn_str, target_table=("lake_import", "user_not_existing")
    )
    with connection.new_connection() as con:
        with con.cursor() as cur:
            cur.execute("SElect * from lake_import.user_not_existing")
            print(cur.fetchall())
