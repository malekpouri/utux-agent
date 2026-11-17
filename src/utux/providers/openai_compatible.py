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

import base64
import http.client
import ipaddress
import json
import math
import os
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import unquote, urlsplit

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


@dataclass(frozen=True)
class _Proxy:
    host: str
    port: int
    # Kept out of repr, so that it never reaches a log or an error.
    authorization: str | None = field(repr=False)

    @property
    def label(self) -> str:
        return f"{self.host}:{self.port}"


class HttpTransport:
    """The real transport, on `http.client`, with the system trust store.

    The timeout covers the whole exchange: before every blocking read the
    socket timeout is set to the time that is left. Name resolution is not
    covered; it is bounded by the system resolver.

    https requests go through the proxy in `https_proxy` or `HTTPS_PROXY`,
    through an HTTP CONNECT tunnel, unless `no_proxy` or `NO_PROXY` names the
    host. A loopback host never uses a proxy. Only `http://` proxies are
    supported; SOCKS proxies are not. The proxy settings are read when the
    transport is created.
    """

    def __init__(
        self,
        *,
        max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES,
        ssl_context: ssl.SSLContext | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        """Create the transport.

        Args:
            max_body_bytes: The largest response body accepted.
            ssl_context: The TLS settings. By default, the system trust store.
            environ: Where the proxy settings are read. By default, the
                environment of the process.

        Raises:
            ModelProviderConfigError: If the proxy setting cannot be used. The
                message never holds the proxy's credentials.
        """
        self._max_body_bytes = max_body_bytes
        self._context = ssl_context if ssl_context is not None else ssl.create_default_context()
        settings = os.environ if environ is None else environ
        self._proxy = _proxy_from(settings)
        self._no_proxy = (settings.get("no_proxy") or settings.get("NO_PROXY") or "").strip()

    def proxy_for(self, url: str) -> str | None:
        """Return the proxy, as `host:port`, that a request to `url` goes through."""
        proxy = self._route(url)
        return None if proxy is None else proxy.label

    def _route(self, url: str) -> _Proxy | None:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if self._proxy is None or parts.scheme != "https" or _is_loopback(host):
            return None
        if _bypasses(host, parts.port or 443, self._no_proxy):
            return None
        return self._proxy

    def __call__(self, request: HttpRequest, timeout_seconds: float) -> HttpResponse:
        """Send the request and return the response."""
        deadline = time.monotonic() + timeout_seconds
        parts = urlsplit(request.url)
        host = parts.hostname or ""
        proxy = self._route(request.url)
        connection: http.client.HTTPConnection
        if proxy is not None:
            connection = http.client.HTTPSConnection(
                proxy.host, proxy.port, timeout=timeout_seconds, context=self._context
            )
            headers = (
                {} if proxy.authorization is None else {"Proxy-Authorization": proxy.authorization}
            )
            connection.set_tunnel(host, parts.port or 443, headers=headers)
        elif parts.scheme == "https":
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


def _proxy_from(settings: Mapping[str, str]) -> _Proxy | None:
    """Read the https proxy from the environment, as curl and urllib do."""
    variable = "https_proxy" if settings.get("https_proxy") else "HTTPS_PROXY"
    value = (settings.get(variable) or "").strip()
    if not value:
        return None
    if "://" not in value:
        value = "http://" + value
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    # Messages name the variable and the scheme only, never the URL, which
    # may hold credentials.
    if scheme.startswith("socks"):
        raise ModelProviderConfigError(f"{variable}: SOCKS proxies are not supported")
    if scheme != "http":
        raise ModelProviderConfigError(
            f"{variable}: only http:// proxies are supported, not {scheme}://"
        )
    if not parts.hostname:
        raise ModelProviderConfigError(f"{variable}: the proxy URL has no host")
    try:
        port = parts.port or 80
    except ValueError:
        raise ModelProviderConfigError(f"{variable}: the proxy URL has an invalid port") from None
    authorization = None
    if parts.username is not None:
        credentials = f"{unquote(parts.username)}:{unquote(parts.password or '')}"
        authorization = "Basic " + base64.b64encode(credentials.encode()).decode("ascii")
    return _Proxy(parts.hostname, port, authorization)


def _bypasses(host: str, port: int, no_proxy: str) -> bool:
    """Return whether `no_proxy` exempts a host from the proxy.

    The value is a comma-separated list. `*` exempts every host. An entry
    exempts a host equal to it or ending in `.` and the entry; a leading dot
    is ignored. An entry with `:port` exempts only that port. Addresses are
    compared as text; address ranges are not supported.
    """
    for raw in no_proxy.split(","):
        entry = raw.strip().lower()
        if not entry:
            continue
        if entry == "*":
            return True
        name, _, entry_port = entry.rpartition(":") if _has_port(entry) else (entry, "", "")
        if entry_port and entry_port != str(port):
            continue
        name = name.lstrip(".").strip("[]")
        if name and (host == name or host.endswith("." + name)):
            return True
    return False


def _has_port(entry: str) -> bool:
    if entry.startswith("["):
        return "]:" in entry
    return entry.count(":") == 1


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
            except _FinalError as final:
                # Retrying cannot change the outcome.
                raise final.error from None
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
        except ssl.SSLCertVerificationError as error:
            reason = _scrub(getattr(error, "verify_message", None) or str(error), key)
            raise _FinalError(
                ModelUnavailableError(
                    f"{self._name}: the system trust store could not verify {self._host}: {reason}"
                )
            ) from None
        except (OSError, http.client.HTTPException) as error:
            reason = _scrub(type(error).__name__ + _detail(error), key)
            raise ModelUnavailableError(
                f"{self._name}: cannot reach {self._host}: {reason}"
            ) from None
        if answer.status == 200:
            return self._parse(answer, key)
        raise self._status_error(
            answer.status,
            answer.header("retry-after"),
            f"{self._name}: HTTP {answer.status}: {_reason(answer.body, key)}",
        )

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

    def _status_error(
        self, status: int, retry_after: str | None, message: str
    ) -> ModelProviderError:
        if status in (401, 403):
            return ModelAuthenticationError(message)
        if status == 408:
            return ModelTimeoutError(message)
        if status == 429:
            return ModelRateLimitError(message, _retry_after(retry_after))
        if status >= 500:
            return ModelUnavailableError(message)
        if 400 <= status < 500:
            return ModelRequestRejectedError(message)
        return ModelInvalidResponseError(message)

    def _parse(self, answer: HttpResponse, key: str | None) -> ModelResponse:
        body = answer.body
        try:
            document = json.loads(body, parse_constant=_refuse_constant)
        except (ValueError, UnicodeDecodeError):
            raise ModelInvalidResponseError(
                f"{self._name}: the response is not JSON: {_scrub(_text(body), key)}"
            ) from None
        if isinstance(document, dict) and isinstance(document.get("error"), dict):
            # Some providers report a failure in a 200 response; it is mapped
            # by its code, like an HTTP status.
            code = document["error"].get("code")
            reason = _reason(body, key)
            if isinstance(code, int) and not isinstance(code, bool) and 400 <= code <= 599:
                raise self._status_error(
                    code,
                    answer.header("retry-after"),
                    f"{self._name}: error {code} in a 200 response: {reason}",
                )
            raise ModelInvalidResponseError(
                f"{self._name}: the response holds an error without a usable code: {reason}"
            )
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


class _FinalError(Exception):
    """Carries an error that is not retried, whatever its type."""

    def __init__(self, error: ModelProviderError) -> None:
        super().__init__(str(error))
        self.error = error


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
    return " ".join(body.decode("utf-8", errors="replace").split())


def _scrub(text: str, key: str | None) -> str:
    """Remove the key from a text, then cut it to length.

    In this order, so that a cut cannot leave a part of the key behind.
    """
    if key:
        text = text.replace(key, _REDACTED)
    return text if len(text) <= _REASON_CHARACTERS else text[:_REASON_CHARACTERS] + "..."


def _detail(error: BaseException) -> str:
    detail = getattr(error, "strerror", None) or str(error)
    return f": {detail}" if detail else ""


def _refuse_constant(name: str) -> float:
    raise ValueError(f"{name} is not JSON")
