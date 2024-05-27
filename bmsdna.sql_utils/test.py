import sqlglot
from deltalake2db import duckdb_create_view_for_delta, polars_scan_delta
import duckdb
import polars as pl
import sqlglot.expressions as ex

print(repr(ex.DataType.build("string", dialect="spark")))


def _cast_dt(dt: pl.DataFrame):
    for col in dt.get_columns():
        if isinstance(col.dtype, pl.Datetime) and (col.dtype.time_unit != "ms" or col.dtype.time_zone != "UTC"):
            dt = dt.with_columns(**{col.name: dt[col.name].cast(pl.Datetime("ms", "UTC"))})
    return dt


print(_cast_dt(polars_scan_delta("tests/data/faker").collect()))

with duckdb.connect() as con:
    # duckdb_create_view_for_delta(con, "tests/data/delta-table", "test_delta")
    duckdb_create_view_for_delta(con, "tests/data/faker", "faker")

    # print(con.execute("SELECT * FROM test_delta").fetchdf())
    print(con.execute("SELECT * FROM faker").fetchdf())
