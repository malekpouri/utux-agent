"""Crossref as a `LiteratureSource` (task M2-06, ADR-0016, ADR-0017).

Crossref resolves DOIs, `doi:<doi>`, through its REST API. It needs no key.
Its documentation (access and authentication, last updated 2025-10-16)
recommends a contact email, as `mailto`, for its "polite" pool, with higher
limits and contact before any block. So the contact email of `utux.yaml` is
sent to Crossref when it is set (rule 8 of `docs/plan/M2.md`). The limits
kept are those of the same page:

| | Without a contact email | With one |
| --- | --- | --- |
| DOI lookups | 5 a second | 10 a second |
| Queries | 1 a second | 3 a second |

Requests go one at a time, below both concurrency limits.

Authors keep the separate `family` and `given` names Crossref gives; an
organisation's `name` is kept whole as a display name. The text is the
deposited JATS abstract as plain text, without its heading, when it is
present and safe to parse.
"""

import json
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote, urlencode

from pydantic import ValidationError

from utux.errors import LiteratureInvalidResponseError, LiteratureNotFoundError
from utux.interfaces.literature_source import FetchedSource, WorkMetadata, check_search
from utux.schemas.claim_ledger import CheckedText
from utux.schemas.source_record import Author, SourceVersion
from utux.sources.http import HttpClient, Transport, urllib_transport

BASE_URL = "https://api.crossref.org/works"
LOOKUP_INTERVAL_SECONDS = 1 / 5
POLITE_LOOKUP_INTERVAL_SECONDS = 1 / 10
QUERY_INTERVAL_SECONDS = 1.0
POLITE_QUERY_INTERVAL_SECONDS = 1 / 3
_JATS = "http://www.ncbi.nlm.nih.gov/JATS1"


def _text(value: object) -> str | None:
    if isinstance(value, list):
        value = next((item for item in value if isinstance(item, str) and item.strip()), None)
    if not isinstance(value, str):
        return None
    joined = " ".join(value.split())
    return joined or None


def _author(entry: object) -> Author | None:
    if not isinstance(entry, Mapping):
        return None
    family, given, name = (
        _text(entry.get("family")),
        _text(entry.get("given")),
        _text(entry.get("name")),
    )
    if family is not None:
        return Author(family=family, given=given)
    if name is not None:
        return Author(display_name=name)
    return None


def _year(work: Mapping[str, Any]) -> int | None:
    for key in ("issued", "published-print", "published-online", "published"):
        date = work.get(key)
        parts = date.get("date-parts") if isinstance(date, Mapping) else None
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            year = parts[0][0]
            if isinstance(year, int) and not isinstance(year, bool):
                return year
            return None
    return None


def jats_abstract(abstract: object) -> str | None:
    """The plain text of a JATS abstract, or None when absent, unsafe or broken.

    A document type or entity declaration is refused before parsing, so no
    entity is ever expanded. Titles, such as the heading "Abstract", are left
    out; runs of whitespace become one space.
    """
    if not isinstance(abstract, str) or not abstract.strip():
        return None
    upper = abstract.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        return None
    try:
        root = ElementTree.fromstring(f'<abstract xmlns:jats="{_JATS}">{abstract}</abstract>')
    except ElementTree.ParseError:
        return None
    for parent in root.iter():
        for child in list(parent):
            if child.tag in (f"{{{_JATS}}}title", "title"):
                parent.remove(child)
    return " ".join("".join(root.itertext()).split()) or None


def _licence(work: Mapping[str, Any]) -> str | None:
    licences = work.get("license")
    if isinstance(licences, list):
        for licence in licences:
            if isinstance(licence, Mapping) and _text(licence.get("URL")):
                return _text(licence.get("URL"))
    return None


def _metadata(work: Mapping[str, Any], identifier: str | None = None) -> WorkMetadata:
    doi = _text(work.get("DOI"))
    authors = [_author(entry) for entry in work.get("author") or []]
    try:
        return WorkMetadata(
            identifier=identifier or (f"doi:{doi}" if doi else ""),
            title=_text(work.get("title")),
            authors=tuple(author for author in authors if author is not None),
            year=_year(work),
            venue=_text(work.get("container-title")),
            url=f"https://doi.org/{doi}" if doi else None,
        )
    except ValidationError as error:
        raise LiteratureInvalidResponseError(
            f"Crossref's work is not valid metadata: {error.error_count()} problems"
        ) from error


class CrossrefSource:
    """A `LiteratureSource` for Crossref."""

    def __init__(
        self,
        transport: Transport = urllib_transport,
        *,
        contact_email: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Reach Crossref through `transport`; send `contact_email` as `mailto` when set."""
        self._contact_email = contact_email
        polite = contact_email is not None
        self._lookup = POLITE_LOOKUP_INTERVAL_SECONDS if polite else LOOKUP_INTERVAL_SECONDS
        self._query = POLITE_QUERY_INTERVAL_SECONDS if polite else QUERY_INTERVAL_SECONDS
        self._client = HttpClient(
            transport,
            min_interval_seconds=self._lookup,
            accept="application/json",
            sleep=sleep,
            monotonic=monotonic,
        )

    @property
    def name(self) -> str:
        """`crossref`."""
        return "crossref"

    @property
    def is_external(self) -> bool:
        """True: queries go to Crossref's servers."""
        return True

    def _url(self, path: str, params: dict[str, str | int] | None = None) -> str:
        query = dict(params or {})
        if self._contact_email:
            query["mailto"] = self._contact_email
        return BASE_URL + path + ("?" + urlencode(query) if query else "")

    def _message(self, url: str, interval: float) -> Mapping[str, Any]:
        body = self._client.get(url, min_interval_seconds=interval)
        try:
            answer = json.loads(body)
        except ValueError as error:
            raise LiteratureInvalidResponseError("Crossref's answer is not JSON") from error
        message = answer.get("message") if isinstance(answer, Mapping) else None
        if not isinstance(message, Mapping):
            raise LiteratureInvalidResponseError("Crossref's answer has no message")
        return message

    def _work(self, identifier: str) -> Mapping[str, Any]:
        scheme, _, doi = identifier.partition(":")
        if scheme != "doi" or not doi:
            raise LiteratureNotFoundError(
                f"Crossref resolves only doi identifiers, not {scheme} ones such as {identifier}"
            )
        return self._message(self._url("/" + quote(doi, safe="/:;()")), self._lookup)

    def search(self, query: str, limit: int) -> tuple[WorkMetadata, ...]:
        """Works for a query, by Crossref's relevance."""
        check_search(query, limit)
        message = self._message(self._url("", {"query": query, "rows": limit}), self._query)
        items = message.get("items")
        if not isinstance(items, list):
            raise LiteratureInvalidResponseError("Crossref's search has no list of items")
        return tuple(
            _metadata(work)
            for work in items[:limit]
            if isinstance(work, Mapping) and work.get("DOI")
        )

    def resolve(self, identifier: str) -> WorkMetadata:
        """The work's metadata."""
        return _metadata(self._work(identifier), identifier)

    def fetch(self, identifier: str) -> FetchedSource:
        """The work's metadata and its deposited abstract, as plain text."""
        work = self._work(identifier)
        text = jats_abstract(work.get("abstract"))
        return FetchedSource(
            metadata=_metadata(work, identifier),
            text=text,
            checked_text=None if text is None else CheckedText.ABSTRACT,
            source_version=SourceVersion.INDEX_ABSTRACT,
            licence=_licence(work),
            extraction_method=None if text is None else "crossref_jats_abstract",
        )
