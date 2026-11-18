"""Generic plugin registry.

Customization hook: every swappable component (data provider, cost model, fill model,
score block, exit rule, ...) registers under a string key so YAML can select it and
users can add their own implementation without touching core code.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    """Name -> class registry with a decorator for registration."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._items: dict[str, type[T]] = {}

    def register(self, name: str) -> Callable[[type[T]], type[T]]:
        def deco(cls: type[T]) -> type[T]:
            if name in self._items and self._items[name] is not cls:
                raise ValueError(f"{self.kind} '{name}' already registered")
            self._items[name] = cls
            return cls

        return deco

    def get(self, name: str) -> type[T]:
        try:
            return self._items[name]
        except KeyError:
            raise KeyError(
                f"Unknown {self.kind} '{name}'. Registered: {sorted(self._items)}"
            ) from None

    def names(self) -> list[str]:
        return sorted(self._items)
