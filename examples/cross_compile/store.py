"""Persistent storage using wire storage axis.

Uses FileStorage directly (it handles pickle persistence internally).
Wraps async FileStorage in dict-like interface for legacy sync code.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict

from kungfu import Ok, Some

from emergent.wire.axis import storage


STORAGE_PATH = str(Path(__file__).parent / ".notes_storage.pickle")


class NoteData(TypedDict):
    """Note data structure."""
    title: str
    content: str


class FileStorageDictAdapter:
    """Wraps async wire FileStorage in sync dict interface for legacy code.

    Legacy code uses:
        _notes[id] = {"title": ..., "content": ...}
        del _notes[id]
        for id, note in _notes.items(): ...

    This adapter wraps FileStorage and runs async ops synchronously.
    """

    def __init__(self, backend: storage.FileStorage[str, NoteData]) -> None:
        self._backend = backend

    def _run[T](self, coro: T) -> T:
        """Run async in sync context."""
        try:
            loop = asyncio.get_running_loop()
            # Already in async context - create task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)  # type: ignore[arg-type]
                return future.result()
        except RuntimeError:
            # No running loop - safe to use run_until_complete
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)  # type: ignore[arg-type]
            finally:
                loop.close()

    def __getitem__(self, key: int) -> NoteData:
        result = self._run(self._backend.get(str(key)))
        match result:
            case Ok(Some(value)):
                return value
            case _:
                raise KeyError(key)

    def __setitem__(self, key: int, value: NoteData) -> None:
        self._run(self._backend.set(str(key), value))

    def __delitem__(self, key: int) -> None:
        self._run(self._backend.delete(str(key)))

    def __contains__(self, key: object) -> bool:
        result = self._run(self._backend.get(str(key)))
        match result:
            case Ok(Some(_)):
                return True
            case _:
                return False

    def items(self) -> Iterator[tuple[int, NoteData]]:
        keys_result = self._run(self._backend.keys())
        match keys_result:
            case Ok(keys):
                for k in keys:
                    result = self._run(self._backend.get(k))
                    match result:
                        case Ok(Some(value)):
                            yield int(k), value
                        case _:
                            pass


def create_notes() -> FileStorageDictAdapter:
    """Factory for IsolateGlobal - creates FileStorage-backed dict adapter.

    Each call creates fresh adapter that loads from file.
    FileStorage handles persistence (saves on every write).
    """
    backend: storage.FileStorage[str, NoteData] = storage.FileStorage(STORAGE_PATH)
    return FileStorageDictAdapter(backend)


def get_state() -> dict[str, NoteData]:
    """Read current state for CLI inspection."""
    adapter = create_notes()
    return {str(k): v for k, v in adapter.items()}
