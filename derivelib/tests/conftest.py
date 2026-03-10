"""Shared fixtures for derivelib tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from emergent.wire.axis.schema import Identity


@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: str


@dataclass
class Post:
    id: Annotated[int, Identity]
    title: str
    body: str
    published: bool = False


@dataclass
class CompositeKey:
    tenant_id: Annotated[str, Identity]
    user_id: Annotated[int, Identity]
    name: str


@dataclass
class NoIdentity:
    name: str
    value: int
