import dataclasses
from typing import TYPE_CHECKING, Any, List, Sequence, Tuple, Type, TypeVar, Union, overload

if TYPE_CHECKING:
    import pydantic

SomeDataClass = TypeVar("SomeDataClass")
Row = Tuple


@overload
def make_class_from_cursor(classtype: type[dict], description: Sequence[Tuple], values: Sequence) -> list[dict]: ...


@overload
def make_class_from_cursor(classtype: type[dict], description: Sequence[Tuple], values: tuple) -> dict: ...


@overload
def make_class_from_cursor(classtype: type, description: Sequence[Tuple], values: None) -> None: ...


@overload
def make_class_from_cursor(
    classtype: type[SomeDataClass], description: Sequence[Tuple], values: Sequence[Row]
) -> List[SomeDataClass]: ...


@overload
def make_class_from_cursor(
    classtype: type[SomeDataClass], description: Sequence[Tuple], values: Row
) -> SomeDataClass: ...


def make_class_from_cursor(
    classtype: type[SomeDataClass],
    description: Sequence[Tuple],
    values: Union[Sequence[Row], Row, None],
) -> Union[SomeDataClass, List[SomeDataClass], None]:
    if values is None:
        return None

    def get_index(name: str):
        index = -1
        for d in description:
            index += 1
            if d[0] == name:
                return index
        return -1

    def get_vl(name: str, type: Any):
        ind = get_index(name)
        if ind == -1:
            return None
        return values[ind]

    if type(values) == tuple or type(values).__name__ == "Row" or type(values).__name__ == "pyodbc.Row":
        if classtype == dict:
            names = [d[0] for d in description]
            return {name: get_vl(name, None) for name in names}  # type: ignore
        elif dataclasses.is_dataclass(classtype):
            prms = {f.name: get_vl(f.name, f.type) for f in dataclasses.fields(classtype)}  # type: ignore
            return classtype(**prms)
        elif hasattr(classtype, "model_validate"):  # Pydantic 2.0
            mod: "Type[pydantic.BaseModel]" = classtype  # type: ignore
            prms = {f: get_vl(f, None) for f in mod.model_fields.keys()}
            return mod.model_validate(prms)  # type: ignore
        else:
            import pydantic

            adapt = pydantic.TypeAdapter(classtype)
            names = [d[0] for d in description]
            dct = {name: get_vl(name, None) for name in names}
            return adapt.validate_python(dct)  # type: ignore
    else:
        return [make_class_from_cursor(classtype, description, item) for item in values]  # type: ignore
