"""M0-01: `utux.errors` provides the base exception class."""

import pytest

from utux.errors import UtuxError


def test_base_error_is_an_exception() -> None:
    assert issubclass(UtuxError, Exception)


def test_base_error_carries_its_message() -> None:
    with pytest.raises(UtuxError, match="something failed"):
        raise UtuxError("something failed")
