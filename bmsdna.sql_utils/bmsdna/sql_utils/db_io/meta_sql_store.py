from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from bmsdna.sql_utils.dbapi import Connection

from bmsdna.sql_utils import sql_quote_name, sql_quote_value


def get_extended_property(
    con: "Connection",
    tbl_name: tuple[str, str],
    name: str,
) -> str | None:
    sql = f"""select cast(value as nvarchar(1000)) from sys.extended_properties where major_id=OBJECT_ID('{sql_quote_name(tbl_name)}') and name={sql_quote_value(name)}"""
    with con.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
        if row is None:
            return None
        return row[0]


def set_extended_property(
    con: "Connection",
    object_type: Literal["Table", "View"],
    tbl_name: tuple[str, str],
    name: str,
    value: str,
):
    sql = f"""
        if exists(select * from sys.extended_properties where major_id=OBJECT_ID('{sql_quote_name(tbl_name)}') and name={sql_quote_value(name)})
        begin
        EXEC sp_updateextendedproperty @name = N{sql_quote_value(name)},
            @value = {sql_quote_value(value)},
            @level0type = N'Schema', @level0name = {sql_quote_value(tbl_name[0])},
            @level1type = N{sql_quote_value(object_type)}, @level1name = {sql_quote_value(tbl_name[1])}

        end
        else 
        begin
        EXEC sp_addextendedproperty @name = N{sql_quote_value(name)},
            @value = {sql_quote_value(value)},
            @level0type = N'Schema', @level0name = {sql_quote_value(tbl_name[0])},
            @level1type = N{sql_quote_value(object_type)}, @level1name = {sql_quote_value(tbl_name[1])}
        end"""
    with con.cursor() as cur:
        cur.execute(sql)
