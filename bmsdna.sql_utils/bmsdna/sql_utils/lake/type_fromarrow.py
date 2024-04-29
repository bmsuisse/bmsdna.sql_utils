from typing import cast, TYPE_CHECKING
from .types import FieldWithType, SQLField
import sqlglot.expressions as ex

if TYPE_CHECKING:
    from pyarrow import DataType


def recursive_get_type(t: "DataType", jsonify_complex: bool, dialect: str = "spark") -> ex.DataType:
    import pyarrow as pa

    is_complex = pa.types.is_nested(t)
    if is_complex and not jsonify_complex:
        return ex.DataType.build(str(t), dialect=dialect)
    if is_complex and jsonify_complex:
        return ex.DataType.build("string", dialect=dialect)

    return ex.DataType.build(str(t), dialect=dialect)
