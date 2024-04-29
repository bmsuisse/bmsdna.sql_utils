from pathlib import Path
from typing import Sequence, Any, TypeVar
import sqlglot.expressions as ex


def read_parquet(path: Path | list[Path] | ex.Expression | list[ex.Expression]) -> ex.Expression:
    if isinstance(path, list):
        return ex.func(
            "read_parquet",
            ex.array(*[ex.Literal.string(str(p)) if isinstance(p, Path) else p for p in path]),
            ex.EQ(
                this=ex.Column(this=ex.Identifier(this="union_by_name", quoted=False)),
                expression=ex.Boolean(this=True),
            ),
        )
    return ex.func("read_parquet", ex.Literal.string(str(path)) if isinstance(path, Path) else path)


def union(selects: Sequence[ex.Expression], *, distinct: bool) -> ex.Expression:
    if len(selects) == 0:
        raise ValueError("No selects to union")
    elif len(selects) == 1:
        return selects[0]
    elif len(selects) == 2:
        return ex.union(selects[0], selects[1], distinct=distinct)
    else:
        return ex.union(selects[0], union(selects[1:], distinct=distinct), distinct=distinct)


def filter_via_dict(conditions: dict[str, Any] | None):
    if not conditions or len(conditions) == 0:
        return None
    return ex.and_(
        *[
            (
                ex.EQ(this=ex.column(k, quoted=True), expression=ex.convert(v))
                if v is not None
                else ex.Is(this=ex.column(k, quoted=True), expression=ex.Null())
            )
            for k, v in conditions.items()
        ]
    )


def table_from_tuple(name: str | tuple[str, str] | tuple[str, str, str], alias: str | None = None) -> ex.Table:
    if alias is not None:
        assert " " not in alias
        assert "-" not in alias
        assert "'" not in alias
        assert '"' not in alias
        assert "*" not in alias
        assert "/" not in alias
        assert "\\" not in alias

    if isinstance(name, str):
        return ex.Table(
            this=ex.Identifier(this=name, quoted=True),
            alias=ex.Identifier(this=alias, quoted=False) if alias else None,
        )
    if len(name) == 2:
        return ex.Table(
            this=ex.Identifier(this=name[1], quoted=True),
            db=ex.Identifier(this=name[0], quoted=True),
            alias=ex.Identifier(this=alias, quoted=False) if alias else None,
        )
    if len(name) == 3:
        return ex.Table(
            this=ex.Identifier(this=name[2], quoted=True),
            db=ex.Identifier(this=name[1], quoted=True),
            catalog=ex.Identifier(this=name[0], quoted=True),
            alias=ex.Identifier(this=alias, quoted=False) if alias else None,
        )
    raise ValueError(f"Invalid name: {name}")
