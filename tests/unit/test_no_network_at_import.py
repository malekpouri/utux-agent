"""M0-10: no module of utux accesses the network when it is imported."""

import subprocess
import sys
import textwrap
from pathlib import Path

# Runs in a fresh interpreter, so that every module is really imported.
GUARD = textwrap.dedent(
    """
    import importlib, pkgutil, socket, sys

    def refuse(*args, **kwargs):
        raise RuntimeError("network access at import time")

    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    socket.socket.sendto = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse

    package = importlib.import_module(sys.argv[1])
    names = [package.__name__] + [
        module.name for module in pkgutil.walk_packages(package.__path__, package.__name__ + ".")
    ]
    for name in names:
        importlib.import_module(name)
    print(len(names))
    """
)


def _import_all(package: str, *extra_path: Path) -> subprocess.CompletedProcess[str]:
    env_path = os_pathsep_join(extra_path)
    return subprocess.run(
        [sys.executable, "-c", GUARD, package],
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": env_path} if env_path else None,
    )


def os_pathsep_join(paths: tuple[Path, ...]) -> str:
    import os

    return os.pathsep.join(str(path) for path in paths)


def test_importing_every_module_of_utux_opens_no_connection() -> None:
    result = _import_all("utux")
    assert result.returncode == 0, result.stderr
    # The walk really found the modules, the providers among them.
    assert int(result.stdout) > 30


def test_the_guard_catches_a_module_that_connects_at_import(tmp_path: Path) -> None:
    package = tmp_path / "synthetic_net"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "fetch.py").write_text(
        "import socket\nsocket.create_connection(('192.0.2.1', 80), timeout=1)\n",
        encoding="utf-8",
    )
    result = _import_all("synthetic_net", tmp_path)
    assert result.returncode != 0
    assert "network access at import time" in result.stderr
