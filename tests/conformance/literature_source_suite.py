"""Conformance suite for `LiteratureSource` (ADR-0017).

Every implementation must pass this suite. To run it against a source,
subclass `LiteratureSourceConformance` in a test module, name the subclass
`Test...`, and implement the `make_...` methods. The suite never reaches the
network: an implementation supplies sources that answer from a catalog or
from recorded synthetic responses.
"""

import inspect
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

import pytest

from utux.errors import (
    LiteratureInvalidResponseError,
    LiteratureNotFoundError,
    LiteratureRateLimitError,
    LiteratureSourceError,
    LiteratureUnavailableError,
)
from utux.interfaces.literature_source import (
    FetchedSource,
    LiteratureSource,
    WorkMetadata,
)

KNOWN = "doi:10.0000/synthetic-known"
"""The identifier of a work every catalog of the suite holds."""

UNKNOWN = "doi:10.0000/synthetic-unknown"
QUERY = "synthetic method comparison"


class Failure(Enum):
    """The upstream failures a source must turn into typed errors."""

    UNAVAILABLE = "unavailable"
    RATE_LIMIT = "rate_limit"
    INVALID_RESPONSE = "invalid_response"


EXPECTED_ERROR: dict[Failure, type[LiteratureSourceError]] = {
    Failure.UNAVAILABLE: LiteratureUnavailableError,
    Failure.RATE_LIMIT: LiteratureRateLimitError,
    Failure.INVALID_RESPONSE: LiteratureInvalidResponseError,
}


class LiteratureSourceConformance(ABC):
    """Tests that every `LiteratureSource` implementation must pass.

    A source that does not resolve DOIs, such as arXiv, sets `known` and
    `unknown` to identifiers of its own scheme.
    """

    known = KNOWN
    unknown = UNKNOWN

    @abstractmethod
    def make_source(self) -> LiteratureSource:
        """A source whose catalog holds the work `known`, with a stored text,
        and at least three works that a search for `QUERY` finds."""

    @abstractmethod
    def make_failing(self, failure: Failure) -> LiteratureSource:
        """A source whose upstream fails in the given way on every call."""

    # Shape of the interface

    def test_is_a_literature_source(self) -> None:
        assert isinstance(self.make_source(), LiteratureSource)

    def test_the_methods_take_their_documented_parameters(self) -> None:
        source = self.make_source()
        assert list(inspect.signature(source.search).parameters) == ["query", "limit"]
        assert list(inspect.signature(source.fetch).parameters) == ["identifier"]
        assert list(inspect.signature(source.resolve).parameters) == ["identifier"]

    def test_name_is_non_empty_text_and_read_only(self) -> None:
        source = self.make_source()
        assert isinstance(source.name, str)
        assert source.name.strip()
        with pytest.raises(AttributeError):
            source.name = "other"  # type: ignore[misc]

    def test_is_external_is_a_boolean_set_per_instance(self) -> None:
        source = self.make_source()
        assert isinstance(source.is_external, bool)
        assert not isinstance(inspect.getattr_static(type(source), "is_external", None), bool)

    # Results

    def test_resolve_gives_the_metadata_of_the_identifier(self) -> None:
        work = self.make_source().resolve(self.known)
        assert isinstance(work, WorkMetadata)
        assert work.identifier == self.known

    def test_fetch_gives_the_metadata_and_the_text(self) -> None:
        fetched = self.make_source().fetch(self.known)
        assert isinstance(fetched, FetchedSource)
        assert fetched.metadata.identifier == self.known
        assert fetched.text is not None
        assert fetched.checked_text is not None

    @pytest.mark.parametrize("limit", [1, 2, 3])
    def test_search_gives_at_most_limit_works(self, limit: int) -> None:
        found = self.make_source().search(QUERY, limit)
        assert isinstance(found, tuple)
        assert 1 <= len(found) <= limit
        assert all(isinstance(work, WorkMetadata) for work in found)

    @pytest.mark.parametrize("limit", [0, -1, 101])
    def test_search_refuses_a_limit_outside_one_to_a_hundred(self, limit: int) -> None:
        with pytest.raises(ValueError, match="limit"):
            self.make_source().search(QUERY, limit)

    def test_search_refuses_an_empty_query(self) -> None:
        with pytest.raises(ValueError, match="query"):
            self.make_source().search("  ", 5)

    # Errors

    @pytest.mark.parametrize("call", ["resolve", "fetch"])
    def test_an_unknown_identifier_is_not_found(self, call: str) -> None:
        with pytest.raises(LiteratureNotFoundError):
            getattr(self.make_source(), call)(self.unknown)

    @pytest.mark.parametrize("failure", list(Failure))
    @pytest.mark.parametrize("call", ["resolve", "fetch", "search"])
    def test_upstream_failures_raise_typed_errors(self, failure: Failure, call: str) -> None:
        source = self.make_failing(failure)
        arguments: tuple[object, ...] = (QUERY, 3) if call == "search" else (self.known,)
        with pytest.raises(EXPECTED_ERROR[failure]):
            getattr(source, call)(*arguments)

    # Threads

    def test_calls_from_several_threads_at_once(self) -> None:
        source = self.make_source()
        with ThreadPoolExecutor(max_workers=8) as pool:
            works = list(pool.map(lambda _: source.resolve(self.known), range(40)))
        assert all(work.identifier == self.known for work in works)
