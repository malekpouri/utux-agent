"""Logged calls to a literature source (task M2-04).

`LoggedLiteratureSource` wraps a `LiteratureSource`. Every call writes one
`literature_call` event: the source, the operation, the identifier or, for a
search, only the hash of the query, the status with its reason, the
duration, and whether the shared cache answered. A result is kept in the
machine-wide cache (`utux.sources.cache`), so that the same call from any
project is answered without the network; a failure is never kept.
"""

import json
import time
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter

from utux.errors import (
    LiteratureInvalidResponseError,
    LiteratureNotFoundError,
    LiteratureRateLimitError,
    LiteratureSourceError,
    LiteratureUnavailableError,
)
from utux.events.log import EventLog
from utux.interfaces.literature_source import FetchedSource, LiteratureSource, WorkMetadata
from utux.schemas.common import Scalar, Stage
from utux.schemas.event import EventStatus, EventType, NewEvent
from utux.sources.cache import ContentCache
from utux.workspace.hashing import hash_bytes

SYSTEM_ACTOR = "system:utux"

STATUS_REASONS: dict[type[LiteratureSourceError], str] = {
    LiteratureUnavailableError: "literature_unavailable",
    LiteratureRateLimitError: "rate_limited",
    LiteratureNotFoundError: "not_found",
    LiteratureInvalidResponseError: "invalid_response",
}
"""The `status_reason` of a failed call, by the error it raised."""

_SEARCH_RESULT = TypeAdapter(tuple[WorkMetadata, ...])
R = TypeVar("R")


def _reason(error: LiteratureSourceError) -> str:
    for kind, reason in STATUS_REASONS.items():
        if isinstance(error, kind):
            return reason
    return "literature_error"


class LoggedLiteratureSource:
    """A literature source whose every call is logged and cached."""

    def __init__(
        self, log: EventLog, source: LiteratureSource, cache: ContentCache | None = None
    ) -> None:
        """Log the calls of `source` to `log`, keeping results in `cache` if given."""
        self._log = log
        self._source = source
        self._cache = cache

    def _call(
        self,
        operation: str,
        asked: str,
        run: Callable[[], R],
        encode: Callable[[R], bytes],
        decode: Callable[[bytes], R],
        *,
        run_id: str | None,
        stage: Stage | None,
        detail: str = "",
    ) -> R:
        search = operation == "search"
        data: dict[str, Scalar] = {
            "source": self._source.name,
            "operation": operation,
            "identifier": None if search else asked,
            "query_hash": hash_bytes(asked.encode("utf-8")) if search else None,
            "cache_hit": False,
        }
        # The cache key holds what changes the answer, such as a search's limit.
        request = f"literature {self._source.name} {operation} {detail}{asked}"
        started = time.monotonic()

        def log(status: EventStatus, reason: str | None) -> None:
            self._log.append(
                NewEvent(
                    actor=SYSTEM_ACTOR,
                    type=EventType.LITERATURE_CALL,
                    status=status,
                    status_reason=reason,
                    run_id=run_id,
                    stage=stage,
                    duration_ms=max(0, round((time.monotonic() - started) * 1000)),
                    data=data,
                )
            )

        if self._cache is not None:
            kept = self._cache.get_response(request)
            if kept is not None:
                data["cache_hit"] = True
                result = decode(kept)
                log(EventStatus.OK, None)
                return result
        try:
            result = run()
        except LiteratureSourceError as error:
            log(EventStatus.ERROR, _reason(error))
            raise
        log(EventStatus.OK, None)
        if self._cache is not None:
            self._cache.put_response(request, encode(result))
        return result

    def search(
        self, query: str, limit: int, *, run_id: str | None = None, stage: Stage | None = None
    ) -> tuple[WorkMetadata, ...]:
        """Search, logged by the hash of the query."""
        return self._call(
            "search",
            query,
            lambda: self._source.search(query, limit),
            _SEARCH_RESULT.dump_json,
            _SEARCH_RESULT.validate_json,
            run_id=run_id,
            stage=stage,
            detail=f"limit={limit} ",
        )

    def fetch(
        self, identifier: str, *, run_id: str | None = None, stage: Stage | None = None
    ) -> FetchedSource:
        """Fetch, logged by the identifier."""
        return self._call(
            "fetch",
            identifier,
            lambda: self._source.fetch(identifier),
            _dump,
            FetchedSource.model_validate_json,
            run_id=run_id,
            stage=stage,
        )

    def resolve(
        self, identifier: str, *, run_id: str | None = None, stage: Stage | None = None
    ) -> WorkMetadata:
        """Resolve, logged by the identifier."""
        return self._call(
            "resolve",
            identifier,
            lambda: self._source.resolve(identifier),
            _dump,
            WorkMetadata.model_validate_json,
            run_id=run_id,
            stage=stage,
        )


def _dump(result: BaseModel) -> bytes:
    return json.dumps(result.model_dump(mode="json"), sort_keys=True).encode("utf-8")
