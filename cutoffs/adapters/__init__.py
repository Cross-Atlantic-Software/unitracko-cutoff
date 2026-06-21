"""Importing this package registers every built-in adapter.

Adding a new body = add a module here and import it below. Nothing else changes.
"""

from cutoffs.adapters import (  # noqa: F401  (import = register)
    _bulk,
    apeapcet,
    biharpoly,
    gujacpc,
    josaa,
    kcet,
    keam,
    mhtcet,
    ojee,
    statepdf,
    tnea,
    tseamcet,
    uptac,
    wbjee,
)

__all__ = ["_bulk", "apeapcet", "biharpoly", "gujacpc", "josaa", "kcet", "keam",
           "mhtcet", "ojee", "statepdf", "tnea", "tseamcet", "uptac", "wbjee"]
