"""A self-signed certificate, a loopback TLS server and a loopback proxy, for tests.

Everything here runs on 127.0.0.1 inside the test. The certificate is
synthetic and made for each test run.
"""

import contextlib
import selectors
import shutil
import socket
import socketserver
import ssl
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from provider_fakes import fixture_body

SYNTHETIC_HOST = "api.synthetic.test"


@dataclass
class Certificate:
    certfile: Path
    keyfile: Path

    def client_context(self) -> ssl.SSLContext:
        """A client context that trusts only this certificate."""
        context = ssl.create_default_context(cafile=str(self.certfile))
        return context


def make_certificate(directory: Path, *names: str) -> Certificate:
    if shutil.which("openssl") is None:
        pytest.skip("openssl is needed to make a test certificate")
    certfile, keyfile = directory / "cert.pem", directory / "key.pem"
    san = ",".join(f"DNS:{name}" for name in names)
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(keyfile),
            "-out",
            str(certfile),
            "-subj",
            f"/CN={names[0]}",
            "-addext",
            f"subjectAltName={san}",
        ],
        check=True,
        capture_output=True,
    )
    return Certificate(certfile, keyfile)


class _CompletionHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        """Keep the test output quiet."""

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers["Content-Length"]))
        self.server.seen.append(self.path)  # type: ignore[attr-defined]
        payload = fixture_body("openai_completion_without_cost.json")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(payload)


@contextlib.contextmanager
def tls_server(certificate: Certificate) -> Iterator[tuple[int, list[str]]]:
    """An HTTPS server that answers every POST with a synthetic completion."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _CompletionHandler)
    httpd.daemon_threads = True
    httpd.seen = []  # type: ignore[attr-defined]
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate.certfile, certificate.keyfile)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1], httpd.seen  # type: ignore[attr-defined]
    finally:
        httpd.shutdown()
        httpd.server_close()


@dataclass
class Proxy:
    port: int
    requests: list[str] = field(default_factory=list)


class _ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            data += chunk
        head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1")
        self.server.proxy.requests.append(head)  # type: ignore[attr-defined]
        target = self.server.target_port  # type: ignore[attr-defined]
        if target is None:
            self.request.sendall(
                b"HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\n\r\n"
            )
            return
        upstream = socket.create_connection(("127.0.0.1", target))
        self.request.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        _pipe(self.request, upstream)


def _pipe(left: socket.socket, right: socket.socket) -> None:
    with selectors.DefaultSelector() as selector:
        selector.register(left, selectors.EVENT_READ, right)
        selector.register(right, selectors.EVENT_READ, left)
        while True:
            events = selector.select(timeout=5)
            if not events:
                return
            for key, _ in events:
                source = key.fileobj
                assert isinstance(source, socket.socket)
                try:
                    chunk = source.recv(65536)
                except OSError:
                    return
                if not chunk:
                    return
                key.data.sendall(chunk)


@contextlib.contextmanager
def proxy_server(target_port: int | None) -> Iterator[Proxy]:
    """A CONNECT proxy on loopback.

    With a target port, every tunnel goes to 127.0.0.1 on that port, whatever
    host was asked for. Without one, every CONNECT is answered with 407.
    """
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _ProxyHandler)
    server.daemon_threads = True
    proxy = Proxy(port=server.server_address[1])
    server.proxy = proxy  # type: ignore[attr-defined]
    server.target_port = target_port  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield proxy
    finally:
        server.shutdown()
        server.server_close()
