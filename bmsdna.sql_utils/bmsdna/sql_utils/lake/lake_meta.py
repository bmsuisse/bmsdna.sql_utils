from typing_extensions import TypedDict, NotRequired
from typing import Optional, Tuple
import os
import requests

from bmsdna.sql_utils.lake.types import LakeMetadata


def make_lake_api_request(
    url_part: str, params: Optional[dict], *, auth: Tuple[str, str], format: Optional[str] = None
):
    lake_api_base_url = os.getenv(
        "LAKE_API_INSTANCE",
        "https://bmsadbprdeuw-bmanalyticssapi-stage.azurewebsites.net/api/v1/",
    )
    if params is None:
        params = {}
    url = lake_api_base_url.removesuffix("/") + "/" + url_part
    r = requests.get(
        url,
        params=params | {"format": format, "jsonify_complex": True, "limit": -1} if format else params,
        auth=auth,
    )
    r.raise_for_status()
    return r


def get_metadata(tag_name: str, lake_table_name: str, auth: Tuple[str, str], params: dict | None = None):
    try:
        r = make_lake_api_request(
            tag_name + "/" + lake_table_name + "/metadata_detail",
            {"jsonify_complex": True} | (params or {}),
            auth=auth,
        )
        jsd: LakeMetadata = r.json()
    except requests.exceptions.HTTPError as e:
        if "$engine" not in (params or {}):
            r = make_lake_api_request(
                tag_name + "/" + lake_table_name + "/metadata_detail",
                {"jsonify_complex": True, "$engine": "duckdb"} | (params or {}),
                auth=auth,
            )
            jsd: LakeMetadata = r.json()
    return jsd


def execute_lake_sql(sql: str, auth: Tuple[str, str]) -> list[dict]:
    lake_api_url = (
        os.getenv("LAKE_API_INSTANCE", "https://bmsadbprdeuw-bmanalyticssapi-stage.azurewebsites.net/api/v1/")
        .removesuffix("/")
        .removesuffix("/v1")
        + "/sql"
    )
    r = requests.post(
        lake_api_url,
        params={"format": "json", "$engine": "duckdb"},
        auth=auth,
        data=sql,
        headers={"Content-Type": "application/sql"},
    )
    r.raise_for_status()
    return r.json()


def get_lake_integrity_sums(tag_name: str, lake_table_name: str, partition_columns: list[str], auth: Tuple[str, str]):
    from bmsdna.sql_utils.integrity_check import get_integrity_sum_sql_all

    sql = get_integrity_sum_sql_all(tag_name + "_" + lake_table_name, partition_columns, dialect="duckdb_polars")
    return execute_lake_sql(sql, auth)
