"""HTTP for literature sources, on the standard library (task M2-05).

A source sends GET requests through a `Transport`: `urllib_transport` in
use, `RecordedTransport` in tests, which answers from recorded synthetic
responses so that no test reaches the network (rule 6 of `docs/plan/M2.md`).

`HttpClient` adds what every source needs:

- a user agent that names utux and its version;
- at most one request at a time, and a minimum interval between requests;
- bounded retries of `429` and `5xx` answers and of network failures,
  waiting for `Retry-After` when given, capped at `MAX_WAIT_SECONDS`;
- a limit on the size of an answer;
- typed errors: `404` is not found, a `429` that persists is rate limited,
  a `5xx` or network failure that persists is unavailable, and any other
  answer is invalid.

It sends no credentials of its own and never a key in a URL. A source may
give it extra headers, such as OpenAlex's optional bearer key; they are
sent with every request of that source and appear in no error message.
"""

import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from utux import __version__
from utux.errors import (
    LiteratureInvalidResponseError,
    LiteratureNotFoundError,
    LiteratureRateLimitError,
    LiteratureUnavailableError,
)

USER_AGENT = f"utux/{__version__} (+https://github.com/malekpouri/utux-agent)"


@dataclass(frozen=True)
class HttpRequest:
    """A GET request."""

    url: str
    headers: Mapping[str, str]
    timeout_seconds: float


@dataclass(frozen=True)
class HttpResponse:
    """An answer: its status, body and headers."""

    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


Transport = Callable[[HttpRequest], HttpResponse]


def urllib_transport(request: HttpRequest) -> HttpResponse:
    """Send a request with `urllib`; an HTTP error status is an answer, not a failure.

    Raises:
        OSError: The network failed, including a timeout.
    """
    prepared = urllib.request.Request(request.url, headers=dict(request.headers), method="GET")
    try:
        with urllib.request.urlopen(prepared, timeout=request.timeout_seconds) as answer:
            body = answer.read(HttpClient.MAX_BYTES + 1)
            return HttpResponse(answer.status, body, dict(answer.headers.items()))
    except urllib.error.HTTPError as error:
        body = error.read(HttpClient.MAX_BYTES + 1) if error.fp is not None else b""
        return HttpResponse(error.code, body, dict(error.headers.items()))


class RecordedTransport:
    """A transport that answers from recorded responses, by exact URL, for tests.

    A URL may have one response, or a list that is answered in turn, the
    last one again once the list is used up. An unknown URL gets `default`.
    Every request is kept in `requests`.
    """

    def __init__(
        self,
        responses: Mapping[str, HttpResponse | Sequence[HttpResponse]],
        *,
        default: HttpResponse | None = None,
    ) -> None:
        """Answer from `responses`; an unknown URL gets `default`, or 404."""
        self._responses = {
            url: [answer] if isinstance(answer, HttpResponse) else list(answer)
            for url, answer in responses.items()
        }
        self.default = default if default is not None else HttpResponse(404, b"")
        self.requests: list[HttpRequest] = []
        self._lock = threading.Lock()

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Answer one request."""
        with self._lock:
            self.requests.append(request)
            queue = self._responses.get(request.url)
            if not queue:
                return self.default
            return queue.pop(0) if len(queue) > 1 else queue[0]


class HttpClient:
    """GET with spacing, bounded retries, a size limit and typed errors."""

    MAX_ATTEMPTS = 3
    MAX_WAIT_SECONDS = 60.0
    MAX_BYTES = 10_000_000
    TIMEOUT_SECONDS = 30.0

    def __init__(
        self,
        transport: Transport,
        *,
        min_interval_seconds: float,
        accept: str,
        headers: Mapping[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Send through `transport`, at least `min_interval_seconds` apart."""
        self._transport = transport
        self._interval = min_interval_seconds
        self._accept = accept
        # Extra headers, such as a source's optional key; never logged or put in errors.
        self._headers = dict(headers or {})
        self._sleep = sleep
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._last: float | None = None

    def _wait_turn(self, interval: float) -> None:
        if self._last is not None:
            wait = self._last + interval - self._monotonic()
            if wait > 0:
                self._sleep(wait)
        self._last = self._monotonic()

    def _retry_wait(self, response: HttpResponse | None, attempt: int) -> float:
        given = None if response is None else _header(response, "Retry-After")
        if given is not None and given.strip().isdigit():
            wait = float(given.strip())
        else:
            wait = float(2**attempt)
        return min(wait, self.MAX_WAIT_SECONDS)

    def get(self, url: str, *, min_interval_seconds: float | None = None) -> bytes:
        """The body of a successful answer to a GET of `url`.

        `min_interval_seconds`, when given, replaces the client's interval
        before this request, for a service whose limits differ by kind of
        request.

        Raises:
            LiteratureNotFoundError: The answer was `404`.
            LiteratureRateLimitError: `429` on every attempt.
            LiteratureUnavailableError: `5xx` or a network failure on every
                attempt.
            LiteratureInvalidResponseError: Any other status, or an answer
                larger than `MAX_BYTES`.
        """
        request = HttpRequest(
            url,
            {"User-Agent": USER_AGENT, "Accept": self._accept, **self._headers},
            self.TIMEOUT_SECONDS,
        )
        with self._lock:
            for attempt in range(self.MAX_ATTEMPTS):
                self._wait_turn(
                    self._interval if min_interval_seconds is None else min_interval_seconds
                )
                try:
                    response: HttpResponse | None = self._transport(request)
                except OSError as error:
                    response = None
                    failure = f"the network failed: {error.__class__.__name__}"
                if response is not None:
                    if response.status == 200:
                        if len(response.body) > self.MAX_BYTES:
                            raise LiteratureInvalidResponseError(
                                f"the answer is too large: more than {self.MAX_BYTES} bytes"
                            )
                        return response.body
                    if response.status == 404:
                        raise LiteratureNotFoundError("the source has no such work (404)")
                    if response.status != 429 and response.status < 500:
                        raise LiteratureInvalidResponseError(
                            f"the source answered with status {response.status}"
                        )
                    failure = f"status {response.status}"
                if attempt + 1 < self.MAX_ATTEMPTS:
                    self._sleep(self._retry_wait(response, attempt))
                    # The wait counts as the interval before the next request.
                    self._last = self._monotonic()
            if response is not None and response.status == 429:
                raise LiteratureRateLimitError(
                    f"the source refused {self.MAX_ATTEMPTS} attempts with a rate limit (429)"
                )
            raise LiteratureUnavailableError(
                f"the source failed {self.MAX_ATTEMPTS} attempts, the last with {failure}"
            )


def _header(response: HttpResponse, name: str) -> str | None:
    for key, value in response.headers.items():
        if key.lower() == name.lower():
            return value
    return None
