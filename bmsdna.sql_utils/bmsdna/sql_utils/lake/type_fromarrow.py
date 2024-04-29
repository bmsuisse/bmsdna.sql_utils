from typing import cast, TYPE_CHECKING
from .types import FieldWithType, FieldType

if TYPE_CHECKING:
    from pyarrow import DataType


def recursive_get_type(t: "DataType", jsonify_complex: bool) -> FieldType:
    import pyarrow as pa

    is_complex = pa.types.is_nested(t)

    return FieldType(
        type_str=str(pa.string()) if is_complex and jsonify_complex else str(t),
        fields=(
            [
                FieldWithType(name=f.name, type=recursive_get_type(f.type, jsonify_complex))
                for f in [t.field(find) for find in range(0, cast(pa.StructType, t).num_fields)]
            ]
            if pa.types.is_struct(t) and not jsonify_complex
            else None
        ),
        inner=(
            recursive_get_type(t.value_type, jsonify_complex)
            if pa.types.is_list(t)
            or pa.types.is_large_list(t)
            or pa.types.is_fixed_size_list(t)
            and t.value_type is not None
            and not jsonify_complex
            else None
        ),
    )
