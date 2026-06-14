"""Central registry of cutoff sources.

Adapters register themselves with the ``@register`` decorator. The UI and the
ingestion script use this registry to list sources and iterate over "all" or
just one — adding a body never touches anything but the new adapter file.
"""

from __future__ import annotations

from typing import TypeVar

from cutoffs.source import CutoffSource

_REGISTRY: dict[str, type[CutoffSource]] = {}

T = TypeVar("T", bound=CutoffSource)


def register(cls: type[T]) -> type[T]:
    """Class decorator that adds a ``CutoffSource`` subclass to the registry.

    Keyed by ``cls.meta.name``. Raises on a duplicate name so collisions surface
    immediately rather than silently shadowing.
    """
    if not isinstance(cls, type) or not issubclass(cls, CutoffSource):
        raise TypeError("register expects a CutoffSource subclass")
    name = cls.meta.name
    if name in _REGISTRY and _REGISTRY[name] is not cls:
        raise ValueError(f"duplicate source name: {name!r}")
    _REGISTRY[name] = cls
    return cls


def get_source(name: str) -> CutoffSource:
    """Instantiate and return the registered source with the given name."""
    try:
        cls = _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "<none>"
        raise KeyError(f"unknown source {name!r}; registered: {known}") from None
    return cls()


def source_names() -> list[str]:
    """Return the sorted list of registered source names."""
    return sorted(_REGISTRY)


def all_sources() -> list[CutoffSource]:
    """Instantiate and return every registered source (for 'query all')."""
    return [_REGISTRY[name]() for name in source_names()]


def clear() -> None:
    """Empty the registry. Intended for tests."""
    _REGISTRY.clear()
