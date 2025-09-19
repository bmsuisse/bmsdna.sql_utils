from typing import TYPE_CHECKING
from ..query import sql_quote_name, SQLObjectNameType

if TYPE_CHECKING:
    from bmsdna.sql_utils.dbapi import Connection


def drop_table_or_view(connection: "Connection", table_name: SQLObjectNameType) -> None:
    table_name_str = sql_quote_name(table_name)
    with connection.cursor() as cur:
        cur.execute(
            f"""declare @type nvarchar(100) = (SELECT type FROM sys.objects o where o.object_id=object_id('{table_name_str}'));
IF @type='U'
begin
	drop table if exists {table_name_str};
end
ELSE IF @type='V'
begin
	drop view if exists {table_name_str};
end
else if @type is not null 
begin
	raiserror('type not supported', 16,1,1);
end	"""
        )
