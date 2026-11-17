"""Fake transports and fixture helpers for tests of the OpenAI-compatible client."""

import json
import threading
import time
from collections.abc import Sequence
from pathlib import Path

from utux.providers.openai_compatible import HttpRequest, HttpResponse

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "openai_compatible"

# Not a real key. It is long and unusual so that a leak is easy to find.
SYNTHETIC_KEY = "synthetic-test-key-7f3a9c1e5b2d4086"


def fixture_body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_json(name: str) -> dict[str, object]:
    document = json.loads(fixture_body(name))
    assert isinstance(document, dict)
    return document


def response(
    status: int, body: bytes | str | dict[str, object], headers: dict[str, str] | None = None
) -> HttpResponse:
    if isinstance(body, dict):
        data = json.dumps(body).encode()
    elif isinstance(body, str):
        data = fixture_body(body) if body.endswith(".json") else body.encode()
    else:
        data = body
    return HttpResponse(status=status, headers=headers or {}, body=data)


OK_WITH_COST = response(200, "openrouter_completion_with_cost.json")
OK_WITHOUT_COST = response(200, "openai_completion_without_cost.json")


class ScriptedTransport:
    """Answers each call with the next item of a script, or always with one item.

    An item is a response, or an exception to raise. Safe to call from
    several threads.
    """

    def __init__(
        self,
        script: HttpResponse | BaseException | Sequence[HttpResponse | BaseException],
        *,
        delay_seconds: float = 0.0,
    ) -> None:
        self._repeat = not isinstance(script, Sequence)
        self._items: list[HttpResponse | BaseException] = (
            [script] if not isinstance(script, Sequence) else list(script)
        )
        self._delay = delay_seconds
        self._lock = threading.Lock()
        self.calls: list[tuple[HttpRequest, float]] = []

    def __call__(self, request: HttpRequest, timeout_seconds: float) -> HttpResponse:
        with self._lock:
            self.calls.append((request, timeout_seconds))
            item = self._items[0] if self._repeat else self._items.pop(0)
        if self._delay > timeout_seconds:
            # What a real transport does: give up at the timeout.
            time.sleep(timeout_seconds)
            raise TimeoutError("synthetic: timed out")
        if self._delay:
            time.sleep(self._delay)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeTime:
    """A clock and a sleep that move together, without waiting."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
