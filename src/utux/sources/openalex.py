"""OpenAlex as a `LiteratureSource` (task M2-05, ADR-0017).

OpenAlex answers basic queries without a key, at up to 10 requests a second
per address (rule 7 assessment in pull request #54). utux is keyless by
default. A key is used only when the user sets the environment variable
`OPENALEX_API_KEY`, never `utux.yaml`, and it is sent only as an
`Authorization: Bearer` header, never in a URL (rule 8 of `docs/plan/M2.md`).
With a key, requests may go 30 a second.
It resolves DOIs, PubMed ids and OpenAlex ids:

- `doi:<doi>` as `/works/https://doi.org/<doi>`;
- `pmid:<id>` as `/works/pmid:<id>`;
- `openalex:<W…>` as `/works/<W…>`.

The text it gives is the abstract, rebuilt exactly from OpenAlex's inverted
index (`rebuild_abstract`). OpenAlex gives each author as one display name;
the last word is taken as the family name and the rest as the given name, a
rule that is wrong for some names, such as "van der Berg".

The contact email of `utux.yaml` is never sent to OpenAlex: its current
documentation does not say that it helps.
"""

import json
import os
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote, urlencode

from pydantic import ValidationError

from utux.errors import LiteratureInvalidResponseError, LiteratureNotFoundError
from utux.interfaces.literature_source import FetchedSource, WorkMetadata, check_search
from utux.schemas.claim_ledger import CheckedText
from utux.schemas.source_record import Author, SourceVersion
from utux.sources.http import HttpClient, Transport, urllib_transport

BASE_URL = "https://api.openalex.org/works"
MIN_INTERVAL_SECONDS = 0.1
"""Ten requests a second, the limit for calls without a key."""
MIN_INTERVAL_WITH_KEY_SECONDS = 1 / 30
"""Thirty requests a second, the limit for calls with a free key."""
KEY_ENVIRONMENT = "OPENALEX_API_KEY"


def rebuild_abstract(index: object) -> str | None:
    """The abstract from OpenAlex's inverted index, word by word in position order.

    The index maps each word to the positions where it stands. The positions
    must cover 0 to n - 1 exactly once each; the words are joined by single
    spaces, as OpenAlex has no other record of the spacing.

    Raises:
        LiteratureInvalidResponseError: The index is not a mapping of words
            to lists of positions, or its positions repeat or leave a gap.
    """
    if index is None or index == {}:
        return None
    if not isinstance(index, Mapping):
        raise LiteratureInvalidResponseError("the abstract index is not a mapping")
    words: dict[int, str] = {}
    for word, positions in index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            raise LiteratureInvalidResponseError("the abstract index is not words to positions")
        for position in positions:
            if not isinstance(position, int) or isinstance(position, bool) or position < 0:
                raise LiteratureInvalidResponseError(
                    f"the abstract index has an invalid position: {position!r}"
                )
            if position in words:
                raise LiteratureInvalidResponseError(
                    f"two words stand at position {position} of the abstract index"
                )
            words[position] = word
    if sorted(words) != list(range(len(words))):
        raise LiteratureInvalidResponseError("the abstract index leaves a gap")
    return " ".join(words[position] for position in range(len(words)))


def _author(name: object) -> Author | None:
    if not isinstance(name, str) or not name.strip():
        return None
    parts = name.split()
    given = " ".join(parts[:-1]) or None
    return Author(family=parts[-1], given=given)


def _identifier(work: Mapping[str, Any]) -> str:
    doi = work.get("doi")
    if isinstance(doi, str) and doi:
        return "doi:" + doi.removeprefix("https://doi.org/")
    openalex = str(work.get("id", ""))
    return "openalex:" + openalex.removeprefix("https://openalex.org/")


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _metadata(work: Mapping[str, Any], identifier: str | None = None) -> WorkMetadata:
    location = work.get("primary_location") or {}
    source = location.get("source") or {} if isinstance(location, Mapping) else {}
    authors = [
        _author((entry.get("author") or {}).get("display_name"))
        for entry in work.get("authorships") or []
        if isinstance(entry, Mapping)
    ]
    doi = work.get("doi")
    try:
        return WorkMetadata(
            identifier=identifier or _identifier(work),
            title=_text(work.get("display_name") or work.get("title")),
            authors=tuple(author for author in authors if author is not None),
            year=work.get("publication_year"),
            venue=_text(source.get("display_name")) if isinstance(source, Mapping) else None,
            url=doi if isinstance(doi, str) and doi.startswith("https://") else None,
        )
    except ValidationError as error:
        raise LiteratureInvalidResponseError(
            f"OpenAlex's work is not valid metadata: {error.error_count()} problems"
        ) from error


def _licence(work: Mapping[str, Any]) -> str | None:
    for key in ("best_oa_location", "primary_location"):
        location = work.get(key)
        if isinstance(location, Mapping) and _text(location.get("license")):
            return _text(location.get("license"))
    return None


class OpenAlexSource:
    """A `LiteratureSource` for OpenAlex."""

    def __init__(
        self,
        transport: Transport = urllib_transport,
        *,
        environ: Mapping[str, str] = os.environ,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Reach OpenAlex through `transport`, with the key of `OPENALEX_API_KEY` if set."""
        key = environ.get(KEY_ENVIRONMENT, "").strip()
        self._client = HttpClient(
            transport,
            min_interval_seconds=MIN_INTERVAL_WITH_KEY_SECONDS if key else MIN_INTERVAL_SECONDS,
            accept="application/json",
            headers={"Authorization": f"Bearer {key}"} if key else None,
            sleep=sleep,
            monotonic=monotonic,
        )

    @property
    def name(self) -> str:
        """`openalex`."""
        return "openalex"

    @property
    def is_external(self) -> bool:
        """True: queries go to OpenAlex's servers."""
        return True

    def _url(self, path: str, params: dict[str, str | int] | None = None) -> str:
        query = dict(params or {})
        return BASE_URL + path + ("?" + urlencode(query) if query else "")

    def _get(self, url: str) -> Any:
        body = self._client.get(url)
        try:
            return json.loads(body)
        except ValueError as error:
            raise LiteratureInvalidResponseError("OpenAlex's answer is not JSON") from error

    def _work(self, identifier: str) -> Mapping[str, Any]:
        scheme, _, value = identifier.partition(":")
        paths = {
            "doi": "/" + quote("https://doi.org/" + value, safe=":/"),
            "pmid": "/pmid:" + quote(value, safe=""),
            "openalex": "/" + quote(value, safe=""),
        }
        if scheme not in paths or not value:
            raise LiteratureNotFoundError(
                f"OpenAlex does not resolve {scheme} identifiers such as {identifier}"
            )
        work = self._get(self._url(paths[scheme]))
        if not isinstance(work, Mapping):
            raise LiteratureInvalidResponseError("OpenAlex's work is not an object")
        return work

    def search(self, query: str, limit: int) -> tuple[WorkMetadata, ...]:
        """Works for a query, by OpenAlex's relevance."""
        check_search(query, limit)
        answer = self._get(self._url("", {"search": query, "per-page": limit}))
        results = answer.get("results") if isinstance(answer, Mapping) else None
        if not isinstance(results, list):
            raise LiteratureInvalidResponseError("OpenAlex's search has no list of results")
        return tuple(_metadata(work) for work in results[:limit] if isinstance(work, Mapping))

    def resolve(self, identifier: str) -> WorkMetadata:
        """The work's metadata."""
        return _metadata(self._work(identifier), identifier)

    def fetch(self, identifier: str) -> FetchedSource:
        """The work's metadata and its abstract, rebuilt from the inverted index."""
        work = self._work(identifier)
        text = rebuild_abstract(work.get("abstract_inverted_index"))
        return FetchedSource(
            metadata=_metadata(work, identifier),
            text=text,
            checked_text=None if text is None else CheckedText.ABSTRACT,
            source_version=SourceVersion.INDEX_ABSTRACT,
            licence=_licence(work),
            extraction_method=None if text is None else "openalex_inverted_index",
        )
