"""File-based storage implementation with pickle persistence.

FileStorage implements KV capabilities with disk persistence.

    from emergent.wire.axis.storage import FileStorage

    storage = FileStorage[str, User](".data/users.pickle")
    await storage.set("user:1", user)
    match await storage.get("user:1"):
        case Ok(Some(user)): ...
"""

import os
import pickle
from datetime import datetime

from emergent.wire.axis.storage._memory import BaseTTLStorage


class FileStorage(BaseTTLStorage):
    """File-based storage with pickle persistence.

    Implements: Get, Set, SetWithTTL, Delete, SetNX, DeletePattern

    Saves to disk on every write operation.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        """Load data from file if exists."""
        if os.path.exists(self._path):
            with open(self._path, "rb") as f:
                self._data = pickle.load(f)

    def _persist(self) -> None:
        """Save data to file."""
        dir_path = os.path.dirname(self._path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        with open(self._path, "wb") as f:
            pickle.dump(self._data, f)


__all__ = ("FileStorage",)
