"""Importing this package registers every built-in adapter.

Adding a new body = add a module here and import it below. Nothing else changes.
"""

from cutoffs.adapters import (  # noqa: F401  (import = register)
    biharpoly,
    josaa,
    kcet,
    keam,
    mhtcet,
    statepdf,
    wbjee,
)

__all__ = ["biharpoly", "josaa", "kcet", "keam", "mhtcet", "statepdf", "wbjee"]
