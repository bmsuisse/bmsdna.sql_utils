import pytest
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class DB_Connection:
    def __init__(self):
        import logging

        logging.getLogger("bmsdna.sql_utils").setLevel(logging.DEBUG)
        logging.getLogger("lakeapi2sql").setLevel(logging.DEBUG)
        logging.getLogger("tiberius").setLevel(logging.DEBUG)
        import shutil

        if os.path.exists("tests/_data"):
            shutil.rmtree("tests/_data")
        os.makedirs("tests/_data", exist_ok=True)
        from bmsdna.sql_utils.query import build_connection_string

        conn_str = build_connection_string(
            os.getenv("ODBC_MASTER_CONN", None)
            or {
                "server": "127.0.0.1,1444",
                "database": "master",
                "ENCRYPT": "yes",
                "TrustServerCertificate": "Yes",
                "UID": "sa",
                "PWD": "MyPass@word4tests",
                "MultipleActiveResultSets": "True",
            },
            odbc=False,
        )
        self.conn_str_master = conn_str
        self.db_name = "sql_utils_test_" + str(os.getpid()) + "_" + str(os.urandom(4).hex())
        from bmsdna.sql_utils.query import get_connection

        with get_connection(conn_str, autocommit=True, timeout=30) as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        """DECLARE @kill varchar(8000) = '';  
    SELECT @kill = @kill + 'kill ' + CONVERT(varchar(5), session_id) + ';'  
    FROM sys.dm_exec_sessions
    WHERE database_id  = db_id(?)

    EXEC(@kill);""",
                        (self.db_name,),
                    )
                    cursor.execute(f" drop DATABASE if exists {self.db_name}")
                    cursor.execute(f"CREATE DATABASE {self.db_name}")
                except Exception as e:
                    logger.error("Error drop creating db", exc_info=e)
            with conn.cursor() as cursor:
                cursor.execute(f"USE {self.db_name}")
            with open("tests/sqls/init.sql", encoding="utf-8-sig") as f:
                sqls = f.read().replace("\r\n", "\n").split("\nGO\n")
                for sql in sqls:
                    with conn.cursor() as cursor:
                        cursor.execute(sql)
            conn.commit()
            conn.close()

        self.conn_str = conn_str.replace("database=master", "database=" + self.db_name).replace(
            "Database=master", "Database=" + self.db_name
        )
        if self.db_name not in self.conn_str:
            raise ValueError("Database not created correctly")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def new_connection(self):
        from bmsdna.sql_utils.query import get_connection

        conn = get_connection(self.conn_str, autocommit=True, timeout=20)
        return conn

    def close(self):
        from bmsdna.sql_utils.query import get_connection

        with get_connection(self.conn_str_master, autocommit=True) as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        """DECLARE @kill varchar(8000) = '';  
    SELECT @kill = @kill + 'kill ' + CONVERT(varchar(5), session_id) + ';'  
    FROM sys.dm_exec_sessions
    WHERE database_id  = db_id(?)

    EXEC(@kill);""",
                        (self.db_name,),
                    )
                    cursor.execute(f" drop DATABASE if exists {self.db_name}")
                except Exception as e:
                    logger.error("Error drop creating db", exc_info=e)


@pytest.fixture(scope="session")
def spawn_sql():
    import test_server
    import os

    if os.getenv("NO_SQL_SERVER", "0") == "1":
        yield None
    else:
        sql_server = test_server.start_mssql_server()
        yield sql_server
        if os.getenv("KEEP_SQL_SERVER", "0") == "0":  # can be handy during development
            sql_server.stop()


@pytest.fixture(scope="session")
def connection(spawn_sql):
    c = DB_Connection()
    yield c
    c.close()


@pytest.fixture(scope="session")
def spark_session():
    from pyspark.sql import SparkSession
    from delta import configure_spark_with_delta_pip

    builder = (
        SparkSession.builder.appName("test_sql_utils")  # type: ignore
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
    )

    spark = configure_spark_with_delta_pip(builder).getOrCreate()

    return spark


@pytest.fixture(scope="session")
def azurite():
    import test_server
    import os

    if os.getenv("NO_AZURITE_DOCKER", "0") == "1":
        test_server.create_test_blobstorage()
        yield None
    else:
        azurite = test_server.start_azurite()
        yield azurite
        if os.getenv("KEEP_AZURITE_DOCKER", "0") == "0":  # can be handy during development
            azurite.stop()
