"""M2-04: every literature call writes one `literature_call` event.

The source is the scripted one; everything is synthetic, and no network is used.
"""

from pathlib import Path

import pytest
from utux.sources.calls import LoggedLiteratureSource
from utux.sources.scripted import ScriptedLiteratureSource, ScriptedWork, synthetic_work

from utux.errors import (
    LiteratureInvalidResponseError,
    LiteratureNotFoundError,
    LiteratureRateLimitError,
    LiteratureUnavailableError,
)
from utux.events.log import EventLog
from utux.schemas.common import Stage
from utux.schemas.event import Event, EventStatus, EventType
from utux.sources.cache import ContentCache
from utux.workspace.hashing import hash_bytes

KNOWN = "doi:10.0000/synthetic-known"
CATALOG = [synthetic_work(KNOWN, "A synthetic study", text="We compare A and B.")]


def _log(tmp_path: Path) -> EventLog:
    return EventLog(tmp_path / "events.jsonl")


def _events(tmp_path: Path) -> list[Event]:
    return [e for e in _log(tmp_path) if e.type is EventType.LITERATURE_CALL]


def test_a_resolve_is_logged_with_its_identifier(tmp_path: Path) -> None:
    logged = LoggedLiteratureSource(_log(tmp_path), ScriptedLiteratureSource(CATALOG))
    work = logged.resolve(KNOWN, run_id="e-000004", stage=Stage.EXPERIMENT)
    assert work.identifier == KNOWN
    (event,) = _events(tmp_path)
    assert (event.status, event.status_reason) == (EventStatus.OK, None)
    assert event.data == {
        "source": "scripted",
        "operation": "resolve",
        "identifier": KNOWN,
        "query_hash": None,
        "cache_hit": False,
    }
    assert event.duration_ms is not None
    assert (event.run_id, event.stage) == ("e-000004", Stage.EXPERIMENT)
    assert event.actor == "system:utux"


def test_a_search_is_logged_by_the_hash_of_its_query_only(tmp_path: Path) -> None:
    query = "synthetic study of a private topic"
    logged = LoggedLiteratureSource(_log(tmp_path), ScriptedLiteratureSource(CATALOG))
    logged.search(query, 5)
    (event,) = _events(tmp_path)
    assert event.data["operation"] == "search"
    assert event.data["identifier"] is None
    assert event.data["query_hash"] == hash_bytes(query.encode("utf-8"))
    assert query not in (tmp_path / "events.jsonl").read_text(encoding="utf-8")


def test_a_second_call_is_answered_by_the_cache_and_says_so(tmp_path: Path) -> None:
    source = ScriptedLiteratureSource(CATALOG)
    logged = LoggedLiteratureSource(_log(tmp_path), source, ContentCache(tmp_path / "cache"))
    first = logged.fetch(KNOWN)
    again = logged.fetch(KNOWN)
    assert first == again
    assert source.calls == 1
    assert [e.data["cache_hit"] for e in _events(tmp_path)] == [False, True]
    # Another project's caller finds it in the shared cache too.
    other = LoggedLiteratureSource(
        EventLog(tmp_path / "other.jsonl"), source, ContentCache(tmp_path / "cache")
    )
    assert other.fetch(KNOWN) == first
    assert source.calls == 1


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (LiteratureUnavailableError("synthetic"), "literature_unavailable"),
        (LiteratureRateLimitError("synthetic"), "rate_limited"),
        (LiteratureNotFoundError("synthetic"), "not_found"),
        (LiteratureInvalidResponseError("synthetic"), "invalid_response"),
    ],
)
def test_a_failed_call_is_logged_with_its_reason_and_raised(
    tmp_path: Path, error: Exception, reason: str
) -> None:
    source = ScriptedLiteratureSource(CATALOG, every_call=ScriptedWork.failing(error))
    logged = LoggedLiteratureSource(_log(tmp_path), source, ContentCache(tmp_path / "cache"))
    with pytest.raises(type(error)):
        logged.resolve(KNOWN)
    (event,) = _events(tmp_path)
    assert (event.status, event.status_reason) == (EventStatus.ERROR, reason)
    # A failure is never cached.
    assert ContentCache(tmp_path / "cache").clear() == 0


def test_an_unknown_identifier_is_not_found_and_logged(tmp_path: Path) -> None:
    logged = LoggedLiteratureSource(_log(tmp_path), ScriptedLiteratureSource(CATALOG))
    with pytest.raises(LiteratureNotFoundError):
        logged.resolve("doi:10.0000/none")
    (event,) = _events(tmp_path)
    assert event.status_reason == "not_found"
