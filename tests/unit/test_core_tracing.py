"""M1-02: LangSmith tracing stays off in utux.core, even when the environment
switches it on.

Each graph runs in a fresh interpreter with every outbound connection
refused and recorded, so nothing leaves the machine. The key is a dummy made
of letters that do not occur in hex ids, so that any four characters of it
in an output can only come from the key.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

DUMMY_KEY = "qzxjkvwpzqtrslmnyz"

# The recorder is registered with atexit before anything imports langsmith,
# so it runs after langsmith's own exit-time flush (atexit runs in reverse).
SCRIPT = textwrap.dedent(
    """
    import atexit, socket, sqlite3, sys

    attempts = []

    def refuse(*args, **kwargs):
        attempts.append(repr(args[:2]))
        raise OSError("connection refused by the test")

    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    socket.socket.sendto = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse
    atexit.register(lambda: print("ATTEMPTS", len(attempts), flush=True))

    if sys.argv[2] == "utux":
        import utux.core  # noqa: F401
        from utux.core.checkpoints import StrictCheckpointSerializer
        serde = StrictCheckpointSerializer()
    else:
        serde = None

    from typing import TypedDict
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import END, START, StateGraph

    class State(TypedDict):
        n: int

    graph = StateGraph(State)
    graph.add_node("first", lambda state: {"n": state["n"] + 1})
    graph.add_node("second", lambda state: {"n": state["n"] * 2})
    graph.add_edge(START, "first")
    graph.add_edge("first", "second")
    graph.add_edge("second", END)
    connection = sqlite3.connect(sys.argv[1], check_same_thread=False)
    app = graph.compile(checkpointer=SqliteSaver(connection, serde=serde))
    print("RESULT", app.invoke({"n": 1}, {"configurable": {"thread_id": "t1"}})["n"])
    connection.close()
    """
)


def _run(tmp_path: Path, mode: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    home = tmp_path / "home"
    home.mkdir()
    database = tmp_path / "checkpoints.sqlite"
    # Only what the interpreter needs: no key of the developer's environment
    # reaches the child.
    env = {
        "PATH": os.defpath,
        "HOME": str(home),
        "LANGSMITH_TRACING": "true",
        "LANGSMITH_API_KEY": DUMMY_KEY,
    }
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(database), mode],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=tmp_path,
        timeout=120,
    )
    return result, database


def _key_parts(length: int = 4) -> set[str]:
    return {DUMMY_KEY[i : i + length] for i in range(len(DUMMY_KEY) - length + 1)}


def _written_bytes(tmp_path: Path) -> bytes:
    return b"".join(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())


def test_utux_core_attempts_no_connection_and_leaks_no_part_of_the_key(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, "utux")
    assert result.returncode == 0, result.stderr
    assert "RESULT 4" in result.stdout
    assert "ATTEMPTS 0" in result.stdout
    outputs = result.stdout + result.stderr
    written = _written_bytes(tmp_path)
    for part in _key_parts():
        assert part not in outputs
        assert part.encode() not in written


def test_without_utux_core_the_same_graph_tries_to_send_traces(tmp_path: Path) -> None:
    # The control: it shows that the environment really switches tracing on,
    # that the recorder sees the attempts, and that the key check can fail.
    result, _ = _run(tmp_path, "plain")
    assert "RESULT 4" in result.stdout
    attempts = int(result.stdout.split("ATTEMPTS ")[1].split()[0])
    assert attempts > 0
    assert any(part in result.stderr for part in _key_parts())
