"""M0-10: proxies, certificates and the system trust store.

The proxy, the TLS server and the certificate are synthetic and run on
127.0.0.1 inside the test. Nothing leaves the machine.
"""

import base64
import ssl
import time
from pathlib import Path
from typing import Any

import pytest
from provider_fakes import FakeTime, ScriptedTransport
from tls_fakes import SYNTHETIC_HOST, make_certificate, proxy_server, tls_server

from utux.errors import ModelProviderConfigError, ModelUnavailableError
from utux.interfaces.model_provider import Message, MessageRole, ModelRequest
from utux.providers.openai_compatible import (
    HttpRequest,
    HttpResponse,
    HttpTransport,
    OpenAICompatibleProvider,
    openrouter,
)

PROXY_USER = "synthetic-user"
PROXY_PASSWORD = "s3cret-proxy-pass"


def _request(timeout: float = 5.0) -> ModelRequest:
    return ModelRequest(
        model="synthetic-local-model",
        messages=(Message(role=MessageRole.USER, content="Synthetic user text."),),
        timeout_seconds=timeout,
    )


def _provider(base_url: str, transport: Any, **options: Any) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="synthetic", base_url=base_url, api_key_env=None, transport=transport, **options
    )


# Which requests go through the proxy


@pytest.mark.parametrize(
    ("environ", "url", "expected"),
    [
        ({}, "https://openrouter.ai/api/v1/chat/completions", None),
        (
            {"HTTPS_PROXY": "http://proxy.example:3128"},
            "https://openrouter.ai/x",
            "proxy.example:3128",
        ),
        (
            {"https_proxy": "http://lower.example:8080"},
            "https://openrouter.ai/x",
            "lower.example:8080",
        ),
        # The lower-case variable wins, as in curl and urllib.
        (
            {"https_proxy": "http://lower.example:8080", "HTTPS_PROXY": "http://upper.example:1"},
            "https://openrouter.ai/x",
            "lower.example:8080",
        ),
        ({"HTTPS_PROXY": "http://proxy.example"}, "https://openrouter.ai/x", "proxy.example:80"),
        ({"HTTPS_PROXY": "proxy.example:3128"}, "https://openrouter.ai/x", "proxy.example:3128"),
        # Only https targets use the proxy; HTTP_PROXY is not read.
        ({"HTTP_PROXY": "http://proxy.example:3128"}, "https://openrouter.ai/x", None),
        # Loopback targets never use a proxy.
        ({"HTTPS_PROXY": "http://proxy.example:3128"}, "https://localhost:8443/x", None),
        ({"HTTPS_PROXY": "http://proxy.example:3128"}, "https://127.0.0.1:8443/x", None),
        ({"HTTPS_PROXY": "http://proxy.example:3128"}, "https://[::1]:8443/x", None),
        ({"HTTPS_PROXY": "http://proxy.example:3128"}, "http://localhost:11434/x", None),
        # NO_PROXY
        (
            {"HTTPS_PROXY": "http://proxy.example:3128", "NO_PROXY": "openrouter.ai"},
            "https://openrouter.ai/x",
            None,
        ),
        (
            {"HTTPS_PROXY": "http://proxy.example:3128", "no_proxy": ".openrouter.ai"},
            "https://api.openrouter.ai/x",
            None,
        ),
        (
            {"HTTPS_PROXY": "http://proxy.example:3128", "NO_PROXY": "*"},
            "https://openrouter.ai/x",
            None,
        ),
        (
            {"HTTPS_PROXY": "http://proxy.example:3128", "NO_PROXY": "other.org, example.net"},
            "https://openrouter.ai/x",
            "proxy.example:3128",
        ),
        (
            {"HTTPS_PROXY": "http://proxy.example:3128", "NO_PROXY": "router.ai"},
            "https://openrouter.ai/x",
            "proxy.example:3128",
        ),
        (
            {"HTTPS_PROXY": "http://proxy.example:3128", "NO_PROXY": "OpenRouter.AI:443"},
            "https://openrouter.ai/x",
            None,
        ),
        (
            {"HTTPS_PROXY": "http://proxy.example:3128", "NO_PROXY": "openrouter.ai:8443"},
            "https://openrouter.ai/x",
            "proxy.example:3128",
        ),
        (
            {"HTTPS_PROXY": "http://proxy.example:3128", "NO_PROXY": "10.0.0.5"},
            "https://10.0.0.5:8443/x",
            None,
        ),
    ],
)
def test_proxy_routing(environ: dict[str, str], url: str, expected: str | None) -> None:
    assert HttpTransport(environ=environ).proxy_for(url) == expected


def test_default_transport_reads_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    assert HttpTransport().proxy_for("https://openrouter.ai/x") == "proxy.example:3128"


@pytest.mark.parametrize(
    ("proxy", "says"),
    [
        (
            f"socks5://{PROXY_USER}:{PROXY_PASSWORD}@proxy.example:1080",
            "SOCKS proxies are not supported",
        ),
        ("socks5h://proxy.example:1080", "SOCKS proxies are not supported"),
        (f"https://{PROXY_USER}:{PROXY_PASSWORD}@proxy.example:3128", "only http:// proxies"),
        ("http://", "no host"),
    ],
)
def test_unsupported_proxy_is_a_configuration_error_without_credentials(
    proxy: str, says: str
) -> None:
    with pytest.raises(ModelProviderConfigError) as caught:
        HttpTransport(environ={"HTTPS_PROXY": proxy})
    assert says in str(caught.value)
    assert PROXY_PASSWORD not in str(caught.value)
    assert PROXY_USER not in str(caught.value)


def test_provider_reports_a_bad_proxy_when_it_is_created(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "socks5://proxy.example:1080")
    with pytest.raises(ModelProviderConfigError, match="SOCKS"):
        openrouter()


def test_proxy_label_holds_no_credentials() -> None:
    transport = HttpTransport(
        environ={"HTTPS_PROXY": f"http://{PROXY_USER}:{PROXY_PASSWORD}@proxy.example:3128"}
    )
    assert transport.proxy_for("https://openrouter.ai/x") == "proxy.example:3128"
    assert PROXY_PASSWORD not in repr(transport)


# Through a loopback proxy


def test_request_goes_through_a_connect_tunnel_with_proxy_credentials(tmp_path: Path) -> None:
    certificate = make_certificate(tmp_path, SYNTHETIC_HOST)
    with tls_server(certificate) as (tls_port, seen), proxy_server(tls_port) as proxy:
        transport = HttpTransport(
            environ={"HTTPS_PROXY": f"http://{PROXY_USER}:{PROXY_PASSWORD}@127.0.0.1:{proxy.port}"},
            ssl_context=certificate.client_context(),
        )
        provider = _provider(f"https://{SYNTHETIC_HOST}/v1", transport)
        answer = provider.complete(_request())
    assert answer.content == "Synthetic local reply."
    (head,) = proxy.requests
    lines = head.split("\r\n")
    assert lines[0] == f"CONNECT {SYNTHETIC_HOST}:443 HTTP/1.1"
    token = base64.b64encode(f"{PROXY_USER}:{PROXY_PASSWORD}".encode()).decode()
    assert f"Proxy-Authorization: Basic {token}" in lines
    # The proxy saw only the tunnel; the request itself went inside it.
    assert "chat/completions" not in head
    assert seen == ["/v1/chat/completions"]


def test_refused_tunnel_is_unavailable_and_the_error_holds_no_credentials(tmp_path: Path) -> None:
    with proxy_server(None) as proxy:
        transport = HttpTransport(
            environ={"HTTPS_PROXY": f"http://{PROXY_USER}:{PROXY_PASSWORD}@127.0.0.1:{proxy.port}"}
        )
        provider = _provider(f"https://{SYNTHETIC_HOST}/v1", transport, sleep=lambda _: None)
        with pytest.raises(ModelUnavailableError) as caught:
            provider.complete(_request())
    text = str(caught.value) + repr(caught.value)
    assert "407" in text
    assert PROXY_PASSWORD not in text
    assert PROXY_USER not in text


def test_loopback_target_bypasses_a_configured_proxy(tmp_path: Path) -> None:
    certificate = make_certificate(tmp_path, "localhost")
    with tls_server(certificate) as (tls_port, seen), proxy_server(None) as proxy:
        transport = HttpTransport(
            environ={"HTTPS_PROXY": f"http://127.0.0.1:{proxy.port}"},
            ssl_context=certificate.client_context(),
        )
        provider = _provider(f"https://localhost:{tls_port}/v1", transport)
        provider.complete(_request())
    assert proxy.requests == []
    assert seen == ["/v1/chat/completions"]


# Certificates


class Counting:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls = 0

    def __call__(self, request: HttpRequest, timeout_seconds: float) -> HttpResponse:
        self.calls += 1
        result: HttpResponse = self.inner(request, timeout_seconds)
        return result


def test_host_the_system_trust_store_cannot_verify_is_not_retried(tmp_path: Path) -> None:
    certificate = make_certificate(tmp_path, "localhost")
    with tls_server(certificate) as (tls_port, seen):
        # The system trust store does not know this synthetic certificate.
        counting = Counting(HttpTransport(environ={}))
        provider = _provider(f"https://localhost:{tls_port}/v1", counting)
        started = time.monotonic()
        with pytest.raises(ModelUnavailableError) as caught:
            provider.complete(_request())
    assert counting.calls == 1
    assert time.monotonic() - started < 2.0
    assert "the system trust store could not verify localhost" in str(caught.value)
    assert seen == []


def test_certificate_failure_from_any_transport_is_not_retried() -> None:
    failure = ssl.SSLCertVerificationError(1, "certificate verify failed: synthetic")
    transport = ScriptedTransport(failure)
    time_ = FakeTime()
    provider = _provider(
        "https://api.example.org/v1", transport, sleep=time_.sleep, clock=time_.clock
    )
    with pytest.raises(ModelUnavailableError, match=r"could not verify api\.example\.org"):
        provider.complete(_request())
    assert len(transport.calls) == 1
    assert time_.slept == []
