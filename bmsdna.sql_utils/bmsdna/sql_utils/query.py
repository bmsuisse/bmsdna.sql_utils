from typing import Any, Literal, Tuple, TypeAlias, Union, overload, TYPE_CHECKING, Callable
from datetime import datetime
from contextlib import closing

ODBC_DRIVER: str | None = None

drivers: list[str] | None = None
if TYPE_CHECKING:
    from bmsdna.sql_utils.dbapi import Connection

ConnectionParams: TypeAlias = "Union[str, dict, Callable[[], Connection | str | dict]]"


def get_connection(
    dict_dt: "ConnectionParams | Connection",
    *,
    timeout: int = 0,
    connection_timeout: int = 30,
    autocommit: bool = False,
) -> "Connection":
    if callable(dict_dt):
        res = dict_dt()
        if isinstance(res, str) or isinstance(res, dict):
            return get_connection(res, timeout=timeout, connection_timeout=connection_timeout, autocommit=autocommit)
        return res
    if not isinstance(dict_dt, dict) and not isinstance(dict_dt, str):
        return dict_dt
    try:
        import pyodbc

        if not pyodbc.drivers():
            raise ImportError("No ODBC drivers available")
        c = pyodbc.connect(
            build_connection_string(dict_dt, odbc=True), autocommit=autocommit, timeout=connection_timeout
        )
        c.timeout = timeout
        return c
    except ImportError:
        import mssql_python  # type: ignore

        c = mssql_python.Connection(
            build_connection_string(dict_dt, odbc=False), autocommit=autocommit, timeout=connection_timeout
        )
        c.timeout = timeout
        return c


def build_connection_string(dict_dt: dict | str, *, odbc: bool = False, odbc_driver: str | None = None):
    if callable(dict_dt):
        return dict_dt()
    if isinstance(dict_dt, str) and not odbc:
        return dict_dt
    global drivers
    global ODBC_DRIVER
    if odbc and not odbc_driver and ODBC_DRIVER is None:
        import pyodbc

        drivers = drivers or pyodbc.drivers()
        prio = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"]
        for p in prio:
            if p in drivers:
                ODBC_DRIVER = p
                break
        if ODBC_DRIVER is None:
            ODBC_DRIVER = next((d for d in drivers if "for SQL Server" in d), "ODBC Driver 17 for SQL Server")
        assert ODBC_DRIVER is not None
    if isinstance(dict_dt, str):
        assert ODBC_DRIVER is not None
        return "DRIVER=" + (odbc_driver or ODBC_DRIVER) + ";" + dict_dt
    opts = dict_dt | {"DRIVER": (odbc_driver or ODBC_DRIVER)} if odbc else dict_dt
    return ";".join((k + "=" + str(v) for k, v in opts.items()))


QuoteMode: TypeAlias = Literal["ansi", "tsql", "postgres"]

SQLObjectNameType: TypeAlias = Union[str, Tuple[str, str], Tuple[str, str, str]]


def sql_quote_name(inp: SQLObjectNameType, *, mode: QuoteMode = "ansi", compat: bool = False):
    if compat:
        inp = get_compatible_name(inp)
    if isinstance(inp, str):
        if inp.startswith("#"):  # temp tables names must not be quoted
            assert " " not in inp
            assert "-" not in inp
            assert "'" not in inp
            assert '"' not in inp
            assert "*" not in inp
            assert "/" not in inp
            assert "\\" not in inp
            return inp
        assert "[" not in inp
        assert "]" not in inp
        assert "`" not in inp
        assert '"' not in inp
        if mode == "ansi":
            return '"' + inp + '"'
        if mode == "postgres":
            return "`" + inp + "`"
        return "[" + inp + "]"
    elif len(inp) == 3:
        db = sql_quote_name(inp[0], mode=mode)
        schema_name = sql_quote_name(inp[1], mode=mode)
        tbl_name = sql_quote_name(inp[2], mode=mode)
        return db + "." + schema_name + "." + tbl_name
    else:
        schema_name = sql_quote_name(inp[0], mode=mode)
        tbl_name = sql_quote_name(inp[1], mode=mode)
        return schema_name + "." + tbl_name


def sql_quote_value(vl: Any):
    if vl is None:
        return "null"
    if isinstance(vl, str):
        return "'" + vl.replace("'", "''") + "'"
    if isinstance(vl, float):
        return str(vl)
    if isinstance(vl, int):
        return str(vl)
    if isinstance(vl, bool):
        return "1" if vl else "0"
    if isinstance(vl, datetime):
        return "'" + vl.isoformat() + "'"
    return "'" + str(vl).replace("'", "''") + "'"


@overload
def get_compatible_name(name: str) -> str: ...


@overload
def get_compatible_name(name: tuple[str, str]) -> tuple[str, str]: ...


@overload
def get_compatible_name(name: tuple[str, str, str]) -> tuple[str, str, str]: ...


def get_compatible_name(name: SQLObjectNameType) -> SQLObjectNameType:
    if isinstance(name, str):
        first_char = name[0]
        if not (
            (ord(first_char) >= ord("a") and ord(first_char) <= ord("z"))
            or (ord(first_char) >= ord("A") and ord(first_char) <= ord("Z"))
        ):
            return get_compatible_name("c_" + name)
        replace_map = {"é": "e", "ê": "e", "â": "a", "è": "e", "ä": "a", "ö": "o", "ü": "u", " ": "_"}
        for tr, tv in replace_map.items():
            name = name.replace(tr, tv)
        return name
    else:
        assert isinstance(name, tuple)
        return tuple((get_compatible_name(n) for n in name))  # type: ignore
