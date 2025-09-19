from dataclasses import dataclass
from typing import Any, Callable, List, Literal, Optional, TypeVar, TYPE_CHECKING, Mapping
from typing_extensions import TypedDict, NotRequired
from bmsdna.sql_utils.lake import FieldWithType, SQLField
from bmsdna.sql_utils.server_info import DBInfo
from .db_logging import init_logging, insert_into_log
from .sqlschema import (
    create_table,
    is_table_empty,
    get_max_update_col_value,
    CreateTableCallbackParams,
    sql_quote_value_with_type,
    get_str_length,
)
from bmsdna.sql_utils.query import sql_quote_name, get_connection, sql_quote_value
from bmsdna.sql_utils.db_io.source import ImportSource
import uuid
import logging
from datetime import datetime
from bmsdna.sql_utils.db_io.meta_sql_store import set_extended_property, get_extended_property
from ..case_preserving_set import CasePreservingSet

if TYPE_CHECKING:
    from bmsdna.sql_utils.dbapi import Connection
    from bmsdna.sql_utils.query import ConnectionParams
    from bmsdna.sql_utils.db_io.source import WriteInfo
    from asyncio import Task

import sys

if sys.version_info < (3, 11, 0):
    import dateutil.parser

    iso_parse = dateutil.parser.isoparse
else:
    iso_parse = datetime.fromisoformat
logger = logging.getLogger(__name__)


is_log_inited = False


def _get_filter_sql(partition_filter: Optional[dict], tbl_name: Optional[str] = None):
    return (
        " AND ".join(
            [
                (sql_quote_name(tbl_name) + "." if tbl_name else "")
                + sql_quote_name(col)
                + (("=" + sql_quote_value(value)) if value is not None else " IS NULL")
                for col, value in partition_filter.items()
            ]
        )
        if partition_filter
        else None
    )


def _str_part_filter(partition_filter: Optional[dict]):
    return "&".join((k + "=" + str(v) for k, v in partition_filter.items())) if partition_filter else None


async def _do_merge(
    source: ImportSource,
    target_table: tuple[str, str],
    schema: list[SQLField],
    conn: "Connection",
    partition_filter: Optional[dict],
    primary_keys: list[str],
    connection_string: "ConnectionParams",
    select: list[str] | None,
    temp_table_callback: list[Callable[[CreateTableCallbackParams], Any]] | None,
    constant_values: Mapping[str, tuple[SQLField, Any]] | None,
):
    temp_table_name = "##" + target_table[1] + "_" + str(uuid.uuid4()).replace("-", "")
    create_table(
        temp_table_name,
        schema,
        conn,
        primary_keys=[],
        overwrite=True,
        callback=temp_table_callback,
        default_values=constant_values,
    )
    write_info = await source.write_to_sql_server(temp_table_name, connection_string, partition_filter, select)
    await execute_merge(conn, target_table, write_info, partition_filter, primary_keys, incl_delete=True)
    return temp_table_name


async def _do_merge_updatecol(
    source: ImportSource,
    target_table: tuple[str, str],
    schema: list[SQLField],
    conn: "Connection",
    partition_filter: Optional[dict],
    primary_keys: list[str],
    update_col: str,
    connection_string: "ConnectionParams",
    select: list[str] | None,
    table_per_partition: bool,
    constant_values: Mapping[str, tuple[SQLField, Any]] | None,
    temp_table_callback: list[Callable[[CreateTableCallbackParams], Any]] | None,
) -> list[str]:
    vl = get_max_update_col_value(conn, target_table, update_col, _get_filter_sql(partition_filter))
    if vl is None:
        return await _do_full_load(
            source=source,
            target_table=target_table,
            schema=schema,
            conn=conn,
            partition_filter=partition_filter,
            connection_string=connection_string,
            is_empty=False,
            select=select,
            table_per_partition=table_per_partition,
            temp_table_callback=temp_table_callback,
            constant_values=constant_values,
            after_swap=None,
            temp_mode="global_temp",
        )
    else:
        temp_table_name_pk = "##" + target_table[1] + "_" + str(uuid.uuid4()).replace("-", "") + "_pk"
        temp_table_name_updates = "##" + target_table[1] + "_" + str(uuid.uuid4()).replace("-", "") + "_updates"
        create_table(
            temp_table_name_pk,
            [f for f in schema if f.column_name in primary_keys],
            conn,
            [],
            True,
            callback=temp_table_callback,
            default_values=constant_values,
        )
        create_table(
            temp_table_name_updates,
            schema,
            conn,
            [],
            True,
            callback=temp_table_callback,
            default_values=constant_values,
        )
        write_info_pk = await source.write_to_sql_server(
            temp_table_name_pk, connection_string, partition_filter or {}, primary_keys
        )

        write_info_updates = await source.write_to_sql_server(
            temp_table_name_updates, connection_string, (partition_filter or {}) | {update_col + "_gte": vl}, select
        )
        exclude_cols = [f.column_name for f in schema if (get_str_length(f.data_type) or 0) > 8000]
        await execute_merge(
            conn,
            target_table,
            write_info_updates,
            partition_filter,
            primary_keys,
            incl_delete=False,
            exclude_compare_cols=exclude_cols,
        )
        conn.commit()
        filter_sql = _get_filter_sql(partition_filter, "trg") or "1=1"
        some_pk = primary_keys[0]
        pk_eq = " AND ".join(("src." + sql_quote_name(pk) + "=trg." + sql_quote_name(pk) for pk in primary_keys))
        delete_stmt = f"DELETE trg FROM {sql_quote_name(target_table)} trg LEFT JOIN {temp_table_name_pk} src ON {pk_eq} WHERE {filter_sql} AND src.{sql_quote_name(some_pk)} is null"
        with conn.cursor() as cur:
            cur.execute(delete_stmt)
        conn.commit()
        return [temp_table_name_pk, temp_table_name_updates]


FULL_TEMP_MODES = Literal["global_temp", "table_swap"]


@dataclass(frozen=True)
class AfterSwapParams:
    target_table: tuple[str, str]
    conn: "Connection"
    partition_filter: Optional[dict]
    table_per_partition: bool = False


async def _do_full_load(
    *,
    source: ImportSource,
    target_table: tuple[str, str],
    schema: list[SQLField],
    conn: "Connection",
    partition_filter: Optional[dict],
    connection_string: "ConnectionParams",
    is_empty: bool,
    table_per_partition: bool,
    select: list[str] | None,
    temp_mode: FULL_TEMP_MODES = "global_temp",
    after_swap: list[Callable[[AfterSwapParams], Any]] | None,
    temp_table_callback: list[Callable[[CreateTableCallbackParams], Any]] | None,
    constant_values: Mapping[str, tuple[SQLField, Any]] | None,
):
    if is_empty:  # insert directly
        await source.write_to_sql_server(target_table, connection_string, partition_filter, select)
        return []
    elif temp_mode == "table_swap":
        temp_table_name = (target_table[0], target_table[1] + "_staging4fl")
        create_table(
            temp_table_name,
            schema,
            conn,
            primary_keys=[],
            overwrite=True,
            callback=temp_table_callback,
            default_values=constant_values,
        )
        select_4_insert = select
        if constant_values:
            select_4_insert = select or [f.column_name for f in schema]
            select_4_insert = [s for s in select_4_insert if s not in constant_values.keys()]
        write_info = await source.write_to_sql_server(
            temp_table_name, connection_string, partition_filter, select_4_insert
        )
        with conn.cursor() as cur:
            cur.execute(
                f"DROP TABLE IF EXISTS {sql_quote_name(target_table)}; exec sp_rename '{sql_quote_name(temp_table_name)}', '{target_table[1]}'"
            )
        if after_swap is not None:
            for a in after_swap:
                a(AfterSwapParams(target_table, conn, partition_filter, table_per_partition))
        return []
    else:
        temp_table_name = "##" + target_table[1] + "_" + str(uuid.uuid4()).replace("-", "")
        create_table(
            temp_table_name,
            schema,
            conn,
            primary_keys=[],
            overwrite=True,
            callback=temp_table_callback,
            default_values=constant_values,
        )
        select_4_insert = select
        if constant_values:
            select_4_insert = select or [f.column_name for f in schema]
            select_4_insert = [s for s in select_4_insert if s not in constant_values.keys()]
        write_info = await source.write_to_sql_server(
            temp_table_name, connection_string, partition_filter, select_4_insert
        )
        execute_full_load(conn, target_table, write_info, partition_filter)
    return [temp_table_name]


async def insert_into_table_partition(
    *,
    source: ImportSource,
    target_table: tuple[str, str],
    connection: "ConnectionParams",
    partition_filter: Optional[dict],
    schema: list[SQLField],
    primary_keys: list[str] | None,
    update_col: Optional[str],
    select: Optional[list[str]],
    skip_create_table=False,
    constant_values: Mapping[str, tuple[SQLField, Any]] | None = None,
    calculated_values: Mapping[str, str] | None = None,
    temp_full_mode: FULL_TEMP_MODES = "global_temp",
    after_swap: list[Callable[[AfterSwapParams], Any]] | None = None,
    table_callback: list[Callable[[CreateTableCallbackParams], Any]] | None,
    temp_table_callback: list[Callable[[CreateTableCallbackParams], Any]] | None,
    table_per_partition: bool,
):
    if select:
        partition_filter_keys = partition_filter.keys() if partition_filter and not table_per_partition else []
        schema = [
            f
            for f in schema
            if f.column_name in select
            or f.column_name in (primary_keys or [])
            or f.column_name in partition_filter_keys
        ]
    partition_filter_str = _str_part_filter(partition_filter)
    temp_tables = []

    with get_connection(connection) as conn:
        if not skip_create_table:
            try:
                init_logging(conn)
            except Exception as err:
                logger.warning(f"Could not initialize logging: {err}")
        try:
            insert_into_log(conn, target_table, "start_load", partition_filter=partition_filter_str)

            if not skip_create_table:
                create_table(
                    target_table,
                    schema,
                    conn,
                    primary_keys=primary_keys,
                    overwrite=False,
                    callback=table_callback,
                    default_values=constant_values,
                    calculated_values=calculated_values,
                )
            is_target_empty = is_table_empty(
                conn, target_table, _get_filter_sql(partition_filter if not table_per_partition else None)
            )
            conn.commit()
            if is_target_empty or primary_keys is None or len(primary_keys) == 0:
                temp_tables = await _do_full_load(
                    source=source,
                    target_table=target_table,
                    schema=schema,
                    conn=conn,
                    partition_filter=partition_filter,
                    table_per_partition=table_per_partition,
                    connection_string=connection,
                    is_empty=is_target_empty,
                    select=select,
                    temp_mode=temp_full_mode,
                    after_swap=after_swap,
                    constant_values=constant_values,
                    temp_table_callback=temp_table_callback,
                )
            elif len(primary_keys) > 0 and update_col is not None:
                temp_tables = await _do_merge_updatecol(
                    target_table=target_table,
                    source=source,
                    schema=schema,
                    conn=conn,
                    partition_filter=partition_filter,
                    table_per_partition=table_per_partition,
                    primary_keys=primary_keys,
                    update_col=update_col,
                    connection_string=connection,
                    constant_values=constant_values,
                    select=select,
                    temp_table_callback=temp_table_callback,
                )
            else:
                temp_tables = await _do_merge(
                    target_table=target_table,
                    source=source,
                    schema=schema,
                    conn=conn,
                    partition_filter=partition_filter,
                    constant_values=constant_values,
                    primary_keys=primary_keys,
                    connection_string=connection,
                    select=select,
                    temp_table_callback=temp_table_callback,
                )
            conn.commit()
            insert_into_log(conn, target_table, "end_load", partition_filter=partition_filter_str)
            conn.commit()
        except Exception as err:
            insert_into_log(conn, target_table, "error", partition_filter=partition_filter_str, error=str(err))
            raise err
        finally:
            temp_tables = temp_tables if isinstance(temp_tables, list) else [temp_tables]
            for temp_table_name in temp_tables:
                with conn.cursor() as cur:
                    sql = f"DROP TABLE IF EXISTS {sql_quote_name(temp_table_name)}"
                    logger.info(f"Executing SQL: {sql}")
                    cur.execute(sql)
                conn.commit()


def execute_full_load(
    conn: "Connection",
    sql_table_name: tuple[str, str],
    source_info: "WriteInfo",
    partition_filter: Optional[dict],
):
    partition_filter_str = _str_part_filter(partition_filter)
    cols_sql = ", ".join([sql_quote_name(cn) for cn in source_info.column_names])
    filter_sql = _get_filter_sql(partition_filter)
    deleteStmt = (
        f"DELETE FROM {sql_quote_name(sql_table_name)} WHERE {filter_sql}"
        if partition_filter
        else "TRUNCATE TABLE " + sql_quote_name(sql_table_name)
    )
    sql = f"""SET XACT_ABORT ON; 
                        BEGIN TRANSACTION;
                        {deleteStmt}
                        INSERT INTO {sql_quote_name(sql_table_name)}({cols_sql})
                        SELECT {cols_sql} FROM {sql_quote_name(source_info.table_name)}
                        COMMIT TRANSACTION
                        """
    logger.info(f"Executing SQL: {sql}")
    insert_into_log(conn, sql_table_name, "start_full", partition_filter=partition_filter_str, sql=sql)
    with conn.cursor() as cur:
        cur.execute(sql)


async def execute_merge(
    conn: "Connection",
    sql_table_name: tuple[str, str],
    source_info: "WriteInfo",
    partition_filter: Optional[dict],
    primary_keys: List[str],
    *,
    incl_delete: bool,
    exclude_compare_cols: Optional[List[str]] = None,
):
    partition_filter_str = _str_part_filter(partition_filter)
    exclude_compare_cols = exclude_compare_cols or []
    cols_sql = ", ".join([sql_quote_name(cn) for cn in source_info.column_names])
    cols_sql_src = ", ".join(["src." + sql_quote_name(cn) for cn in source_info.column_names])
    cols_sql_src_compare = ", ".join(
        ["src." + sql_quote_name(cn) for cn in source_info.column_names if cn not in exclude_compare_cols]
    )
    cols_sql_trg_compare = ", ".join(
        ["trg." + sql_quote_name(cn) for cn in source_info.column_names if cn not in exclude_compare_cols]
    )
    filter_sql_trg = _get_filter_sql(partition_filter, "trg") or "1=1"
    pk_eq = " AND ".join(("src." + sql_quote_name(pk) + "=trg." + sql_quote_name(pk) for pk in primary_keys))
    update_cols = ",\r\n\t ".join(
        ("trg." + sql_quote_name(cn) + "=src." + sql_quote_name(cn) for cn in source_info.column_names)
    )
    delete_stuff = f"WHEN NOT MATCHED BY SOURCE AND {filter_sql_trg} THEN DELETE" if incl_delete else ""
    sql = f"""SET XACT_ABORT ON; 
            MERGE {sql_quote_name(sql_table_name)} as trg
            USING {sql_quote_name(source_info.table_name)} as src
            ON {pk_eq}
            WHEN NOT MATCHED THEN INSERT({cols_sql})
                VALUES({cols_sql_src})
            WHEN MATCHED AND EXISTS (
                SELECT {cols_sql_src_compare}
                except
                SELECT {cols_sql_trg_compare}
                )
                THEN 
                UPDATE 
                    SET {update_cols}
            {delete_stuff};
                        """
    logger.info(f"Executing SQL: {sql}")
    insert_into_log(conn, sql_table_name, "start_merge", partition_filter=partition_filter_str, sql=sql)
    with conn.cursor() as cur:
        cur.execute(sql)


def _part_tbl(part_values: Mapping):
    if len(part_values) == 1:
        return "_" + str(list(part_values.values())[0])
    sorted_items = sorted(part_values.items(), key=lambda x: x[0])  # sort keys alphabetically
    return "_" + "_".join(str(v) for _, v in sorted_items)


T = TypeVar("T")


def _make_list(x: T | list[T] | None) -> list[T] | None:
    if x is None or isinstance(x, list):
        return x
    return [x]


def _get_select(c: str, constant_values: Mapping, calculated_columns: Mapping):
    if c not in constant_values and c not in calculated_columns:
        return sql_quote_name(c)
    if c in constant_values.keys():
        return f"{sql_quote_value_with_type(*constant_values[c])} as {sql_quote_name(c)}"
    return calculated_columns[c] + " as  " + sql_quote_name(c)


async def has_delta(
    source: ImportSource,
    connection: "str | dict | Connection",
    target_table: tuple[str, str],
):
    owns_conn = False
    try:
        if isinstance(connection, str) or isinstance(connection, dict):
            connection = get_connection(connection)
            owns_conn = True
        mod_date = source.get_last_change_date()
        if mod_date:
            ld = get_extended_property(connection, target_table, "sql_utils_load_date")
            if ld:
                dt = iso_parse(ld)
                if dt >= mod_date:
                    return False
    finally:
        if owns_conn:
            if not isinstance(connection, str) and not isinstance(connection, dict):
                connection.close()
    return True


async def _execute(
    source: ImportSource,
    connection_string: "ConnectionParams",
    target_table: tuple[str, str],
    primary_keys: list[str] | None = None,
    update_col: Optional[str] = None,
    select: Optional[list[str]] = None,
    table_per_partition=False,
    after_swap: list[Callable[[AfterSwapParams], Any]] | Callable[[AfterSwapParams], Any] | None = None,
    temp_full_mode: FULL_TEMP_MODES | None = None,
    table_callback: (
        list[Callable[[CreateTableCallbackParams], Any]] | Callable[[CreateTableCallbackParams], Any] | None
    ) = None,
    temp_table_callback: (
        list[Callable[[CreateTableCallbackParams], Any]] | Callable[[CreateTableCallbackParams], Any] | None
    ) = None,
    calculated_columns: Mapping[str, Any] | None = None,
    await_partitions=True,
    force=False,
):
    calculated_columns = calculated_columns or dict()
    part_values = source.get_partition_values()
    schema = source.get_schema()
    mod_date = source.get_last_change_date()
    if not force and mod_date:
        with get_connection(connection_string) as conn:
            ld = get_extended_property(conn, target_table, "sql_utils_load_date")
            if ld:
                dt = iso_parse(ld)
                if dt >= mod_date:
                    logger.info(f"Skipping table {target_table}, because it is already up to date")
                    return
    assert schema is not None
    if part_values is not None and len(part_values) > 0:
        table_sql: list[str] = []
        if table_per_partition:
            all_cols = CasePreservingSet(select or [f.column_name for f in schema])
            for k in calculated_columns.keys():
                all_cols.add(k)
            for k in part_values[0].keys():
                all_cols.add(k)
        else:
            all_cols = CasePreservingSet()
        first = True
        proms: "list[Task]" = []
        for item in part_values:
            target_table_part = target_table
            constant_values = source.get_constant_values(item, select=select)
            if table_per_partition:
                target_table_part = (target_table[0], target_table[1] + _part_tbl(item))
                sql = (
                    "SELECT "
                    + ", ".join(_get_select(c, constant_values, calculated_columns) for c in all_cols)
                    + " FROM "
                    + sql_quote_name(target_table_part)
                )
                select = select or [
                    f.column_name
                    for f in schema
                    if f.column_name not in constant_values.keys() and f.column_name not in calculated_columns.keys()
                ]
                table_sql.append(sql)
            prom = insert_into_table_partition(
                target_table=target_table_part,
                source=source,
                connection=connection_string,
                skip_create_table=not first and not table_per_partition,
                partition_filter=item,
                table_per_partition=table_per_partition,
                schema=schema,
                primary_keys=primary_keys,
                update_col=update_col,
                select=select,
                constant_values=(
                    constant_values if not table_per_partition else None
                ),  # for table per partition we handle it in the view
                temp_full_mode=temp_full_mode or ("table_swap" if table_per_partition else "global_temp"),
                after_swap=_make_list(after_swap),
                temp_table_callback=_make_list(temp_table_callback),
                table_callback=_make_list(table_callback),
            )
            if await_partitions:
                await prom
            else:
                import asyncio

                proms.append(asyncio.create_task(prom))
                if len(proms) > 5:
                    import asyncio

                    done, _ = await asyncio.wait(proms, return_when=asyncio.FIRST_COMPLETED)
                    for d in done:
                        proms.remove(d)

            first = False
        if not await_partitions:
            import asyncio

            await asyncio.wait(proms, return_when=asyncio.ALL_COMPLETED)
        if table_per_partition:
            select_4view = "\r\n UNION ALL\r\n ".join(table_sql)
            view = f"CREATE OR ALTER VIEW {sql_quote_name(target_table)} AS \r\n{select_4view}"

            with get_connection(connection_string) as conn:
                with conn.cursor() as cur:
                    cur.execute(view)

    else:
        constant_values = source.get_constant_values(None, select=select)

        select = select or [f.column_name for f in schema if f.column_name not in constant_values.keys()]
        await insert_into_table_partition(
            target_table=target_table,
            source=source,
            connection=connection_string,
            partition_filter=None,
            schema=schema,
            primary_keys=primary_keys,
            update_col=update_col,
            select=select,
            constant_values=constant_values,
            temp_full_mode=temp_full_mode or "global_temp",
            table_per_partition=False,
            after_swap=_make_list(after_swap),
            temp_table_callback=_make_list(temp_table_callback),
            table_callback=_make_list(table_callback),
        )

    with get_connection(connection_string) as conn:
        set_extended_property(
            conn,
            "View" if table_per_partition and part_values is not None and len(part_values) > 0 else "Table",
            target_table,
            "sql_utils_load_date",
            mod_date.isoformat() if mod_date else "",
        )
        conn.commit()


async def insert_into_table(
    *,
    source: ImportSource,
    connection_string: "ConnectionParams",
    target_table: tuple[str, str],
    primary_keys: list[str] | None = None,
    update_col: Optional[str] = None,
    select: Optional[list[str]] = None,
    table_per_partition=False,
    after_swap: list[Callable[[AfterSwapParams], Any]] | Callable[[AfterSwapParams], Any] | None = None,
    temp_full_mode: FULL_TEMP_MODES | None = None,
    table_callback: (
        list[Callable[[CreateTableCallbackParams], Any]] | Callable[[CreateTableCallbackParams], Any] | None
    ) = None,
    temp_table_callback: (
        list[Callable[[CreateTableCallbackParams], Any]] | Callable[[CreateTableCallbackParams], Any] | None
    ) = None,
    calculated_columns: Mapping[str, Any] | None = None,
    await_partitions=True,
    force=False,
):
    try:
        await _execute(
            source=source,
            connection_string=connection_string,
            target_table=target_table,
            primary_keys=primary_keys,
            update_col=update_col,
            select=select,
            table_per_partition=table_per_partition,
            after_swap=after_swap,
            temp_full_mode=temp_full_mode,
            table_callback=table_callback,
            temp_table_callback=temp_table_callback,
            calculated_columns=calculated_columns,
            await_partitions=await_partitions,
            force=force,
        )
    except Exception as err:
        if "Cannot create a row of size" in str(err):
            with get_connection(connection_string) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"drop table {sql_quote_name(target_table)}")
                conn.commit()
            await _execute(
                source=source,
                connection_string=connection_string,
                target_table=target_table,
                primary_keys=primary_keys,
                update_col=update_col,
                select=select,
                table_per_partition=table_per_partition,
                after_swap=after_swap,
                temp_full_mode=temp_full_mode,
                table_callback=table_callback,
                temp_table_callback=temp_table_callback,
                calculated_columns=calculated_columns,
                await_partitions=await_partitions,
                force=force,
            )
            return
        raise err


def get_create_index_callback(db_info: DBInfo):
    supports_ccx = db_info.supports_column_store_index()

    def create_index(prms: CreateTableCallbackParams):
        if prms.primary_keys is not None:
            return  # has already an index
        with prms.conn.cursor() as cur:
            if prms.action == "create":
                tname = prms.table_name if isinstance(prms.table_name, str) else prms.table_name[1]
                schema = prms.table_name[0] if isinstance(prms.table_name, tuple) else ""
                if supports_ccx:
                    cur.execute(
                        f"CREATE CLUSTERED COLUMNSTORE INDEX {sql_quote_name('CX_' + schema + '_' + tname)} ON {sql_quote_name((schema, tname))} WITH (DATA_COMPRESSION=COLUMNSTORE_ARCHIVE)"
                    )

    return create_index
