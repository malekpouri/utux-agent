"""The checkpoint serializer of a run's graph.

LangGraph's `JsonPlusSerializer` stores Python objects as msgpack extension
types that name a module and a class, and constructs them on load. By default
it constructs any class it is given; in its strict mode it still constructs
the classes on its own safe list (`langgraph.checkpoint.serde._msgpack`,
`SAFE_MSGPACK_TYPES`), returns the raw data of any other class, and compiling
a graph widens the list with the types of the state schema
(`BaseCheckpointSaver.with_allowlist`).

utux needs none of this: graph state holds only ids, relative paths, hashes
and small enums, which msgpack encodes natively. `StrictCheckpointSerializer`
therefore refuses every extension type, on write and on read, never falls
back to pickle or to the JSON reviver, and cannot be widened.
"""

from typing import Any, NoReturn

import ormsgpack
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from utux.errors import CheckpointDataError

_PLAIN_KINDS = frozenset({"null", "bytes", "bytearray", "msgpack"})


def _refuse_extension(code: int, data: bytes) -> NoReturn:
    raise CheckpointDataError(
        f"checkpoint data holds msgpack extension type {code}, an object to construct; "
        "graph state must be plain data"
    )


def _unpack_plain(payload: bytes) -> Any:
    refused: list[int] = []

    def refuse(code: int, data: bytes) -> NoReturn:
        refused.append(code)
        _refuse_extension(code, data)

    try:
        return ormsgpack.unpackb(payload, ext_hook=refuse, option=ormsgpack.OPT_NON_STR_KEYS)
    except ormsgpack.MsgpackDecodeError as error:
        # ormsgpack replaces the hook's exception with its own, so the
        # refusal is recognised by what the hook recorded.
        if refused:
            raise CheckpointDataError(
                f"checkpoint data holds msgpack extension type {refused[0]}, an object to "
                "construct; graph state must be plain data"
            ) from None
        raise CheckpointDataError(f"checkpoint data is not valid msgpack: {error}") from error


class StrictCheckpointSerializer(JsonPlusSerializer):
    """A checkpoint serializer that stores and loads plain data only.

    Plain data is None, booleans, numbers, strings, bytes, and lists and
    dicts of these. Anything else raises `CheckpointDataError`.
    """

    def __init__(self) -> None:
        super().__init__(
            pickle_fallback=False,
            allowed_json_modules=None,
            allowed_msgpack_modules=None,
            __unpack_ext_hook__=_refuse_extension,
        )

    def with_msgpack_allowlist(self, extra_allowlist: Any) -> "StrictCheckpointSerializer":
        """Return this serializer unchanged: its allowlist is empty for good."""
        return self

    def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
        """Serialize plain data, refusing anything stored as an object."""
        kind, data = super().dumps_typed(obj)
        # Reading it back with the refusing hook finds any object in it before
        # it reaches the database.
        self.loads_typed((kind, data))
        return kind, data

    def loads_typed(self, data: tuple[str, bytes]) -> Any:
        """Deserialize plain data, refusing every object and every other kind."""
        kind, payload = data
        if kind not in _PLAIN_KINDS:
            raise CheckpointDataError(
                f"checkpoint data of kind {kind!r} is refused; only plain msgpack is read"
            )
        if kind == "msgpack":
            return _unpack_plain(payload)
        return super().loads_typed(data)
