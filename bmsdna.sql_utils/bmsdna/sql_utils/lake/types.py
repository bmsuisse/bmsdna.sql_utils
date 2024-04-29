from typing_extensions import TypedDict, NotRequired
from typing import List, Optional


class FieldType(TypedDict):
    type_str: str
    fields: NotRequired[Optional[list["FieldWithType"]]]
    inner: NotRequired[Optional["FieldType"]]


class FieldWithType(TypedDict):
    name: str
    type: FieldType
    max_str_length: NotRequired[Optional[int]]


class LakeMetadata(TypedDict):
    partition_values: list[dict]
    partition_columns: list[str]
    max_string_lengths: dict[str, int]
    schema: list[FieldWithType]
    modified_date: str


class LakeMetadataWithIntegrity(LakeMetadata):
    has_integrity_value: bool
    integrity_sums: List[dict]
    sql_integrity_sums: List[dict]
