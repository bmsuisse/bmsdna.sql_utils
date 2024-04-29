from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias

if TYPE_CHECKING:
    import pyodbc


class Cursor(Protocol):
    description: Sequence | None
    rowcount: int
    arraysize: int

    def nextset(self) -> bool:
        ...

    def close(self) -> None:
        ...

    def execute(self, operation: Any, *args, **kwargs):
        ...

    def executemany(self, operation: Any, seq_of_parameters: Sequence | Mapping, *args, **kwargs):
        ...

    def fetchone(self) -> Sequence | None:
        ...

    def fetchmany(self, size: int = 0) -> Sequence[Sequence]:
        ...

    def fetchall(self, size: int = 0) -> Sequence[Sequence]:
        ...

    def setinputsizes(self, sizes: Sequence):
        ...

    def setoutputsize(self, size: Any, column: int | None = None):
        ...

    def __enter__(self) -> "Cursor":
        ...

    def __exit__(self, exc_type, exc_val, exc_tb):
        ...


class ConnectionT(Protocol):
    def close(self) -> None:
        ...

    def commit(self) -> None:
        ...

    def cursor(self, *args, **kwargs) -> Cursor:
        ...


Connection: TypeAlias = "ConnectionT | pyodbc.Connection"
