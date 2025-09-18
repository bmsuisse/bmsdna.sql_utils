from typing import TYPE_CHECKING
import pytest

if TYPE_CHECKING:
    from .conftest import DB_Connection
    from pyspark.sql import SparkSession


@pytest.mark.asyncio
async def test_insert_user2(connection: "DB_Connection", spark_session: "SparkSession"):
    from bmsdna.sql_utils.db_io.source_spark import SourceSpark
    import os

    df = spark_session.sql(
        f'select * from delta.`{os.path.abspath("tests/data/user2")}` order by "User_-_iD", __timestamp'
    )

    s = SourceSpark(df)
    from .utils import execute_compare

    await execute_compare(
        source=s,
        keys=["User_-_iD", "__timestamp"],
        connection=connection,
        delta_path="tests/data/user2",
        target_table=("lake_import", "user_from_spark"),
    )


@pytest.mark.asyncio
async def test_insert_user2_json(connection: "DB_Connection", spark_session: "SparkSession"):
    from bmsdna.sql_utils.db_io.source_spark import SourceSpark
    import os

    df = spark_session.sql(
        f'select * from delta.`{os.path.abspath("tests/data/user2")}` order by "User_-_iD", __timestamp'
    )

    s = SourceSpark(df)
    s.use_json_insert = True
    from .utils import execute_compare

    await execute_compare(
        source=s,
        keys=["User_-_iD", "__timestamp"],
        connection=connection,
        delta_path="tests/data/user2",
        target_table=("lake_import", "user_from_spark"),
    )


@pytest.mark.asyncio
# @pytest.mark.skip("invalid characters, must be fixed in lakeapi2sql")
async def test_insert_faker(connection: "DB_Connection", spark_session: "SparkSession"):
    from bmsdna.sql_utils.db_io.source_spark import SourceSpark
    import os

    df = spark_session.sql(f"select * from delta.`{os.path.abspath('tests/data/faker')}`")

    s = SourceSpark(df)
    s.use_json_insert = False
    from .utils import execute_compare

    await execute_compare(
        source=s,
        keys=["id"],
        connection=connection,
        delta_path="tests/data/faker",
        target_table=("lake_import", "faker_from_spark"),
        test_data=False,  # date types / unicode seems to be broken by pandas
    )


@pytest.mark.asyncio
async def test_insert_faker_json(connection: "DB_Connection", spark_session: "SparkSession"):
    from bmsdna.sql_utils.db_io.source_spark import SourceSpark
    import os

    df = spark_session.sql(f"select * from delta.`{os.path.abspath('tests/data/faker')}`")

    s = SourceSpark(df)
    s.use_json_insert = True
    from .utils import execute_compare

    await execute_compare(
        source=s,
        keys=["id"],
        connection=connection,
        delta_path="tests/data/faker",
        target_table=("lake_import", "faker_from_spark"),
        test_data=False,  # date types / unicode seems to be broken by pandas
    )
