from typing import Any, Literal

from bmsdna.sql_utils.query import SQLObjectNameType, sql_quote_name
from typing_extensions import LiteralString


def get_proc_exec_sql(
    name: SQLObjectNameType,
    arg_dict: list[tuple[LiteralString, Any]],
    param_style: Literal["?", "%"],
) -> str:
    if param_style == "?":
        return "EXEC " + sql_quote_name(name) + " " + ", ".join(["@" + key + "=?" for (key, _) in arg_dict])
    return "EXEC " + sql_quote_name(name) + " " + ", ".join(["@" + key + "=%s" for (key, _) in arg_dict])


def get_param_style(conn: Any):
    try:
        import pytds

        if isinstance(conn, pytds.connection.BaseConnection):
            return "%"
    except ImportError:
        pass

    try:
        import aioodbc

        if isinstance(conn, aioodbc.Connection):
            return "?"
    except ImportError:
        pass
    return "?"

    try:
        import pyodbc

        if isinstance(conn, pyodbc.Connection):
            return "?"
    except ImportError:
        pass
    return "?"
