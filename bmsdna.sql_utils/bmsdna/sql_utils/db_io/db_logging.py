from typing import Literal, Optional, Union, TYPE_CHECKING
import logging
import sqlglot.expressions as ex

if TYPE_CHECKING:
    from bmsdna.sql_utils.dbapi import Connection

logger = logging.getLogger(__name__)


def init_logging(conn: "Connection"):
    from .sqlschema import create_table, SQLField

    create_table(
        ("lake_import", "_log"),
        [
            SQLField(column_name="table_name", data_type=ex.DataType.build("varchar(200)", dialect="tsql")),
            SQLField(column_name="type", data_type=ex.DataType.build("varchar(100)", dialect="tsql")),
            SQLField(column_name="insert_date", data_type=ex.DataType.build("datetime", dialect="tsql")),
            SQLField(column_name="partition_filter", data_type=ex.DataType.build("varchar(900)", dialect="tsql")),
            SQLField(column_name="error", data_type=ex.DataType.build("nvarchar(4000)", dialect="tsql")),
            SQLField(column_name="sql", data_type=ex.DataType.build("nvarchar(4000)", dialect="tsql")),
        ],
        conn,
        overwrite=False,
        primary_keys=[],
    )


warned_logging = False


def insert_into_log(
    con: "Connection",
    table_name: Union[str, tuple[str, str]],
    type: Literal["start_load", "end_load", "error", "schema_drift", "start_merge", "start_full", "skip_load"],
    *,
    partition_filter: Optional[str] = None,
    error: Optional[str] = None,
    sql: Optional[str] = None,
):
    table_name_str = table_name if isinstance(table_name, str) else table_name[0] + "." + table_name[1]
    if sql and len(sql) > 4000:
        sql = sql[0:3999]
    if error:
        logger.error(f"{type} for {table_name}, {partition_filter}:\n {error}")
    else:
        logger.info(f"{type} for {table_name}, {partition_filter}")
    try:
        with con.cursor() as cur:
            cur.execute(
                """INSERT INTO lake_import._log("table_name", type, insert_date, partition_filter, error, sql)
                    VALUES(?,?,GETUTCDATE(),?,?,?)""",
                (table_name_str, type, partition_filter, error, sql),
            )
    except Exception as err:
        global warned_logging
        if not warned_logging:
            warned_logging = True
            logger.warning("Could not log to table", exc_info=err)
