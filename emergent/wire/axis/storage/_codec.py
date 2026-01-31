"""Storage codecs — serialization for typed values.

Codec transforms between typed values and bytes.
Like wire codecs transform between transport and domain.
"""

import json
import pickle
from typing import Protocol, Generic, TypeVar

T = TypeVar("T")


class Codec(Protocol[T]):
    """Serialization codec: T ↔ bytes."""

    def encode(self, value: T) -> bytes: ...
    def decode(self, data: bytes) -> T: ...


class PickleCodec(Generic[T]):
    """Pickle serialization. Fast, Python-only."""

    def encode(self, value: T) -> bytes:
        return pickle.dumps(value)

    def decode(self, data: bytes) -> T:
        return pickle.loads(data)  # type: ignore[return-value]


class JsonCodec(Generic[T]):
    """JSON serialization. Interoperable, text-based.

    Note: T must be JSON-serializable (dict, list, str, int, etc.)
    For dataclasses, use with dataclasses.asdict() or pydantic.
    """

    def encode(self, value: T) -> bytes:
        return json.dumps(value).encode("utf-8")

    def decode(self, data: bytes) -> T:
        return json.loads(data.decode("utf-8"))  # type: ignore[return-value]


class IdentityCodec:
    """No-op codec for bytes. Pass-through."""

    def encode(self, value: bytes) -> bytes:
        return value

    def decode(self, data: bytes) -> bytes:
        return data


__all__ = (
    "Codec",
    "PickleCodec",
    "JsonCodec",
    "IdentityCodec",
)
