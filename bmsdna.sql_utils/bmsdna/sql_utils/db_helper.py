from typing import Any, Dict, List, Optional, Tuple, TypeVar, Union

from bmsdna.sql_utils.dbapi import Connection
from bmsdna.sql_utils.query import SQLObjectNameType
from bmsdna.sql_utils.result import make_class_from_cursor
from bmsdna.sql_utils.sql_gen import get_param_style, get_proc_exec_sql
from typing_extensions import LiteralString
from dataclasses import dataclass

SomeDataClass = TypeVar("SomeDataClass")
Row = Tuple


def get_one_real_row(cursor: Any) -> Union[Row, None]:
    while cursor.description is None or len(cursor.description) == 0:
        if not cursor.nextset():
            return None
    return cursor.fetchone()


def get_all_real_rows(cursor: Any) -> Union[List[Row], None]:
    while cursor.description is None or len(cursor.description) == 0:
        if not cursor.nextset():
            return None
    return cursor.fetchall()


def execute_proc_with_results(
    result_type: type[SomeDataClass],
    connection: Connection,
    name: SQLObjectNameType,
    arg_dict: Dict[LiteralString, Any] | None,
    commit=True,
) -> Optional[List[SomeDataClass]]:
    with connection.cursor() as cur:
        st = get_param_style(connection)
        args = list(arg_dict.items()) if arg_dict else []
        strSQL = get_proc_exec_sql(name, args, st)
        prmValues = tuple([value for (_, value) in args])
        r = cur.execute(
            strSQL,
            prmValues,
        )

        row = get_all_real_rows(cur)
        if commit:
            connection.commit()
        assert cur.description is not None
        return make_class_from_cursor(result_type, cur.description, row)  # type: ignore


def execute_proc_with_single_result(
    result_type: type[SomeDataClass],
    connection: Connection,
    name: SQLObjectNameType,
    arg_dict: Dict[LiteralString, Any] | None,
    commit=True,
) -> Optional[SomeDataClass]:
    with connection.cursor() as cur:
        st = get_param_style(connection)
        args = list(arg_dict.items()) if arg_dict else []
        strSQL = get_proc_exec_sql(name, args, st)
        prmValues = tuple([value for (_, value) in args])
        r = cur.execute(
            strSQL,
            prmValues,
        )

        row = get_one_real_row(cur)
        if commit:
            connection.commit()
        assert cur.description is not None
        return make_class_from_cursor(result_type, cur.description, row)  # type: ignore


@dataclass(frozen=True)
class ExecInfo:
    row_counts: int
    messages: List[str]


def execute_proc_no_result(
    connection: Connection,
    name: SQLObjectNameType,
    arg_dict: Dict[LiteralString, Any] | None,
    commit=True,
):
    with connection.cursor() as cur:
        st = get_param_style(connection)
        args = list(arg_dict.items()) if arg_dict else []
        strSQL = get_proc_exec_sql(name, args, st)
        prmValues = tuple([value for (_, value) in args])
        prmValues = tuple([value for (_, value) in arg_dict.items()]) if arg_dict else tuple()
        messages = list()
        row_counts = 0
        cur.execute(
            strSQL,
            prmValues,
        )
        if "messages" in dir(cur):
            messages.append(cur.messages)  # type: ignore
        row_counts = row_counts + (cur.rowcount if cur.rowcount > 0 else 0)
        while cur.nextset():
            pass
        if commit:
            connection.commit()
        return ExecInfo(row_counts, messages)
