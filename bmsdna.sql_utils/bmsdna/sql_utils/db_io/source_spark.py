from datetime import datetime, timezone

from .source import ImportSource, WriteInfo
import urllib.parse
from bmsdna.sql_utils.query import build_connection_string
import logging
from bmsdna.sql_utils.lake.types import SQLField
from bmsdna.sql_utils.lake.type_fromarrow import recursive_get_type
from bmsdna.sql_utils.query import get_connection
from typing import TYPE_CHECKING
from .sqlschema import with_max_str_length, get_str_length
import sqlglot.expressions as ex

if TYPE_CHECKING:
    from bmsdna.sql_utils.query import ConnectionParams
    from pyspark.sql import DataFrame
logger = logging.getLogger(__name__)


class SourceSpark(ImportSource):
    def __init__(
        self,
        df: "DataFrame",
        use_json_insert=False,
        change_date: datetime | None = None,
        partition_columns: list[str] | None = None,
    ) -> None:
        super().__init__()

        self._schema: list[SQLField] | None = None
        self.use_json_insert = use_json_insert
        self.df = df
        self.change_date = change_date
        self.partition_columns = partition_columns

    async def write_to_sql_server(
        self,
        target_table: str | tuple[str, str],
        connection_string: "ConnectionParams",
        partition_filters: dict | None,
        select: list[str] | None,
    ) -> WriteInfo:
        p_df = self.df
        if partition_filters:
            from pyspark.sql.functions import col, lit

            for k, v in partition_filters.items():
                p_df = p_df.filter(col(k) == lit(v))

        table_str = target_table if isinstance(target_table, str) else target_table[0] + "." + target_table[1]
        conn_str_maybe = connection_string() if callable(connection_string) else connection_string

        if self.use_json_insert or not (isinstance(conn_str_maybe, str) or isinstance(conn_str_maybe, dict)):
            from .json_insert import insert_into_table_via_json
            from pyspark.sql.functions import to_json, struct, col

            iter = p_df.select(to_json(struct(col("*")))).toLocalIterator()

            async def _to_batches():
                ls = []
                for row in iter:
                    ls.append(row[0])
                    if len(ls) > 1000:
                        yield "[" + "\n, ".join(ls) + "]"
                        ls = []
                if ls:
                    yield "[" + "\n, ".join(ls) + "]"

            with get_connection(connection_string) as con:
                schema = self.get_schema()
                filtered_schema = schema if not select else [f for f in schema if f.column_name in select]
                await insert_into_table_via_json(
                    json_batches=_to_batches(),
                    table_name=target_table,
                    connection=con,
                    schema=filtered_schema,
                )
                col_names = [f.column_name for f in filtered_schema]
        else:
            import pyarrow as pa
            from lakeapi2sql.bulk_insert import insert_record_batch_to_sql

            if not p_df.isEmpty():
                try:
                    tbl = p_df.toArrow()  # type: ignore
                except AttributeError:
                    tbl = pa.Table.from_pandas(p_df.toPandas())

                record_batch_reader = pa.RecordBatchReader.from_batches(tbl.schema, tbl.to_batches())
                res = await insert_record_batch_to_sql(
                    build_connection_string(conn_str_maybe, odbc=True), table_str, record_batch_reader, select
                )
                col_names = [f["name"] for f in res["fields"]]
            else:
                col_names = [f.column_name for f in self.get_schema()]
        return WriteInfo(column_names=col_names, table_name=target_table)

    def get_partition_values(self) -> list[dict]:
        col_names = [f.column_name for f in self.get_schema()]
        if "_partition" in col_names and self.partition_columns is None:
            self.partition_columns = ["_partition"]
        if self.partition_columns:
            return [
                r.asDict(True)
                for r in self.df.selectExpr(*self.partition_columns)
                .orderBy(*self.partition_columns)
                .distinct()
                .collect()
            ]
        return []

    def get_schema(self) -> list[SQLField]:
        fields = self.df.schema.fields

        def sqlglot_type(dtype):
            simple_str = str(dtype.simpleString())
            if simple_str == "timestamp_ntz":
                return ex.DataType.build("datetime2", dialect="tsql")  # more or less
            if simple_str.startswith("date32[") or simple_str == "date32":
                return ex.DataType.build("date", dialect="tsql")
            if simple_str.startswith("date64[") or simple_str == "date64":
                return ex.DataType.build("date", dialect="tsql")
            return ex.DataType.build(simple_str, dialect="spark")

        schema = [SQLField(f.name, sqlglot_type(f.dataType)) for f in fields]
        sql_lens = []
        length_fields = []
        for field in schema:
            from pyspark.sql.functions import col, length, max

            if field.data_type.this in ex.DataType.TEXT_TYPES or str(field.data_type).lower() == "string":
                length_fields.append(field.column_name)
                sql_lens.append(max(length(col(field.column_name))).alias(field.column_name))

        if sql_lens:
            lengths = self.df.select(*sql_lens).collect()[0].asDict()
            new_schema: list[SQLField] = []
            for field in schema:
                if field.column_name in length_fields:
                    new_field = SQLField(
                        field.column_name, with_max_str_length(field.data_type, lengths[field.column_name] or 100)
                    )
                    new_schema.append(new_field)
                else:
                    new_schema.append(field)
            return new_schema
        return schema

    def get_last_change_date(self):
        if self.change_date:
            return self.change_date
        col_names = [f.column_name for f in self.get_schema()]
        if "__timestamp" in col_names:
            return self.df.selectExpr("max(__timestamp) as max_ts").collect()[0][0]
        return None
