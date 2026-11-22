"""The `LiteratureSource` interface: search, fetch and resolve scientific works.

The contract is recorded in ADR-0017. A source finds works by a query,
resolves an identifier to its bibliographic metadata, and fetches a work's
text where it may. It knows nothing about claims, projects or the cache:
the core logs every call and keeps results in the shared cache.
"""

from typing import Annotated, Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from utux.schemas.claim_ledger import CheckedText
from utux.schemas.common import Identifier, NonEmptyText
from utux.schemas.source_record import Author, SourceVersion

MAX_SEARCH_LIMIT = 100
"""The most works one search may ask for."""

SourceIdentifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*:\S+$", strict=True)]
"""A work's identifier with its scheme, such as `doi:10.0000/example`,
`arxiv:2101.00001` or `pmid:00000000`."""


class _Value(BaseModel):
    """Base of the result types: no unknown fields, immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkMetadata(_Value):
    """What a source knows about a work: its identifier and bibliographic metadata.

    A field the source does not give is null, or empty for the authors. It
    is never guessed.
    """

    identifier: SourceIdentifier
    title: NonEmptyText | None = None
    authors: tuple[Author, ...] = ()
    year: Annotated[int, Field(ge=1000, le=2999, strict=True)] | None = None
    venue: NonEmptyText | None = None
    url: Annotated[str, Field(pattern=r"^https?://[^\s/]+\S*$", strict=True)] | None = None


class FetchedSource(_Value):
    """A work's metadata and, where the source gives it, its text.

    Attributes:
        metadata: The work.
        text: The text as the source gives it, or null when it gives none.
        checked_text: `abstract` or `full_text`; null exactly when there is
            no text.
        source_version: Which version of the work the text comes from.
        licence: The licence or access terms the source states, or null.
        extraction_method: A code for how the text was obtained, for
            example `api_structured_text`; null exactly when there is no
            text.
    """

    metadata: WorkMetadata
    text: NonEmptyText | None
    checked_text: CheckedText | None
    source_version: SourceVersion
    licence: NonEmptyText | None
    extraction_method: Identifier | None

    @model_validator(mode="after")
    def _text_fields_agree(self) -> Self:
        given = [self.text is None, self.checked_text is None, self.extraction_method is None]
        if len(set(given)) != 1:
            raise ValueError("text, checked_text and extraction_method are all given or all null")
        return self


def check_search(query: str, limit: int) -> None:
    """Refuse a search that no source may run, as every source must.

    Raises:
        ValueError: The query is blank, or the limit is not from 1 to 100.
    """
    if not query.strip():
        raise ValueError("the query is empty")
    if not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise ValueError(f"the limit must be from 1 to {MAX_SEARCH_LIMIT}, not {limit}")


@runtime_checkable
class LiteratureSource(Protocol):
    """Access to one database of scientific works.

    An implementation must pass the conformance suite in
    `tests/conformance/literature_source_suite.py`. Every method blocks until
    it returns or raises, and is safe to call from several threads at once.
    """

    @property
    def name(self) -> str:
        """Short name of the source, used in logs, such as `openalex`. Read-only."""
        ...

    @property
    def is_external(self) -> bool:
        """Whether a query sent to this source leaves the machine. Read-only.

        Set per instance from the source's configuration, as for
        `ModelProvider`; true unless the source can show otherwise.
        """
        ...

    def search(self, query: str, limit: int) -> tuple[WorkMetadata, ...]:
        """Find works for a query, at most `limit`, best first.

        Raises:
            ValueError: A blank query, or a limit not from 1 to 100.
            LiteratureUnavailableError: The source could not be reached.
            LiteratureRateLimitError: A rate limit refused the call.
            LiteratureInvalidResponseError: The answer is not valid.
        """
        ...

    def fetch(self, identifier: str) -> FetchedSource:
        """Fetch a work's metadata and, where the source gives it, its text.

        Raises:
            LiteratureNotFoundError: The source has no such work.
            LiteratureUnavailableError: The source could not be reached.
            LiteratureRateLimitError: A rate limit refused the call.
            LiteratureInvalidResponseError: The answer is not valid.
        """
        ...

    def resolve(self, identifier: str) -> WorkMetadata:
        """Resolve an identifier to the work's bibliographic metadata.

        Raises:
            LiteratureNotFoundError: The source has no such work.
            LiteratureUnavailableError: The source could not be reached.
            LiteratureRateLimitError: A rate limit refused the call.
            LiteratureInvalidResponseError: The answer is not valid.
        """
        ...
