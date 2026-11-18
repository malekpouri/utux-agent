"""M1-02: the checkpoint serializer of utux.core never constructs an object.

Graph state holds only ids, relative paths, hashes and small enums, all of
which msgpack encodes natively. Anything that needs an extension type, which
is how LangGraph's serializer stores Python objects, is refused on write and
on read.
"""

import collections
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal, TypedDict
from uuid import UUID

import ormsgpack
import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from utux.core.checkpoints import StrictCheckpointSerializer
from utux.errors import CheckpointDataError

# LangGraph's extension code for "call a constructor with one argument".
EXT_CONSTRUCTOR_SINGLE_ARG = 0


def _constructor_payload(module: str, name: str, argument: object) -> tuple[str, bytes]:
    inner = ormsgpack.packb([module, name, argument])
    return "msgpack", ormsgpack.packb(ormsgpack.Ext(EXT_CONSTRUCTOR_SINGLE_ARG, inner))


def test_plain_state_round_trips() -> None:
    serde = StrictCheckpointSerializer()
    state = {
        "artifact_id": "a-000001",
        "path": "methodology/method.md",
        "content_hash": "sha256:" + "0" * 64,
        "stage": "methodology",
        "attempt": 2,
        "done": False,
        "inputs": ["inputs/question.md"],
        "parent": None,
    }
    assert serde.loads_typed(serde.dumps_typed(state)) == state


def test_the_default_serializer_constructs_an_object_named_in_the_data() -> None:
    # The control: the payload is valid, and LangGraph's default builds the
    # object it names.
    payload = _constructor_payload("collections", "OrderedDict", [["k", 1]])
    assert isinstance(JsonPlusSerializer().loads_typed(payload), collections.OrderedDict)


def test_an_object_named_in_the_data_is_refused() -> None:
    payload = _constructor_payload("collections", "OrderedDict", [["k", 1]])
    with pytest.raises(CheckpointDataError, match="extension type 0"):
        StrictCheckpointSerializer().loads_typed(payload)


def test_even_a_type_on_langgraphs_safe_list_is_refused() -> None:
    payload = _constructor_payload("pathlib", "Path", "/etc/passwd")
    with pytest.raises(CheckpointDataError):
        StrictCheckpointSerializer().loads_typed(payload)


@pytest.mark.parametrize("kind", ["json", "pickle", "unknown"])
def test_serialization_kinds_other_than_msgpack_are_refused(kind: str) -> None:
    with pytest.raises(CheckpointDataError, match=kind):
        StrictCheckpointSerializer().loads_typed((kind, b"{}"))


@pytest.mark.parametrize(
    "value",
    [Path("methodology/method.md"), Decimal("0.5"), date(2026, 11, 18), UUID(int=1), {"a", "b"}],
)
def test_writing_an_object_is_refused(value: object) -> None:
    with pytest.raises(CheckpointDataError):
        StrictCheckpointSerializer().dumps_typed({"value": value})


def test_compiling_a_graph_cannot_widen_the_allowlist() -> None:
    serde = StrictCheckpointSerializer()
    assert serde.with_msgpack_allowlist([("collections", "OrderedDict")]) is serde


class _State(TypedDict):
    stage: Literal["methodology", "implementation"]
    attempt: int
    paths: list[str]


def test_a_graph_runs_and_resumes_with_the_strict_serializer(tmp_path: Path) -> None:
    graph = StateGraph(_State)
    graph.add_node("method", lambda s: {"stage": "implementation", "paths": ["method.md"]})
    graph.add_node("retry", lambda s: {"attempt": s["attempt"] + 1})
    graph.add_edge(START, "method")
    graph.add_conditional_edges("method", lambda s: "retry" if s["attempt"] < 2 else END)
    graph.add_edge("retry", "method")
    config = {"configurable": {"thread_id": "run-1"}}
    database = tmp_path / "checkpoints.sqlite"

    with sqlite3.connect(database, check_same_thread=False) as connection:
        app = graph.compile(
            checkpointer=SqliteSaver(connection, serde=StrictCheckpointSerializer())
        )
        result = app.invoke({"stage": "methodology", "attempt": 0, "paths": []}, config)
    assert result == {"stage": "implementation", "attempt": 2, "paths": ["method.md"]}

    # A new connection, as after a restart, reads the saved state back.
    with sqlite3.connect(database, check_same_thread=False) as connection:
        app = graph.compile(
            checkpointer=SqliteSaver(connection, serde=StrictCheckpointSerializer())
        )
        assert app.get_state(config).values == result
