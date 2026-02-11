"""Result combinators — functor maps over Result[Option[A], E].

The natural transformation that every codec-backed pattern uses:

    Result[Option[bytes], E]  →  Result[Option[T], E]

    # Before (6 lines per method):
    match await self.backend.get(key):
        case Ok(Some(data)): return Ok(Some(self.codec.decode(data)))
        case Ok(Nothing()): return Ok(Nothing())
        case Error(e): return Error(e)

    # After (1 line):
    return map_option(await self.backend.get(key), self.codec.decode)
"""

from __future__ import annotations

from collections.abc import Callable

from kungfu import Result, Ok, Error, Option, Some, Nothing


def map_option[A, B, E](
    result: Result[Option[A], E],
    f: Callable[[A], B],
) -> Result[Option[B], E]:
    """Functor map over Result[Option[A], E]."""
    match result:
        case Ok(Some(a)):
            return Ok(Some(f(a)))
        case Ok(Nothing()):
            return Ok(Nothing())
        case Error() as err:
            return err
        case _:
            return Ok(Nothing())


def map_result[A, B, E](
    result: Result[A, E],
    f: Callable[[A], B],
) -> Result[B, E]:
    """Functor map over Result[A, E]."""
    match result:
        case Ok(a):
            return Ok(f(a))
        case Error() as err:
            return err


__all__ = ("map_option", "map_result")
