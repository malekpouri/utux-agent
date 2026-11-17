"""An OpenAI-compatible chat-completions client, on the standard library only.

One client serves every OpenAI-compatible API: OpenRouter, a direct OpenAI
key, and local servers such as Ollama (ADR-0008). It is blocking, honours the
timeout of each request, and retries rate limits and transient failures with
a bounded backoff that never passes that timeout.

`cost_usd` is only what the provider reports in its response. There is no
price table and no estimate (ADR-0007).

The API key is read from an environment variable at each call. It is never
stored, logged or put into an error message.
"""

import http.client
import ipaddress
import json
import math
import os
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import ValidationError

from utux import __version__
from utux.errors import (
    ModelAuthenticationError,
    ModelInvalidResponseError,
    ModelProviderConfigError,
    ModelProviderError,
    ModelRateLimitError,
    ModelRequestRejectedError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from utux.interfaces.model_provider import FinishReason, ModelRequest, ModelResponse, Usage

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_KEY_VARIABLE = "OPENROUTER_API_KEY"

_DEFAULT_MAX_BODY_BYTES = 16 * 1024 * 1024
_READ_BYTES = 64 * 1024
_REASON_CHARACTERS = 300
_REDACTED = "[redacted]"
_STANDARD_FIELDS = frozenset({"model", "messages", "temperature", "max_tokens"})
_FINISH_REASONS = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "content_filter": FinishReason.CONTENT_FILTER,
}


@dataclass(frozen=True)
class HttpRequest:
    """One HTTP POST to send."""

    url: str
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class HttpResponse:
    """The answer to an HTTP request. Header names are compared without case."""

    status: int
    headers: Mapping[str, str]
    body: bytes

    def header(self, name: str) -> str | None:
        """Return a header value, whatever the case of its name."""
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return None


class Transport(Protocol):
    """Sends one HTTP request.

    Raises `TimeoutError` when no complete answer arrives within
    `timeout_seconds`, and `OSError` or `http.client.HTTPException` when the
    server cannot be reached.
    """

    def __call__(self, request: HttpRequest, timeout_seconds: float) -> HttpResponse:
        """Send the request and return the response."""
        ...


class HttpTransport:
    """The real transport, on `http.client`, with the system trust store.

    The timeout covers the whole exchange: before every blocking read the
    socket timeout is set to the time that is left. Name resolution is not
    covered; it is bounded by the system resolver. Proxy settings from the
    environment are not used.
    """

    def __init__(self, *, max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES) -> None:
        """Create the transport.

        Args:
            max_body_bytes: The largest response body accepted.
        """
        self._max_body_bytes = max_body_bytes
        self._context = ssl.create_default_context()

    def __call__(self, request: HttpRequest, timeout_seconds: float) -> HttpResponse:
        """Send the request and return the response."""
        deadline = time.monotonic() + timeout_seconds
        parts = urlsplit(request.url)
        host = parts.hostname or ""
        connection: http.client.HTTPConnection
        if parts.scheme == "https":
            connection = http.client.HTTPSConnection(
                host, parts.port, timeout=timeout_seconds, context=self._context
            )
        else:
            connection = http.client.HTTPConnection(host, parts.port, timeout=timeout_seconds)
        try:
            connection.request("POST", parts.path, body=request.body, headers=dict(request.headers))
            _limit(connection, deadline)
            answer = connection.getresponse()
            chunks: list[bytes] = []
            size = 0
            while True:
                _limit(connection, deadline)
                chunk = answer.read1(_READ_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > self._max_body_bytes:
                    raise ModelInvalidResponseError(
                        f"the response is larger than {self._max_body_bytes} bytes"
                    )
                chunks.append(chunk)
            return HttpResponse(
                status=answer.status,
                headers={key.lower(): value for key, value in answer.getheaders()},
                body=b"".join(chunks),
            )
        finally:
            connection.close()


def _limit(connection: http.client.HTTPConnection, deadline: float) -> None:
    """Give the next blocking read only the time that is left."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("the timeout of the request has passed")
    if connection.sock is not None:
        connection.sock.settimeout(remaining)


class OpenAICompatibleProvider:
    """A `ModelProvider` for any OpenAI-compatible chat-completions API.

    The base URL must use https, except for a loopback host, where http is
    allowed. `is_external` is false for a loopback host and true for every
    other host.
    """

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key_env: str | None,
        extra_body: Mapping[str, object] | None = None,
        transport: Transport | None = None,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        max_backoff_seconds: float = 8.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create the provider. Nothing is sent and no key is read yet.

        Args:
            name: Short name of the provider, used in logs and errors.
            base_url: The API's base URL, for example
                `https://openrouter.ai/api/v1`. Requests go to
                `<base_url>/chat/completions`.
            api_key_env: The environment variable that holds the API key, or
                None for a server that needs no key.
            extra_body: Fields added to every request body, for a provider
                that needs them. They may not replace a standard field.
            transport: Sends the HTTP requests. Tests pass a fake.
            max_attempts: How many times one call is tried in all.
            backoff_seconds: The wait before the first retry; it doubles for
                each further retry.
            max_backoff_seconds: The longest wait between two attempts, unless
                the provider asks for a longer one.
            sleep: Waits between attempts. Tests pass a fake.
            clock: A monotonic clock in seconds. Tests pass a fake.

        Raises:
            ModelProviderConfigError: If the base URL, the name or the extra
                body cannot work.
        """
        if not name.strip():
            raise ModelProviderConfigError("the provider needs a name")
        self._name = name
        self._endpoint, self._host, self._is_external = _parse_base_url(base_url)
        overlap = sorted(_STANDARD_FIELDS & set(extra_body or {}))
        if overlap:
            raise ModelProviderConfigError(
                f"extra body fields may not replace standard fields: {', '.join(overlap)}"
            )
        if max_attempts < 1:
            raise ModelProviderConfigError("max_attempts must be at least 1")
        self._api_key_env = api_key_env
        self._extra_body = dict(extra_body or {})
        self._transport: Transport = transport if transport is not None else HttpTransport()
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._sleep = sleep
        self._clock = clock

    @property
    def name(self) -> str:
        """Short name of the provider."""
        return self._name

    @property
    def is_external(self) -> bool:
        """False for a loopback host, true for every other host."""
        return self._is_external

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Send one chat-completions request and return the answer.

        Raises:
            ModelAuthenticationError: The key is missing or unusable, before
                anything is sent, or the provider refused it.
            ModelRateLimitError: Rate limited on the last attempt.
            ModelTimeoutError: No answer within `request.timeout_seconds`.
            ModelUnavailableError: Unreachable or failing on the last attempt.
            ModelRequestRejectedError: The provider refused the request.
            ModelInvalidResponseError: The answer is not a valid response.
        """
        key = self._read_key()
        http_request = HttpRequest(
            url=self._endpoint, headers=self._headers(key), body=self._body(request)
        )
        deadline = self._clock() + request.timeout_seconds
        attempt = 1
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise ModelTimeoutError(
                    f"{self._name}: no answer within {request.timeout_seconds} seconds"
                )
            try:
                return self._attempt(http_request, remaining, request, key)
            except (ModelRateLimitError, ModelUnavailableError) as error:
                wait = self._wait(attempt, error)
                # Retry only while attempts are left and the wait still fits
                # into the timeout of the request.
                if attempt >= self._max_attempts or wait >= deadline - self._clock():
                    raise
            self._sleep(wait)
            attempt += 1

    def _attempt(
        self, http_request: HttpRequest, remaining: float, request: ModelRequest, key: str | None
    ) -> ModelResponse:
        try:
            answer = self._transport(http_request, remaining)
        except TimeoutError:
            raise ModelTimeoutError(
                f"{self._name}: no answer within {request.timeout_seconds} seconds"
            ) from None
        except (OSError, http.client.HTTPException) as error:
            reason = _scrub(type(error).__name__ + _detail(error), key)
            raise ModelUnavailableError(
                f"{self._name}: cannot reach {self._host}: {reason}"
            ) from None
        if answer.status == 200:
            return self._parse(answer.body, key)
        raise self._status_error(answer, key)

    def _read_key(self) -> str | None:
        if self._api_key_env is None:
            return None
        key = os.environ.get(self._api_key_env, "").strip()
        if not key:
            raise ModelAuthenticationError(f"{self._name}: {self._api_key_env} is not set")
        if any(character.isspace() or ord(character) < 32 for character in key):
            raise ModelAuthenticationError(
                f"{self._name}: {self._api_key_env} does not hold a usable key"
            )
        return key

    def _headers(self, key: str | None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"utux/{__version__}",
        }
        if key is not None:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _body(self, request: ModelRequest) -> bytes:
        body: dict[str, object] = {
            "model": request.model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens
        body.update(self._extra_body)
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def _wait(self, attempt: int, error: ModelProviderError) -> float:
        if isinstance(error, ModelRateLimitError) and error.retry_after_seconds is not None:
            return error.retry_after_seconds
        return float(min(self._max_backoff_seconds, self._backoff_seconds * 2 ** (attempt - 1)))

    def _status_error(self, answer: HttpResponse, key: str | None) -> ModelProviderError:
        status = answer.status
        message = f"{self._name}: HTTP {status}: {_reason(answer.body, key)}"
        if status in (401, 403):
            return ModelAuthenticationError(message)
        if status == 408:
            return ModelTimeoutError(message)
        if status == 429:
            return ModelRateLimitError(message, _retry_after(answer.header("retry-after")))
        if status >= 500:
            return ModelUnavailableError(message)
        if 400 <= status < 500:
            return ModelRequestRejectedError(message)
        return ModelInvalidResponseError(message)

    def _parse(self, body: bytes, key: str | None) -> ModelResponse:
        try:
            document = json.loads(body, parse_constant=_refuse_constant)
        except (ValueError, UnicodeDecodeError):
            raise ModelInvalidResponseError(
                f"{self._name}: the response is not JSON: {_scrub(_text(body), key)}"
            ) from None
        try:
            return _response_from(document)
        except _InvalidResponseError as problem:
            raise ModelInvalidResponseError(f"{self._name}: {problem}") from None


def openrouter(
    *,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    max_attempts: int = 3,
) -> OpenAICompatibleProvider:
    """Return the OpenRouter provider: the client with OpenRouter's base URL.

    The key is read from `OPENROUTER_API_KEY` at each call. Every request
    asks OpenRouter to report the cost of the call in `usage.cost`.
    """
    return OpenAICompatibleProvider(
        name="openrouter",
        base_url=OPENROUTER_BASE_URL,
        api_key_env=OPENROUTER_KEY_VARIABLE,
        extra_body={"usage": {"include": True}},
        transport=transport,
        max_attempts=max_attempts,
        sleep=sleep,
        clock=clock,
    )


class _InvalidResponseError(Exception):
    """A response body that does not have the expected shape."""


def _response_from(document: object) -> ModelResponse:
    if not isinstance(document, dict):
        raise _InvalidResponseError("the response is not a JSON object")
    choices = document.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise _InvalidResponseError("the response has no choice")
    choice = choices[0]
    finish = choice.get("finish_reason")
    if finish not in _FINISH_REASONS:
        raise _InvalidResponseError(f"the finish reason {finish!r} is not supported")
    finish_reason = _FINISH_REASONS[finish]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise _InvalidResponseError("the choice has no message")
    content = message.get("content")
    if content is None and finish_reason is FinishReason.CONTENT_FILTER:
        content = ""
    if not isinstance(content, str):
        raise _InvalidResponseError("the message content is not text")
    usage = document.get("usage")
    if not isinstance(usage, dict):
        raise _InvalidResponseError("the response has no usage")
    try:
        return ModelResponse(
            model=document.get("model"),  # type: ignore[arg-type]
            content=content,
            finish_reason=finish_reason,
            usage=Usage(
                tokens_in=usage.get("prompt_tokens"),  # type: ignore[arg-type]
                tokens_out=usage.get("completion_tokens"),  # type: ignore[arg-type]
            ),
            cost_usd=_cost(usage),
        )
    except ValidationError as error:
        fields = ", ".join(
            ".".join(str(part) for part in item["loc"]) or "response"
            for item in error.errors(include_url=False, include_input=False)
        )
        raise _InvalidResponseError(f"the response has invalid fields: {fields}") from None


def _cost(usage: dict[str, object]) -> float | None:
    """Return the cost the provider reported, or None when it reported none."""
    cost = usage.get("cost")
    if cost is None:
        return None
    if isinstance(cost, bool) or not isinstance(cost, int | float):
        raise _InvalidResponseError("the reported cost is not a number")
    if not math.isfinite(cost) or cost < 0:
        raise _InvalidResponseError("the reported cost is not a number of zero or more")
    return float(cost)


def _parse_base_url(base_url: str) -> tuple[str, str, bool]:
    parts = urlsplit(base_url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        raise ModelProviderConfigError("the base URL must be an http or https URL with a host")
    if parts.username is not None or parts.password is not None:
        raise ModelProviderConfigError("the base URL must not hold a user name or password")
    if parts.query or parts.fragment:
        raise ModelProviderConfigError("the base URL must not have a query or a fragment")
    local = _is_loopback(host)
    if parts.scheme == "http" and not local:
        # A key would travel in clear text to another machine.
        raise ModelProviderConfigError("the base URL must use https unless the host is loopback")
    try:
        parts.port  # noqa: B018 - raises for a port that is not a number
    except ValueError as error:
        raise ModelProviderConfigError("the base URL has an invalid port") from error
    return base_url.rstrip("/") + "/chat/completions", host, not local


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _retry_after(value: str | None) -> float | None:
    """Return a Retry-After header given in seconds; an HTTP date is ignored."""
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _reason(body: bytes, key: str | None) -> str:
    """Return the provider's reason for an error, without the key."""
    try:
        document = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return _scrub(_text(body), key)
    if isinstance(document, dict):
        error = document.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return _scrub(error["message"], key)
    return _scrub(_text(body), key)


def _text(body: bytes) -> str:
    text = " ".join(body.decode("utf-8", errors="replace").split())
    return text if len(text) <= _REASON_CHARACTERS else text[:_REASON_CHARACTERS] + "..."


def _scrub(text: str, key: str | None) -> str:
    text = text if len(text) <= _REASON_CHARACTERS else text[:_REASON_CHARACTERS] + "..."
    return text.replace(key, _REDACTED) if key else text


def _detail(error: BaseException) -> str:
    detail = getattr(error, "strerror", None) or str(error)
    return f": {detail}" if detail else ""


def _refuse_constant(name: str) -> float:
    raise ValueError(f"{name} is not JSON")
