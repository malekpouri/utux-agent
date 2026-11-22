"""arXiv as a `LiteratureSource` (task M2-05, ADR-0017).

The arXiv API answers in Atom XML and asks for at most one request every
three seconds, on one connection at a time (its terms of use; rule 7
assessment in pull request #54); the client keeps to that. It needs no key.
It resolves arXiv ids only, `arxiv:<id>`, and its text is the abstract,
from the entry's `summary`, with runs of whitespace made one space. Authors
are split as for OpenAlex: the last word of a name is the family name.

A feed that holds a document type or an entity declaration is refused
before it is parsed, so that no entity is ever expanded.
"""

import re
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from urllib.parse import urlencode

from pydantic import ValidationError

from utux.errors import LiteratureInvalidResponseError, LiteratureNotFoundError
from utux.interfaces.literature_source import FetchedSource, WorkMetadata, check_search
from utux.schemas.claim_ledger import CheckedText
from utux.schemas.source_record import Author, SourceVersion
from utux.sources.http import HttpClient, Transport, urllib_transport

BASE_URL = "https://export.arxiv.org/api/query"
MIN_INTERVAL_SECONDS = 3.0
"""One request every three seconds (the arXiv API's terms of use)."""

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_WORD = re.compile(r"[A-Za-z0-9]+")
_FIELD_PREFIXES = frozenset({"ti", "au", "abs", "co", "jr", "cat", "rn", "id", "all"})
"""The field prefixes of the arXiv API user manual, section 5.1."""
_OPERATORS = frozenset({"and", "or", "andnot"})
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "for",
        "from",
        "has",
        "have",
        "in",
        "into",
        "is",
        "it",
        "its",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "we",
        "were",
        "with",
        "you",
        "your",
    }
)
"""Common English words left out of the word clause; they stay in the phrase."""
_VERSION = re.compile(r"v[0-9]+$")


def _clean(text: str | None) -> str | None:
    joined = " ".join((text or "").split())
    return joined or None


def _author(name: str | None) -> Author | None:
    parts = (name or "").split()
    if not parts:
        return None
    return Author(family=parts[-1], given=" ".join(parts[:-1]) or None)


class ArxivSource:
    """A `LiteratureSource` for arXiv."""

    def __init__(
        self,
        transport: Transport = urllib_transport,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Reach arXiv through `transport`, three seconds between requests."""
        self._client = HttpClient(
            transport,
            min_interval_seconds=MIN_INTERVAL_SECONDS,
            accept="application/atom+xml",
            sleep=sleep,
            monotonic=monotonic,
        )

    @property
    def name(self) -> str:
        """`arxiv`."""
        return "arxiv"

    @property
    def is_external(self) -> bool:
        """True: queries go to arXiv's servers."""
        return True

    def _entries(self, params: dict[str, str | int]) -> list[ElementTree.Element]:
        body = self._client.get(BASE_URL + "?" + urlencode(params))
        head = body[:4096].upper()
        if b"<!DOCTYPE" in head or b"<!ENTITY" in body.upper():
            raise LiteratureInvalidResponseError(
                "arXiv's answer holds a DOCTYPE or an entity declaration; it is not parsed"
            )
        try:
            feed = ElementTree.fromstring(body)
        except ElementTree.ParseError as error:
            raise LiteratureInvalidResponseError("arXiv's answer is not XML") from error
        if feed.tag != _ATOM + "feed":
            raise LiteratureInvalidResponseError("arXiv's answer is not an Atom feed")
        entries = feed.findall(_ATOM + "entry")
        # arXiv reports an unknown or malformed id as an entry titled "Error".
        return [e for e in entries if _clean(e.findtext(_ATOM + "title")) != "Error"]

    def _metadata(self, entry: ElementTree.Element, identifier: str | None) -> WorkMetadata:
        url = _clean(entry.findtext(_ATOM + "id")) or ""
        arxiv_id = _VERSION.sub("", url.rsplit("/abs/", 1)[-1])
        published = _clean(entry.findtext(_ATOM + "published")) or ""
        authors = [_author(a.findtext(_ATOM + "name")) for a in entry.findall(_ATOM + "author")]
        try:
            return WorkMetadata(
                identifier=identifier or f"arxiv:{arxiv_id}",
                title=_clean(entry.findtext(_ATOM + "title")),
                authors=tuple(a for a in authors if a is not None),
                year=int(published[:4]) if published[:4].isdigit() else None,
                venue=_clean(entry.findtext(_ARXIV + "journal_ref")),
                url=url.replace("http://", "https://", 1) if url.startswith("http") else None,
            )
        except ValidationError as error:
            raise LiteratureInvalidResponseError(
                f"arXiv's entry is not valid metadata: {error.error_count()} problems"
            ) from error

    def _entry(self, identifier: str) -> ElementTree.Element:
        scheme, _, value = identifier.partition(":")
        if scheme != "arxiv" or not value:
            raise LiteratureNotFoundError(
                f"arXiv resolves only arxiv identifiers, not {scheme} ones such as {identifier}"
            )
        entries = self._entries({"id_list": value, "max_results": 1})
        if not entries:
            raise LiteratureNotFoundError(f"arXiv has no work {identifier}")
        return entries[0]

    def search(self, query: str, limit: int) -> tuple[WorkMetadata, ...]:
        """Works for a query, by arXiv's relevance.

        The query is searched as a phrase in the title and in all fields, or
        as all of its content words (arXiv API user manual, section 5.1:
        quotes make a phrase, `OR` and parentheses combine clauses). Words
        are lowercased, so none is read as the operator `AND`, `OR` or
        `ANDNOT`; field prefixes such as `all` and common stop words are left
        out of the word clause, where they would match nothing.
        """
        check_search(query, limit)
        words = [word.lower() for word in _WORD.findall(query)]
        if not words:
            raise ValueError("the query has no word to search for")
        phrase = " ".join(words)
        clauses = [f'ti:"{phrase}"', f'all:"{phrase}"']
        content = [
            word
            for word in dict.fromkeys(words)
            if word not in _STOP_WORDS | _FIELD_PREFIXES | _OPERATORS
        ]
        if content:
            clauses.append("(" + " AND ".join(f"all:{word}" for word in content) + ")")
        params: dict[str, str | int] = {
            "search_query": " OR ".join(clauses),
            "sortBy": "relevance",
            "sortOrder": "descending",
            "start": 0,
            "max_results": limit,
        }
        entries = self._entries(params)
        return tuple(self._metadata(entry, None) for entry in entries[:limit])

    def resolve(self, identifier: str) -> WorkMetadata:
        """The work's metadata."""
        return self._metadata(self._entry(identifier), identifier)

    def fetch(self, identifier: str) -> FetchedSource:
        """The work's metadata and its abstract."""
        entry = self._entry(identifier)
        text = _clean(entry.findtext(_ATOM + "summary"))
        return FetchedSource(
            metadata=self._metadata(entry, identifier),
            text=text,
            checked_text=None if text is None else CheckedText.ABSTRACT,
            source_version=SourceVersion.PREPRINT,
            licence=None,
            extraction_method=None if text is None else "arxiv_api_atom",
        )
