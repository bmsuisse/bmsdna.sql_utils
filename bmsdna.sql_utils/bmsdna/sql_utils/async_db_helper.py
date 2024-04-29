from typing import Any, Dict, List, Optional, Tuple, TypeVar, Union

from aioodbc import Connection
from bmsdna.sql_utils.query import SQLObjectNameType
from bmsdna.sql_utils.result import make_class_from_cursor
from bmsdna.sql_utils.sql_gen import get_param_style, get_proc_exec_sql
from typing_extensions import LiteralString

SomeDataClass = TypeVar("SomeDataClass")
Row = Tuple


async def get_one_real_row(cursor) -> Union[Row, None]:
    while cursor.description is None or len(cursor.description) == 0:
        if not await cursor.nextset():
            return None
    return await cursor.fetchone()


async def get_all_real_rows(cursor) -> Union[List[Row], None]:
    while cursor.description is None or len(cursor.description) == 0:
        if not await cursor.nextset():
            return None
    return await cursor.fetchall()


async def execute_proc_with_results(
    result_type: type[SomeDataClass],
    connection: Connection,
    name: SQLObjectNameType,
    arg_dict: Dict[LiteralString, Any] | None,
    commit=True,
) -> Optional[List[SomeDataClass]]:
    async with connection.cursor() as cur:
        st = get_param_style(connection)
        args = list(arg_dict.items()) if arg_dict else []
        strSQL = get_proc_exec_sql(name, args, st)
        prmValues = tuple([value for (_, value) in args])
        r = await cur.execute(
            strSQL,
            prmValues,
        )

        row = await get_all_real_rows(cur)
        if commit:
            await connection.commit()
        return make_class_from_cursor(result_type, cur.description, row)  # type: ignore


async def execute_proc_with_single_result(
    result_type: type[SomeDataClass],
    connection: Connection,
    name: SQLObjectNameType,
    arg_dict: Dict[LiteralString, Any] | None,
    commit=True,
) -> Optional[SomeDataClass]:
    async with connection.cursor() as cur:
        st = get_param_style(connection)
        args = list(arg_dict.items()) if arg_dict else []
        strSQL = get_proc_exec_sql(name, args, st)
        prmValues = tuple([value for (_, value) in args])
        r = cur.execute(
            strSQL,
            prmValues,
        )

        row = await get_one_real_row(cur)
        if commit:
            await connection.commit()
        assert cur.description is not None
        return make_class_from_cursor(result_type, cur.description, row)  # type: ignore


async def execute_proc_no_result(
    connection: Connection,
    name: SQLObjectNameType,
    arg_dict: Dict[LiteralString, Any] | None,
    commit=True,
):
    async with connection.cursor() as cur:
        st = get_param_style(connection)
        args = list(arg_dict.items()) if arg_dict else []
        strSQL = get_proc_exec_sql(name, args, st)
        prmValues = tuple([value for (_, value) in args])
        prmValues = tuple([value for (_, value) in arg_dict.items()]) if arg_dict else tuple()
        r = await cur.execute(
            strSQL,
            prmValues,
        )
        if commit:
            await connection.commit()
