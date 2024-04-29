from abc import abstractmethod, ABC
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bmsdna.sql_utils.lake.types import FieldWithType


@dataclass(frozen=True)
class WriteInfo:
    column_names: list[str]
    table_name: str | tuple[str, str]


class ImportSource(ABC):
    @abstractmethod
    async def write_to_sql_server(
        self,
        target_table: str | tuple[str, str],
        connection_string: str | dict,
        partition_filters: dict | None,
        select: list[str] | None = None,
    ) -> WriteInfo:
        ...

    @abstractmethod
    def get_partition_values(self) -> list[dict] | None:
        ...

    @abstractmethod
    def get_schema(self) -> "list[FieldWithType]":
        ...

    @abstractmethod
    def get_last_change_date(self) -> datetime | None:
        ...

    def get_constant_values(
        self, partition_filter: dict | None, *, select: list[str] | None
    ) -> "dict[str, tuple[FieldWithType, Any]]":
        from bmsdna.sql_utils.lake.types import FieldWithType

        partition_filter = partition_filter or {}
        sc = self.get_schema()
        res: dict[str, tuple[FieldWithType, Any]] = {}
        for fn in partition_filter.keys():
            scf = next((f for f in sc if f["name"] == fn))
            res[scf["name"]] = (scf, partition_filter[fn])
        for f in sc:
            if (
                f["name"] not in partition_filter
                and f.get("max_str_length", None) is None
                and f["type"]["type_str"] == "string"
            ):
                res[f["name"]] = (f, None)
        return res
