from bmsdna.sql_utils.db_io.sqlschema import get_sql_for_schema
from bmsdna.sql_utils.lake.types import FieldWithType, FieldType
import sqlglot
import sqlglot.expressions as exp


def test_schema_with_calc():
    sql = get_sql_for_schema(
        ("dbo", "tester"),
        [FieldWithType(name="p1", type=FieldType(type_str="int", fields=None, inner=None), max_str_length=None)],
        primary_keys=[],
        with_exist_check=False,
        default_values=None,
        calculated_values={"p2": "1"},
    )
    expr = sqlglot.parse_one(sql, dialect="tsql")

    assert isinstance(expr, exp.Create)
    sql = get_sql_for_schema(
        ("dbo", "tester"),
        [FieldWithType(name="p1", type=FieldType(type_str="int", fields=None, inner=None), max_str_length=None)],
        primary_keys=[],
        with_exist_check=False,
        default_values=None,
        calculated_values={"p2": "1", "P1": "34"},
    )
    assert "p1" not in sql or "P1" not in sql  # no duplicate because of case
    expr = sqlglot.parse_one(sql, dialect="tsql")
    assert isinstance(expr, exp.Create)
