from bmsdna.sql_utils.db_io.source import WriteInfo
from bmsdna.sql_utils.lake.lake_meta import get_metadata
from bmsdna.sql_utils.lake.types import FieldWithType, LakeMetadata, SQLField
from .source import ImportSource
import os
import urllib.parse
from bmsdna.sql_utils.query import build_connection_string, get_connection, ConnectionParams
from .sqlschema import convert_to_sql_field
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import aiohttp
    from bmsdna.sql_utils.dbapi import Connection

logger = logging.getLogger(__name__)


async def _req_to_json_batches(req: "aiohttp.ClientResponse", batch_size=1000):
    current_batch: list[str] = []
    async for line in req.content:
        sline = line.decode("utf-8")
        current_batch.append(sline)
        if len(current_batch) > batch_size:
            yield "[" + ",".join(current_batch) + "]"
            current_batch = []
    if len(current_batch) > 0:
        yield "[" + ",".join(current_batch) + "]"
        current_batch = []


class LakeSource(ImportSource):
    def __init__(
        self,
        tag_name: str,
        lake_table_name: str,
        lake_api_auth: tuple[str, str] | None = None,
        *,
        use_json_insert=False,
    ) -> None:
        super().__init__()
        self.tag_name = tag_name
        self.lake_table_name = lake_table_name
        self.lake_api_auth = lake_api_auth or (os.getenv("LAKE_API_USER", ""), os.getenv("LAKE_API_PWD", ""))
        self._meta: LakeMetadata | None = None
        self.use_json_insert = use_json_insert

    def _get_meta(self):
        if self._meta is None:
            jsd: LakeMetadata = get_metadata(self.tag_name, self.lake_table_name, auth=self.lake_api_auth)
            self._meta = jsd
        return self._meta

    def get_partition_values(self) -> list[dict]:
        jsd = self._get_meta()
        return jsd["partition_values"]

    def get_schema(self) -> list[SQLField]:
        jsd = self._get_meta()
        fields = jsd.get("data_schema", jsd.get("schema", None))
        return [convert_to_sql_field(f) for f in fields]

    def get_last_change_date(self):
        jsd = self._get_meta()
        return datetime.fromisoformat(jsd["modified_date"])

    async def write_to_sql_server(
        self,
        target_table: str | tuple[str, str],
        connection_string: "ConnectionParams",
        partition_filters: dict | None,
        select: list[str] | None,
    ) -> WriteInfo:
        s_format = "arrow-stream" if not self.use_json_insert else "ndjson"
        full_url = (
            os.getenv(
                "LAKE_API_INSTANCE",
                "https://bmsadbprdeuw-bmanalyticssapi-stage.azurewebsites.net/api/v1/",
            )
            + self.tag_name
            + "/"
            + self.lake_table_name
        ) + f"?format={s_format}&jsonify_complex=True&limit=-1"
        if select:
            full_url += "&$select=" + ",".join(select)
        if partition_filters and len(partition_filters) > 0:
            full_url += "&" + "&".join(
                [
                    urllib.parse.quote(str(k), safe="") + "=" + urllib.parse.quote(str(v), safe="")
                    for k, v in partition_filters.items()
                ]
            )
        # r = make_lake_api_request(url_part, filters, format="arrow-stream", auth=lake_api_auth)
        conn_str_maybe = connection_string() if callable(connection_string) else connection_string
        if self.use_json_insert or (not isinstance(conn_str_maybe, str) and not isinstance(conn_str_maybe, dict)):
            from .json_insert import insert_into_table_via_json
            import aiohttp

            with get_connection(conn_str_maybe) as con:
                schema = self.get_schema()
                filtered_schema = schema if not select else [f for f in schema if f.column_name in select]
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        full_url, auth=aiohttp.BasicAuth(self.lake_api_auth[0], self.lake_api_auth[1])
                    ) as req:
                        req.raise_for_status()
                        r = _req_to_json_batches(req)
                        await insert_into_table_via_json(
                            json_batches=r, table_name=target_table, connection=con, schema=filtered_schema
                        )
                        col_names = [f.column_name for f in filtered_schema]
                con.commit()
            return WriteInfo(column_names=col_names, table_name=target_table)
        else:
            logger.info(f"Get Data from {full_url}")
            from lakeapi2sql.bulk_insert import insert_http_arrow_stream_to_sql

            table_str = target_table if isinstance(target_table, str) else target_table[0] + "." + target_table[1]
            connection_string_sql = build_connection_string(conn_str_maybe, odbc=False)
            res = await insert_http_arrow_stream_to_sql(
                connection_string_sql, table_str, full_url, self.lake_api_auth, None
            )
            colnames = [f["name"] for f in res["fields"]]
            # r.raise_for_status()

            return WriteInfo(column_names=colnames, table_name=target_table)
