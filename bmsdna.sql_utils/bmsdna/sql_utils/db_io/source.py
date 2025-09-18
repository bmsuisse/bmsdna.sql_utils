from abc import abstractmethod, ABC
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping, Callable
import sqlglot.expressions as ex

if TYPE_CHECKING:
    from bmsdna.sql_utils.lake.types import SQLField
    from bmsdna.sql_utils.query import ConnectionParams


@dataclass(frozen=True)
class WriteInfo:
    column_names: list[str]
    table_name: str | tuple[str, str]


forbidden_cols = ["__hash", "__metadata"]


class ImportSource(ABC):
    def __init__(self):
        self.forbidden_cols = forbidden_cols

    @abstractmethod
    async def write_to_sql_server(
        self,
        target_table: str | tuple[str, str],
        connection_string: "ConnectionParams",
        partition_filters: dict | None,
        select: list[str] | None = None,
    ) -> WriteInfo: ...

    @abstractmethod
    def get_partition_values(self) -> list[dict] | None: ...

    @abstractmethod
    def get_schema(self) -> "list[SQLField]": ...

    @abstractmethod
    def get_last_change_date(self) -> datetime | None: ...

    def get_constant_values(
        self, partition_filter: dict | None, *, select: list[str] | None
    ) -> "Mapping[str, tuple[SQLField, Any]]":
        from bmsdna.sql_utils.lake.types import FieldWithType

        partition_filter = partition_filter or {}
        sc = self.get_schema()
        res: dict[str, tuple[SQLField, Any]] = {}
        for fn in partition_filter.keys():
            scf = next((f for f in sc if f.column_name == fn))
            res[scf.column_name] = (scf, partition_filter[fn])
        for f in sc:
            if (
                f.column_name not in partition_filter
                and len(f.data_type.expressions) == 0
                and f.data_type.Type in ex.DataType.TEXT_TYPES
            ):
                res[f.column_name] = (f, None)
        return res
