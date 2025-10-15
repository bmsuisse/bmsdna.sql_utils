from datetime import datetime, timezone

from .source import ImportSource, WriteInfo
import urllib.parse
import logging
from bmsdna.sql_utils.lake.types import SQLField
from bmsdna.sql_utils.lake.type_fromarrow import recursive_get_type
from bmsdna.sql_utils.query import sql_quote_name, get_connection, ConnectionParams
from typing import TYPE_CHECKING, Callable
from .sqlschema import with_max_str_length

if TYPE_CHECKING:
    import deltalake
    from bmsdna.sql_utils.dbapi import Connection
logger = logging.getLogger(__name__)


class DeltaSource(ImportSource):
    def __init__(
        self, path_or_table: "str | deltalake.DeltaTable", storage_options: dict | None = None, use_json_insert=False
    ) -> None:
        super().__init__()
        import deltalake

        if isinstance(path_or_table, str):
            self.delta_lake = deltalake.DeltaTable(path_or_table, storage_options=storage_options)
        else:
            self.delta_lake = path_or_table
        self._schema: list[SQLField] | None = None
        self.use_json_insert = use_json_insert
        self.batch_size = 1048576 if not use_json_insert else 1000

    async def write_to_sql_server(
        self,
        target_table: str | tuple[str, str],
        connection_string: "ConnectionParams",
        partition_filters: dict | None,
        select: list[str] | None,
    ) -> WriteInfo:
        import duckdb
        from deltalake2db import get_sql_for_delta

        sql = get_sql_for_delta(self.delta_lake, partition_filters, select)
        if sql is not None:
            with duckdb.connect() as con:
                record_batch_reader = con.execute(sql).fetch_record_batch(self.batch_size)
                table_str = target_table if isinstance(target_table, str) else target_table[0] + "." + target_table[1]
                conn_str_maybe = connection_string() if callable(connection_string) else connection_string

                if self.use_json_insert or not (isinstance(conn_str_maybe, str) or isinstance(conn_str_maybe, dict)):
                    from .json_insert import insert_into_table_via_json_from_batches

                    con = None
                    with get_connection(conn_str_maybe) as con:
                        schema = self.get_schema()
                        filtered_schema = schema if not select else [f for f in schema if f.column_name in select]
                        await insert_into_table_via_json_from_batches(
                            reader=record_batch_reader, table_name=target_table, connection=con, schema=filtered_schema
                        )
                        col_names = [f.column_name for f in filtered_schema]
                        con.commit()
                else:
                    from bmsdna.sql_utils.query import build_connection_string
                    from lakeapi2sql.bulk_insert import insert_record_batch_to_sql

                    connection_string_sql = build_connection_string(conn_str_maybe, odbc=False)

                    res = await insert_record_batch_to_sql(
                        connection_string_sql, table_str, record_batch_reader, select
                    )
                    col_names = [f["name"] for f in res["fields"]]
                # r.raise_for_status()
        else:
            col_names = []
        return WriteInfo(column_names=col_names, table_name=target_table)

    def get_partition_values(self) -> list[dict]:
        import duckdb
        from deltalake2db import get_sql_for_delta

        part_cols = self.delta_lake.metadata().partition_columns

        if len(part_cols) == 0:
            return []
        delta_sql = get_sql_for_delta(self.delta_lake, {}, part_cols, distinct=True)
        if delta_sql is None:
            return []  # no files
        sql = delta_sql + " ORDER BY " + ",".join([sql_quote_name(pc) for pc in part_cols])
        with duckdb.connect() as con:
            ls = con.execute(sql).fetchall()
            return [{p: it[i] for i, p in enumerate(part_cols)} for it in ls]

    def get_schema(self) -> list[SQLField]:
        import pyarrow as pa
        from deltalake2db import get_sql_for_delta

        if self._schema is not None:
            return self._schema
        import duckdb

        sc_schema = self.delta_lake.schema()  # .to_pyarrow()
        if hasattr(sc_schema, "to_pyarrow"):
            schema = sc_schema.to_pyarrow()  # type: ignore
        else:
            import pyarrow

            schema: pyarrow.Schema = pyarrow.schema(sc_schema)  # type: ignore
        sql_lens = []
        length_fields: list[str] = []
        fields: dict[str, SQLField] = dict()
        for fieldname in schema.names:
            if fieldname in self.forbidden_cols:
                continue
            f = schema.field(fieldname)
            t = f.type
            is_complex = (
                pa.types.is_list(t)
                or pa.types.is_large_list(t)
                or pa.types.is_fixed_size_list(t)
                and t.value_type is not None
            )
            is_string = pa.types.is_string(t) or pa.types.is_large_string(t)
            fields[fieldname] = SQLField(fieldname, recursive_get_type(t, True))
            if is_complex:
                length_fields.append(fieldname)
                sql_lens.append(f"MAX(LEN(to_json({sql_quote_name(fieldname)}))) as {sql_quote_name(fieldname)}")
            elif is_string:
                length_fields.append(fieldname)
                sql_lens.append(f"MAX(LEN({sql_quote_name(fieldname)})) as {sql_quote_name(fieldname)}")

        if len(sql_lens) > 0:
            delta_sql = get_sql_for_delta(self.delta_lake, distinct=False, cte_wrap_name="deltasql")
            if delta_sql is not None:  # if there are no files, we get None
                sql = delta_sql + "\r\n SELECT " + ", ".join(sql_lens) + " FROM deltasql"

                with duckdb.connect() as con:
                    with con.cursor() as cur:
                        cur.execute(sql)
                        res = cur.fetchone()
                        assert res is not None
                        for i, lf in enumerate(length_fields):
                            fields[lf] = SQLField(
                                fields[lf].column_name, with_max_str_length(fields[lf].data_type, res[i] or 100)
                            )

        self._schema = list(fields.values())
        return self._schema

    def get_last_change_date(self):
        return datetime.fromtimestamp(
            self.delta_lake.history(1)[-1]["timestamp"] / 1000.0,
            tz=timezone.utc,
        )
