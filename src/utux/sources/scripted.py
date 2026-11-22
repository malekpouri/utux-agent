"""A scripted `LiteratureSource` for tests.

It answers from a catalog written by the test and never reaches the
network. Tests of code that calls a literature source use it in place of a
real one.
"""

import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from utux.errors import (
    LiteratureInvalidResponseError,
    LiteratureNotFoundError,
    LiteratureSourceError,
)
from utux.interfaces.literature_source import FetchedSource, WorkMetadata, check_search
from utux.schemas.claim_ledger import CheckedText
from utux.schemas.source_record import SourceVersion

_WORD = re.compile(r"[a-z0-9]+")


def synthetic_work(identifier: str, title: str, *, text: str | None = None) -> FetchedSource:
    """A synthetic work for a catalog, with an abstract when `text` is given."""
    return FetchedSource(
        metadata=WorkMetadata(identifier=identifier, title=title, year=2024),
        text=text,
        checked_text=None if text is None else CheckedText.ABSTRACT,
        source_version=SourceVersion.INDEX_ABSTRACT,
        licence=None,
        extraction_method=None if text is None else "api_structured_text",
    )


@dataclass(frozen=True)
class ScriptedWork:
    """What every call of a scripted source does instead of answering.

    Attributes:
        error: An error to raise, as an upstream failure would.
        payload: A raw upstream answer to validate, as a real source must;
            one that is not a valid result raises
            `LiteratureInvalidResponseError`.
    """

    error: LiteratureSourceError | None = None
    payload: Mapping[str, object] | None = None

    @classmethod
    def failing(cls, error: Exception) -> "ScriptedWork":
        """Every call raises `error`."""
        assert isinstance(error, LiteratureSourceError)
        return cls(error=error)

    @classmethod
    def raw(cls, payload: Mapping[str, object]) -> "ScriptedWork":
        """Every call receives `payload` from upstream."""
        return cls(payload=payload)


class ScriptedLiteratureSource:
    """A `LiteratureSource` that answers from a catalog of works.

    A search finds the works whose title holds every word of the query, in
    catalog order. `calls` counts the calls that reached the catalog.
    """

    def __init__(
        self,
        catalog: Sequence[FetchedSource],
        *,
        every_call: ScriptedWork | None = None,
        name: str = "scripted",
        is_external: bool = False,
    ) -> None:
        """Answer from `catalog`, or do what `every_call` says on every call."""
        self._catalog = {work.metadata.identifier: work for work in catalog}
        self._every_call = every_call
        self._name = name
        self._is_external = is_external
        self._lock = threading.Lock()
        self.calls = 0

    @property
    def name(self) -> str:
        """The source's name in logs."""
        return self._name

    @property
    def is_external(self) -> bool:
        """Whether queries leave the machine; set per instance."""
        return self._is_external

    def _step(self) -> None:
        with self._lock:
            self.calls += 1
        step = self._every_call
        if step is None:
            return
        if step.error is not None:
            raise step.error
        try:
            WorkMetadata.model_validate(step.payload)
        except ValidationError as error:
            raise LiteratureInvalidResponseError(
                f"the synthetic upstream answer is not a valid work: {error.error_count()} problems"
            ) from error

    def _work(self, identifier: str) -> FetchedSource:
        self._step()
        work = self._catalog.get(identifier)
        if work is None:
            raise LiteratureNotFoundError(f"the scripted catalog has no {identifier}")
        return work

    def search(self, query: str, limit: int) -> tuple[WorkMetadata, ...]:
        """The catalog's works whose title holds every word of the query."""
        check_search(query, limit)
        self._step()
        words = set(_WORD.findall(query.lower()))
        found = [
            work.metadata
            for work in self._catalog.values()
            if words <= set(_WORD.findall((work.metadata.title or "").lower()))
        ]
        return tuple(found[:limit])

    def fetch(self, identifier: str) -> FetchedSource:
        """The catalog's work."""
        return self._work(identifier)

    def resolve(self, identifier: str) -> WorkMetadata:
        """The catalog's work's metadata."""
        return self._work(identifier).metadata
