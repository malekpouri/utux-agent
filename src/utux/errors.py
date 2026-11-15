"""Typed exceptions raised by utux.

Every error raised deliberately by this package derives from `UtuxError`, so
callers can catch the package's failures without catching unrelated ones.
"""


class UtuxError(Exception):
    """Base class for all errors raised by utux."""
