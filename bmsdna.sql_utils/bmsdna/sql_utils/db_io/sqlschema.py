from dataclasses import dataclass
from typing import Callable, Literal, Union, Optional, Any, TYPE_CHECKING, Mapping
import logging
from bmsdna.sql_utils.lake import FieldWithType, SQLField
from bmsdna.sql_utils.query import sql_quote_name, sql_quote_value
import sqlglot.expressions as ex

if TYPE_CHECKING:
    from bmsdna.sql_utils.dbapi import Connection
logger = logging.getLogger(__name__)

table_name_type = Union[str, tuple[str, str]]


def convert_to_sql_field(field: FieldWithType):
    sqt = get_sql_type(field["type"]["type_str"], field.get("max_str_length", None))
    return SQLField(field["name"], ex.DataType.build(sqt, dialect="tsql"))


def with_max_str_length(t: ex.DataType, max_str_length: int | None) -> ex.DataType:
    sql_str = t.sql("tsql")
    if "(" in sql_str:
        sql_str = sql_str[0 : sql_str.find("(")]
    if max_str_length is None:
        max_str_length = 100
    if max_str_length > 4000:
        max_str_length = -1
    new_str = f"{sql_str}({max_str_length})" if max_str_length != -1 else sql_str + "(MAX)"
    return ex.DataType.build(new_str, dialect="tsql")


def get_str_length(field: SQLField | ex.DataType):
    if isinstance(field, SQLField):
        return get_str_length(field.data_type)
    if len(field.expressions) != 1:
        return None
    t_zero = field.expressions[0]
    if not isinstance(t_zero, (float, int, str)):
        t_zero = t_zero.this
    if not isinstance(t_zero, (float, int, str)):
        t_zero = t_zero.this
    if not isinstance(t_zero, (float, int, str)):
        t_zero = t_zero.this
    assert isinstance(t_zero, (float, int, str)), f"cannot get string length from {str(field)}. AST: {repr(field)}"
    if isinstance(t_zero, str) and t_zero.upper() == "MAX":
        return -1
    return int(t_zero)


def get_field_col_definition(
    field: FieldWithType | SQLField, nullable=True, default: str | None = None, formula: str | None = None
) -> str:
    if not isinstance(field, SQLField):
        field = convert_to_sql_field(field)
    return get_col_definition(
        field=field,
        default=default,
        formula=formula,
    )


def get_sql_type(type_str: str, max_str_length: Optional[int]):
    assert type_str not in ["List", "Struct"]
    simple_type_map = {
        "float16": "float",
        "float32": "float",
        "float64": "float",
        "double": "float",
        "int16": "smallint",
        "int": "int",
        "int32": "int",
        "int64": "bigint",
        "int8": "tinyint",  # one could argue to use smallint here, but nobody does use something like this
        "uint8": "tinyint",
        "uint16": "int",
        "uint32": "bigint",
        "uint64": "bigint",
        "date": "datetime",  # we do not map to date since it gives strange errors
        "datetime": "datetime",
        "time": "time",
        "time32": "time",
        "time64": "time",
        "duration": "time",
        "timestamp": "datetimeoffset",
        "date32": "datetime",
        "date64": "datetime",
        "bool": "bit",
        "binary": "varbinary(MAX)",
        "decimal128": "float",
        "float": "float",
        "large_binary": "varbinary(MAX)",
        "categorical": "nvarchar(1000)",
        "null": "nvarchar(1000)",
        "object": "nvarchar(max)",
        "timestamp[us]": "datetime2",
        "timestamp[ms]": "datetime",
        "timestamp[ns]": "datetime2",
        "varchar": "varchar",
        "nvarchar": "nvarchar",
        "date32[day]": "datetime",
        "date64[day]": "datetime",
        "bigint": "bigint",
    }
    if type_str.startswith("struct<") or type_str.startswith("list<") or type_str.startswith("array<"):
        return "nvarchar(MAX)"  # json-ify-ed
    elif type_str in ["Utf8", "varchar", "nvarchar", "string", "large_string", "utf8", "large_utf8"]:
        real_max_length = max_str_length or 4000
        if real_max_length <= 2000:
            real_max_length = real_max_length * 2
        elif real_max_length > 4000:  # need max type
            real_max_length = "MAX"
        return f"nvarchar({real_max_length})"
    elif type_str.startswith("decimal"):  # types like decimal128(Precision, scale). We assume float is ok
        normalized = type_str.replace("[", "(")
        scale = int(normalized[normalized.find(",") + 1 :].removesuffix("]").removesuffix(")"))
        return "numeric(38, " + str(scale) + ")"
    elif type_str in simple_type_map:
        return simple_type_map[type_str]
    elif type_str.startswith("timestamp[us"):
        return "datetime2"
    elif type_str.startswith("timestamp[ns"):
        return "datetime2"
    elif type_str.startswith("timestamp[ms"):
        return "datetime"
    else:
        raise ValueError("Unkown type " + type_str)


def get_col_definition(
    field: SQLField,
    nullable=True,
    default: str | None = None,
    formula: str | None = None,
) -> str:
    if formula is not None:
        return sql_quote_name(field.column_name) + " AS " + formula
    sql_type = field.data_type.sql("tsql")
    if sql_type.startswith("varchar") or sql_type.startswith("char"):
        sql_type = "n" + sql_type  # see https://github.com/tobymao/sqlglot/issues/3381
    if sql_type.startswith("VARCHAR") or sql_type.startswith("CHAR"):
        sql_type = "N" + sql_type  # see https://github.com/tobymao/sqlglot/issues/3381
    definit = sql_quote_name(field.column_name) + " " + sql_type + (" NOT NULL" if not nullable else "")
    if default is not None and default.lower() != "null":
        definit += " DEFAULT (" + default + ")"
    return definit


def sql_quote_value_with_type(field: FieldWithType | SQLField, value: Any) -> str:
    if not isinstance(field, SQLField):
        field = convert_to_sql_field(field)

    if value is not None and field.data_type.type in [ex.DataType.Type.BOOLEAN, ex.DataType.Type.BIT]:
        assert type(value) == bool
        if value == True:
            return f"CAST(1 as bit)"
        else:
            return f"CAST(0 as bit)"
    if value is not None and str(field.data_type.type).lower() in ["string", "int32", "varchar", "int"]:
        return sql_quote_value(value)  # string / int32 are defaults for sql server
    sql_type = field.data_type.sql("tsql")
    if sql_type.startswith("varchar") or sql_type.startswith("char"):
        sql_type = "n" + sql_type  # see https://github.com/tobymao/sqlglot/issues/3381
    if sql_type.startswith("VARCHAR") or sql_type.startswith("CHAR"):
        sql_type = "n" + sql_type  # see https://github.com/tobymao/sqlglot/issues/3381
    if value is not None:
        return f"CAST({sql_quote_value(value)} as {sql_type})"
    else:
        return f"CAST(NULL AS {sql_type})"


def get_sql_for_schema(
    table_name: table_name_type,
    schema: list[SQLField],
    primary_keys: list[str] | None,
    with_exist_check: bool,
    default_values: Mapping[str, tuple[FieldWithType | SQLField, Any]] | None = None,
    calculated_values: Mapping[str, str] | None = None,
):
    cols_sql = [
        get_field_col_definition(
            f,
            primary_keys is None or f.column_name not in primary_keys,
            default=(
                sql_quote_value_with_type(*default_values[f.column_name])
                if default_values and f.column_name in default_values
                else None
            ),
            formula=(
                calculated_values[f.column_name]
                if calculated_values is not None and f.column_name in calculated_values
                else None
            ),
        )
        for f in schema
    ]
    l_col_names = [f.column_name.lower() for f in schema]
    if calculated_values is not None:
        for k, v in calculated_values.items():
            if k.lower() not in l_col_names:
                cols_sql.append(sql_quote_name(k) + " AS " + v)

    cols = ", ".join(cols_sql)
    pkdef = ""
    if primary_keys and len(primary_keys) > 0:
        pkcols = ", ".join((sql_quote_name(n) for n in primary_keys))
        tbl_name_pk = (
            table_name.removeprefix("##") if isinstance(table_name, str) else table_name[0] + "_" + table_name[1]
        )
        pkdef = f", CONSTRAINT {sql_quote_name('PK_' + tbl_name_pk)}  PRIMARY KEY({pkcols})"
    create_sql = f"CREATE TABLE {sql_quote_name(table_name)}({cols}{pkdef}) "

    if with_exist_check:
        return f"""
            IF OBJECT_ID (N'{sql_quote_name(table_name).replace("'", "''")}', N'U') IS NULL 
            BEGIN
                {create_sql}
                select 'created' as action
            END
            else
            begin
                select 'nothing' as action
            end 
        """
    return create_sql


def get_raw_type(type: str | ex.DataType | ex.DataType.Type) -> str:
    if isinstance(type, ex.DataType.Type):
        return str(type).lower()
    if isinstance(type, ex.DataType):
        return str(type.type).lower()
    if "(" in type:
        return type[: type.find("(")]
    return type


def col_approx_eq(type1: str, type2: str | ex.DataType | ex.DataType.Type):
    if type1 == type2:
        return True
    if isinstance(type2, ex.DataType.Type):
        type2 = str(type2).lower()
    elif isinstance(type2, ex.DataType):
        type2 = str(type2).lower()
    if "(" in type1:
        type1 = type1[: type1.find("(")]
    if "(" in type2:
        type2 = type2[: type2.find("(")]
    if type1.lower() in ["varchar", "nvarchar"] and type2.lower() in ["varchar", "nvarchar"]:
        return True
    return type1 == type2


@dataclass(frozen=True)
class CreateTableCallbackParams:
    table_name: table_name_type
    schema: list[SQLField]
    conn: "Connection"
    primary_keys: list[str] | None
    action: Literal["create", "adjusted", "none"]
    truncated: bool


def create_table(
    table_name: table_name_type,
    schema: list[SQLField],
    conn: "Connection",
    primary_keys: list[str] | None,
    overwrite: bool,
    default_values: Mapping[str, tuple[SQLField, Any]] | None = None,
    calculated_values: Mapping[str, str] | None = None,
    callback: list[Callable[[CreateTableCallbackParams], Any]] | None = None,
):
    if not any(schema):
        raise ValueError("Must provide at least one column")
    created = False
    truncated = False
    adjusted = False
    if overwrite:
        with conn.cursor() as cur:
            sql = f"DROP TABLE IF EXISTS {sql_quote_name(table_name)}"
            logger.info(f"Executing sql: {sql}")
            cur.execute(sql)
            created = True
            truncated = True
    else:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COLUMN_NAME as column_name,
	DATA_TYPE as data_type,
	CHARACTER_MAXIMUM_LENGTH as max_len,COLUMN_DEFAULT
	FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=? and TABLE_NAME=?""",
                (table_name[0], table_name[1]),
            )
            assert cur.description is not None
            columns = [column[0] for column in cur.description]
            cols = []
            for row in cur.fetchall():
                cols.append(dict(zip(columns, row)))
        if len(cols) > 0:
            col_dict = {col["column_name"].lower(): col for col in cols}
            todos: list[str] = []
            truncate = False
            separate_cursors = False
            for scc in schema:
                max_len = get_str_length(scc.data_type)
                existing_col = col_dict.get(scc.column_name.lower(), None)
                if existing_col is None:
                    defini = get_field_col_definition(
                        scc,
                        primary_keys is None or scc.column_name not in primary_keys,
                        default=(
                            sql_quote_value_with_type(*default_values[scc.column_name])
                            if default_values and scc.column_name in default_values
                            else None
                        ),
                        formula=(
                            calculated_values.get(scc.column_name, None) if calculated_values is not None else None
                        ),
                    )
                    truncate = True
                    todos.append(f"ALTER TABLE {sql_quote_name(table_name)} ADD {defini}")

                elif (
                    not col_approx_eq(existing_col["data_type"], scc.data_type)
                    and scc.column_name not in (calculated_values or dict())
                    and scc.column_name not in (default_values or dict())
                ):
                    truncate = True
                    separate_cursors = True
                    todos.append(
                        f"ALTER TABLE {sql_quote_name(table_name)} DROP COLUMN {sql_quote_name(scc.column_name)}"
                    )
                    defini = get_field_col_definition(scc, primary_keys is None or scc.column_name not in primary_keys)
                    todos.append(f"ALTER TABLE {sql_quote_name(table_name)} ADD {defini}")
                elif (
                    max_len is not None
                    and existing_col["max_len"]
                    and max_len > existing_col["max_len"]
                    and existing_col["max_len"] != -1
                    and scc.column_name not in (calculated_values or dict())
                    and scc.column_name not in (default_values or dict())
                ):
                    max_len_str = str(max_len)
                    if (max_len > 4000 and existing_col["data_type"] == "nvarchar") or (
                        existing_col["data_type"] == "varchar" and max_len > 8000
                    ):
                        max_len_str = "MAX"
                    sql_t = existing_col["data_type"] + "(" + max_len_str + ")"
                    todos.append(
                        f"ALTER TABLE {sql_quote_name(table_name)} ALTER COLUMN {sql_quote_name(scc.column_name)} {sql_t}"
                    )
            if truncate:
                todos.insert(0, f"TRUNCATE TABLE {sql_quote_name(table_name)}")
                truncated = True
            if len(todos) > 0:
                adjusted = True
                if separate_cursors:
                    for td in todos:
                        with conn.cursor() as cur:
                            logger.info(f"Executing alter sql: {td}")
                            from .db_logging import insert_into_log

                            insert_into_log(conn, table_name, "schema_drift", sql=td)
                            cur.execute(td)
                else:
                    sql = ";\r\n".join(todos)
                    with conn.cursor() as cur:
                        logger.info(f"Executing alter sql: {sql}")
                        from .db_logging import insert_into_log

                        print(sql)
                        insert_into_log(conn, table_name, "schema_drift", sql=sql)
                        cur.execute(sql)

    with conn.cursor() as cur:
        sql = get_sql_for_schema(
            table_name,
            schema,
            primary_keys=primary_keys,
            with_exist_check=not overwrite,
            default_values=default_values,
            calculated_values=calculated_values,
        )

        logger.info(f"Executing sql: {sql}")
        from .db_logging import insert_into_log

        cur.execute(sql)
        if not overwrite:
            from bmsdna.sql_utils.db_helper import get_one_real_row

            res = get_one_real_row(cur)
            assert res is not None
            created = res[0].lower() == "created"
    if callback is not None:
        for c in callback:
            c(
                CreateTableCallbackParams(
                    table_name,
                    schema,
                    conn,
                    primary_keys,
                    "create" if created else "adjusted" if adjusted else "none",
                    truncated=truncated,
                )
            )


def is_table_empty(
    conn: "Connection",
    table_name: table_name_type,
    filter: Optional[str],
):
    with conn.cursor() as cur:
        cur.execute("SELECT TOP 1 * FROM " + sql_quote_name(table_name) + f" WHERE {filter or '1=1'}")
        res = cur.fetchall()
        if len(res) == 0:
            return True
        return False


def get_max_update_col_value(
    conn: "Connection",
    table_name: table_name_type,
    update_col: str,
    filter: Optional[str],
):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT MaX({sql_quote_name(update_col)}) FROM "
            + sql_quote_name(table_name)
            + f" WHERE {filter or '1=1'}"
        )
        res = cur.fetchone()
        if res is None:
            return None
        return res[0]
