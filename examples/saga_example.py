"""
Saga — distributed transactions with auto-rollback.

Level 5: emergent.saga
Level 3: combinators.lift
Level 2: kungfu.Result
"""

from kungfu import Ok, Error
from combinators import lift as L
from emergent import saga as S
from examples._infra import banner, run, Failure


# Mock APIs
async def book_flight(flight: str) -> str:
    print(f"  ✓ Book flight: {flight}")
    return "FL-001"


async def cancel_flight(booking_id: str) -> None:
    print(f"  ← Cancel flight: {booking_id}")


async def book_hotel(hotel: str) -> str:
    print(f"  ✗ Book hotel: {hotel}")
    raise ValueError("No rooms available")


async def cancel_hotel(booking_id: str) -> None:
    print(f"  ← Cancel hotel: {booking_id}")


async def main() -> None:
    banner("Saga: Book Trip")

    # Define saga chain
    saga = (
        S.step(
            action=L.catching_async(lambda: book_flight("NYC→LON"), on_error=lambda e: Failure(str(e))),
            compensate=cancel_flight,
        )
        .then(lambda _: S.step(
            action=L.catching_async(lambda: book_hotel("Hilton"), on_error=lambda e: Failure(str(e))),
            compensate=cancel_hotel,
        ))
    )

    # Execute
    print("\nExecuting saga...")
    result = await S.run_chain(saga)

    match result:
        case Ok(r):
            print(f"\n✓ Success: {r.value}")
        case Error(e):
            print(f"\n✗ Failed: {e.error}")
            print(f"  Rolled back: {e.rollback_complete}")


if __name__ == "__main__":
    run(main)
