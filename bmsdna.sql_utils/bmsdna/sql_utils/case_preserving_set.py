from collections.abc import MutableSet


class CasePreservingSet(MutableSet[str]):
    """String set that preserves case but tests for containment by case-folded value

    E.g. 'Foo' in CasePreservingSet(['FOO']) is True. Preserves case of *last*
    inserted variant.

    """

    def __init__(self, *args):
        self._values: dict[str, str] = {}
        if len(args) > 1:
            raise TypeError(f"{type(self).__name__} expected at most 1 argument, got {len(args)}")
        values = args[0] if args else ()

        for v in values:
            self.add(v)

    def __repr__(self):
        return "<{}{} at {:x}>".format(type(self).__name__, tuple(self._values.values()), id(self))

    def __contains__(self, value: str):
        return value.casefold() in self._values

    def __iter__(self):
        return iter(self._values.values())

    def __len__(self):
        return len(self._values)

    def add(self, value: str):
        self._values[value.casefold()] = value

    def discard(self, value: str):
        try:
            del self._values[value.casefold()]
        except KeyError:
            pass
