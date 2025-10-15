from datetime import datetime, timezone

from .source import ImportSource, WriteInfo
import urllib.parse
from bmsdna.sql_utils.query import get_connection
import logging
from bmsdna.sql_utils.lake.types import FieldWithType, SQLField
from bmsdna.sql_utils.lake.type_fromarrow import recursive_get_type
from bmsdna.sql_utils.query import sql_quote_name
from .sqlschema import with_max_str_length
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import deltalake
    from bmsdna.sql_utils.query import ConnectionParams

logger = logging.getLogger(__name__)


class DeltaPolarsSource(ImportSource):
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
        import polars
        from deltalake2db import polars_scan_delta

        df = polars_scan_delta(self.delta_lake, conditions=partition_filters).collect()
        arrow_schema = df.limit(0).to_arrow().schema
        slices = df.iter_slices()

        def _to_batches():
            for sl in slices:
                yield from sl.to_arrow().to_batches()

        import pyarrow

        record_batch_reader = pyarrow.RecordBatchReader.from_batches(arrow_schema, _to_batches())
        table_str = target_table if isinstance(target_table, str) else target_table[0] + "." + target_table[1]
        conn_str_maybe = connection_string() if callable(connection_string) else connection_string

        if self.use_json_insert or not (isinstance(conn_str_maybe, str) or isinstance(conn_str_maybe, dict)):
            from .json_insert import insert_into_table_via_json_from_batches

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

            res = await insert_record_batch_to_sql(connection_string_sql, table_str, record_batch_reader, select)
            col_names = [f["name"] for f in res["fields"]]
            # r.raise_for_status()
        return WriteInfo(column_names=col_names, table_name=target_table)

    def get_partition_values(self) -> list[dict]:
        import polars as pl
        from deltalake2db import polars_scan_delta

        part_cols = self.delta_lake.metadata().partition_columns

        if len(part_cols) == 0:
            return []
        sorted = (
            polars_scan_delta(self.delta_lake).select([pl.col(pc) for pc in part_cols]).unique().sort(part_cols[0])
        )
        return sorted.collect().to_dicts()

    def get_schema(self) -> list[SQLField]:
        import pyarrow as pa
        from deltalake2db import polars_scan_delta

        if self._schema is not None:
            return self._schema
        import polars as pl

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
            fields[fieldname] = SQLField(column_name=fieldname, data_type=recursive_get_type(t, True))
            if is_complex:
                length_fields.append(fieldname)
                import json

                sql_lens.append(pl.col(fieldname).map_elements(lambda x: len(json.dumps(x))).max().alias(fieldname))
            elif is_string:
                length_fields.append(fieldname)
                sql_lens.append(pl.col(fieldname).str.len_chars().max().alias(fieldname))

        if len(sql_lens) > 0:
            res = polars_scan_delta(self.delta_lake).select(*sql_lens).collect().to_dicts()
            for lf in length_fields:
                fields[lf] = SQLField(
                    fields[lf].column_name, with_max_str_length(fields[lf].data_type, res[0][lf] or 100)
                )

        self._schema = list(fields.values())
        return self._schema

    def get_last_change_date(self):
        return datetime.fromtimestamp(
            self.delta_lake.history(1)[-1]["timestamp"] / 1000.0,
            tz=timezone.utc,
        )
