from datetime import datetime, timezone

from deltalake2db import get_sql_for_delta
from .source import ImportSource, WriteInfo
import urllib.parse
from bmsdna.sql_utils.query import build_connection_string
import logging
from bmsdna.sql_utils.lake.types import SQLField
from bmsdna.sql_utils.lake.type_fromarrow import recursive_get_type
from bmsdna.sql_utils.query import sql_quote_name
from typing import TYPE_CHECKING
from .sqlschema import with_max_str_length
import sqlglot.expressions as ex

if TYPE_CHECKING:
    import pyspark
    from pyspark.sql import DataFrame
logger = logging.getLogger(__name__)


class SourceSpark(ImportSource):
    def __init__(self, df: "DataFrame", use_json_insert=False, change_date: datetime | None = None) -> None:
        super().__init__()

        self._schema: list[SQLField] | None = None
        self.use_json_insert = use_json_insert
        self.df = df
        self.change_date = change_date

    async def write_to_sql_server(
        self,
        target_table: str | tuple[str, str],
        connection_string: str | dict,
        partition_filters: dict | None,
        select: list[str] | None,
    ) -> WriteInfo:
        import pyarrow as pa

        p_df = self.df
        if partition_filters:
            from pyspark.sql.functions import col, lit

            for k, v in partition_filters.items():
                p_df = p_df.filter(col(k) == lit(v))
        tbl = pa.Table.from_pandas(p_df.toPandas())

        record_batch_reader = pa.RecordBatchReader.from_batches(tbl.schema, tbl.to_batches())
        from lakeapi2sql.bulk_insert import insert_record_batch_to_sql

        table_str = target_table if isinstance(target_table, str) else target_table[0] + "." + target_table[1]
        connection_string_sql = build_connection_string(connection_string, odbc=False)
        if self.use_json_insert:
            from .json_insert import insert_into_table_via_json_from_batches
            import pyodbc

            with pyodbc.connect(build_connection_string(connection_string, odbc=True)) as con:
                schema = self.get_schema()
                filtered_schema = schema if not select else [f for f in schema if f.column_name in select]
                await insert_into_table_via_json_from_batches(
                    reader=record_batch_reader, table_name=target_table, connection=con, schema=filtered_schema
                )
                col_names = [f.column_name for f in filtered_schema]
        else:
            res = await insert_record_batch_to_sql(connection_string_sql, table_str, record_batch_reader, select)
            col_names = [f["name"] for f in res["fields"]]
        return WriteInfo(column_names=col_names, table_name=target_table)

    def get_partition_values(self) -> list[dict]:
        col_names = [f.column_name for f in self.get_schema()]
        if "_partition" in col_names:
            return [
                r.asDict(True) for r in self.df.selectExpr("_partition").orderBy("_partition").distinct().collect()
            ]
        return []

    def get_schema(self) -> list[SQLField]:
        fields = self.df.schema.fields
        return [SQLField(f.name, ex.DataType.build(str(f.dataType.simpleString()), dialect="spark")) for f in fields]

    def get_last_change_date(self):
        if self.change_date:
            return self.change_date
        col_names = [f.column_name for f in self.get_schema()]
        if "__timestamp" in col_names:
            return self.df.selectExpr("max(__timestamp) as max_ts").collect()[0][0]
        return None
