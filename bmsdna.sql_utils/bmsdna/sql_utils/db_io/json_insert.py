from bmsdna.sql_utils.db_io.sqlschema import get_field_col_definition
from bmsdna.sql_utils.query import sql_quote_name
from bmsdna.sql_utils.lake import FieldWithType
from typing import TYPE_CHECKING, AsyncIterable
import json

if TYPE_CHECKING:
    import pyodbc
    import pytds
    import pyarrow as pa


async def insert_into_table_via_json(
    *,
    json_batches: AsyncIterable[str],
    table_name: tuple[str, str] | str,
    connection: "pyodbc.Connection | pytds.Connection",
    schema: list[FieldWithType],
    colnames: list[str] | None = None,
):
    colnames = colnames or [f["name"] for f in schema]
    cols = ", ".join([sql_quote_name(c) for c in colnames])
    col_defs = ", ".join([get_field_col_definition(f) for f in schema])
    insert_to_tmp_tbl_stmt = (
        f"INSERT INTO {sql_quote_name(table_name)}({cols}) SELECT {cols} from openjson(?) with ({col_defs})"
    )
    async for batch_json in json_batches:
        with connection.cursor() as cursor:
            cursor.execute(insert_to_tmp_tbl_stmt, (batch_json,))


async def _batch_reader_to_json(reader: "pa.RecordBatchStreamReader"):
    try:
        import polars  # type: ignore

        for batch in reader:  # type: ignore
            pld = polars.from_arrow(batch)  # type: ignore
            assert isinstance(pld, polars.DataFrame)  # type: ignore
            jsond = pld.write_json(row_oriented=True)  # type: ignore
            yield jsond
    except ImportError:
        for batch in reader:
            yield json.dumps(batch.to_pylist())


async def insert_into_table_via_json_from_batches(
    *,
    reader: "pa.RecordBatchReader",
    table_name: tuple[str, str] | str,
    connection: "pyodbc.Connection | pytds.Connection",
    schema: list[FieldWithType],
    colnames: list[str] | None = None,
):
    colnames = colnames or reader.schema.names or [f["name"] for f in schema]
    r = _batch_reader_to_json(reader)
    await insert_into_table_via_json(
        json_batches=r, schema=schema, table_name=table_name, colnames=colnames, connection=connection
    )
