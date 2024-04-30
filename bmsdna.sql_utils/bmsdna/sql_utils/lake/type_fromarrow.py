from typing import cast, TYPE_CHECKING
from .types import FieldWithType, SQLField
import sqlglot.expressions as ex

if TYPE_CHECKING:
    from pyarrow import DataType


def recursive_get_type(t: "DataType", jsonify_complex: bool, dialect: str = "spark") -> ex.DataType:
    import pyarrow as pa
    import pyarrow.types as pat

    if pat.is_decimal(t):
        return ex.DataType.build(f"decimal({t.precision},{t.scale})", dialect="spark")
    if pat.is_date(t):
        return ex.DataType.build("date", dialect="tsql")
    if pat.is_timestamp(t):
        return ex.DataType.build("datetime2", dialect="tsql")
    if pat.is_null(t):
        return ex.DataType.build("null")
    is_complex = pa.types.is_nested(t)
    if is_complex and not jsonify_complex:
        return ex.DataType.build(str(t), dialect=dialect)
    if is_complex and jsonify_complex:
        return ex.DataType.build("string", dialect=dialect)

    return ex.DataType.build(str(t), dialect=dialect)
