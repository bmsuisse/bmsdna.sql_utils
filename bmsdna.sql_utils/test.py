import sqlglot
from deltalake2db import duckdb_create_view_for_delta
import duckdb

with duckdb.connect() as con:
    # duckdb_create_view_for_delta(con, "tests/data/delta-table", "test_delta")
    duckdb_create_view_for_delta(con, "tests/data/faker", "faker")

    # print(con.execute("SELECT * FROM test_delta").fetchdf())
    print(con.execute("SELECT * FROM faker").fetchdf())
