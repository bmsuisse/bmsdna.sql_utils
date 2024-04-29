from typing import Literal, Optional, Union, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    import pyodbc
    import pytds

logger = logging.getLogger(__name__)


def init_logging(conn: "pyodbc.Connection|pytds.Connection"):
    from .sqlschema import create_table, FieldWithType

    create_table(
        ("lake_import", "_log"),
        [
            FieldWithType(name="table_name", type={"type_str": "varchar"}, max_str_length=200),
            FieldWithType(name="type", type={"type_str": "varchar"}, max_str_length=100),
            FieldWithType(name="insert_date", type={"type_str": "datetime"}),
            FieldWithType(name="partition_filter", type={"type_str": "varchar"}, max_str_length=900),
            FieldWithType(name="error", type={"type_str": "nvarchar"}, max_str_length=4000),
            FieldWithType(name="sql", type={"type_str": "nvarchar"}, max_str_length=4000),
        ],
        conn,
        overwrite=False,
        primary_keys=[],
    )


def insert_into_log(
    con: "pyodbc.Connection|pytds.Connection",
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
    with con.cursor() as cur:
        cur.execute(
            """INSERT INTO lake_import._log(table_name, type, insert_date, partition_filter, error, sql)
                VALUES(?,?,GETUTCDATE(),?,?,?)""",
            (table_name_str, type, partition_filter, error, sql),
        )
