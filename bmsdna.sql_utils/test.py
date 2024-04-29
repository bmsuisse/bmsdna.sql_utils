import sqlglot

print(repr(sqlglot.parse("SELECT * FROM read_parquet('path.parquet', union_by_name = TRUE)", dialect="duckdb")))

print("")

print(repr(sqlglot.parse("SELECT * FROM read_parquet(['path.parquet','path2.parquet'])", dialect="duckdb")))
print(
    repr(
        sqlglot.parse(
            """select getdate() AT TIME ZONE 'UTC' from [user] as u
                            """,
            dialect="tsql",
        )
    )
)
