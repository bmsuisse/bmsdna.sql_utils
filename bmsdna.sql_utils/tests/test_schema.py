from bmsdna.sql_utils.db_io.sqlschema import get_sql_for_schema
from bmsdna.sql_utils.lake.types import SQLField, FieldType
import sqlglot
import sqlglot.expressions as exp


def test_schema_with_calc():
    sql = get_sql_for_schema(
        ("dbo", "tester"),
        [SQLField(column_name="p1", data_type=exp.DataType.build(dtype=exp.DataType.Type.INT))],
        primary_keys=[],
        with_exist_check=False,
        default_values=None,
        calculated_values={"p2": "1"},
    )
    expr = sqlglot.parse_one(sql, dialect="tsql")

    assert isinstance(expr, exp.Create)
    sql = get_sql_for_schema(
        ("dbo", "tester"),
        [SQLField(column_name="p1", data_type=exp.DataType.build(dtype=exp.DataType.Type.INT))],
        primary_keys=[],
        with_exist_check=False,
        default_values=None,
        calculated_values={"p2": "1", "P1": "34"},
    )
    assert "p1" not in sql or "P1" not in sql  # no duplicate because of case
    expr = sqlglot.parse_one(sql, dialect="tsql")
    assert isinstance(expr, exp.Create)


def test_string_columns_use_database_default_collation():
    sql = get_sql_for_schema(
        ("dbo", "tester"),
        [
            SQLField(column_name="s1", data_type=exp.DataType.build("varchar(10)", dialect="tsql")),
            SQLField(column_name="s2", data_type=exp.DataType.build("nvarchar(max)", dialect="tsql")),
            SQLField(column_name="i1", data_type=exp.DataType.build(dtype=exp.DataType.Type.INT)),
        ],
        primary_keys=[],
        with_exist_check=False,
        default_values=None,
        calculated_values=None,
    )
    assert sql.upper().count("COLLATE DATABASE_DEFAULT") == 2
    assert isinstance(sqlglot.parse_one(sql, dialect="tsql"), exp.Create)
