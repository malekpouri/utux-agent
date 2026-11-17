"""M0-10: the HTTP transport of the OpenAI-compatible client, against a loopback server.

The server runs on 127.0.0.1 inside the test; nothing leaves the machine.
Every response it gives is synthetic.
"""

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from provider_fakes import SYNTHETIC_KEY, fixture_body

from utux.errors import ModelInvalidResponseError, ModelTimeoutError, ModelUnavailableError
from utux.interfaces.model_provider import Message, MessageRole, ModelRequest
from utux.providers.openai_compatible import HttpTransport, OpenAICompatibleProvider

SEEN: list[dict[str, Any]] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Keep the test output quiet."""

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        SEEN.append({"path": self.path, "headers": dict(self.headers), "body": body})
        behaviour = body["model"]
        if behaviour == "synthetic/slow":
            time.sleep(3)
        if behaviour == "synthetic/drip":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            for _ in range(30):
                self.wfile.write(b" ")
                self.wfile.flush()
                time.sleep(0.1)
            return
        payload = fixture_body("openai_completion_without_cost.json")
        if behaviour == "synthetic/big":
            payload = b" " * (2 * 1024 * 1024) + payload
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def server() -> Iterator[str]:
    SEEN.clear()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _request(model: str = "synthetic-local-model", timeout: float = 5.0) -> ModelRequest:
    return ModelRequest(
        model=model,
        messages=(Message(role=MessageRole.USER, content="Synthetic user text."),),
        timeout_seconds=timeout,
    )


def _local(base_url: str, **options: Any) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(name="local", base_url=base_url, api_key_env=None, **options)


def test_real_transport_talks_to_an_openai_compatible_server(server: str) -> None:
    provider = _local(server)
    assert provider.is_external is False
    answer = provider.complete(_request())
    assert answer.content == "Synthetic local reply."
    assert answer.cost_usd is None
    (seen,) = SEEN
    assert seen["path"] == "/v1/chat/completions"
    assert seen["body"]["messages"] == [{"role": "user", "content": "Synthetic user text."}]
    assert "Authorization" not in seen["headers"]


def test_key_is_sent_as_a_header_to_a_server_that_needs_one(
    server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNTHETIC_LOCAL_KEY", SYNTHETIC_KEY)
    provider = OpenAICompatibleProvider(
        name="local", base_url=server, api_key_env="SYNTHETIC_LOCAL_KEY"
    )
    provider.complete(_request())
    assert SEEN[0]["headers"]["Authorization"] == f"Bearer {SYNTHETIC_KEY}"


def test_timeout_is_honoured_when_the_server_does_not_answer(server: str) -> None:
    started = time.monotonic()
    with pytest.raises(ModelTimeoutError):
        _local(server).complete(_request("synthetic/slow", timeout=0.3))
    assert time.monotonic() - started < 2.0


def test_timeout_is_honoured_when_the_body_arrives_too_slowly(server: str) -> None:
    started = time.monotonic()
    with pytest.raises(ModelTimeoutError):
        _local(server).complete(_request("synthetic/drip", timeout=0.5))
    assert time.monotonic() - started < 2.0


def test_body_larger_than_the_limit_is_refused(server: str) -> None:
    provider = _local(server, transport=HttpTransport(max_body_bytes=1024 * 1024))
    with pytest.raises(ModelInvalidResponseError, match="larger"):
        provider.complete(_request("synthetic/big"))


def test_nothing_listening_is_unavailable() -> None:
    # A port on the loopback interface that nothing listens on.
    provider = _local("http://127.0.0.1:9/v1", sleep=lambda _: None)
    with pytest.raises(ModelUnavailableError, match="127.0.0.1"):
        provider.complete(_request(timeout=2.0))
