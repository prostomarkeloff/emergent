"""
Repositories — simulate microservice calls.

Each repo has artificial latency to show parallel execution benefits.
"""

from dataclasses import dataclass, field
import asyncio

from examples.full_stack.domain import (
    UserId,
    ProductId,
    AddressId,
    PaymentMethodId,
    UserProfile,
    LoyaltyTier,
    Address,
    PaymentMethod,
    Product,
    InventoryStatus,
    ProductPromotion,
    ShippingOption,
    TaxCalculation,
    FraudCheckResult,
    PaymentAuthorization,
    CheckoutError,
)


# ═══════════════════════════════════════════════════════════════════════════════
# User Service (3 endpoints, each ~40ms)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class UserService:
    _profiles: dict[int, UserProfile] = field(default_factory=dict[int, UserProfile])
    _loyalty: dict[int, LoyaltyTier] = field(default_factory=dict[int, LoyaltyTier])
    _addresses: dict[int, Address] = field(default_factory=dict[int, Address])
    _payments: dict[int, PaymentMethod] = field(
        default_factory=dict[int, PaymentMethod]
    )

    def seed(self) -> None:
        self._profiles = {
            1: UserProfile(UserId(1), "Alice", "alice@example.com"),
            2: UserProfile(UserId(2), "Bob", "bob@example.com"),
        }
        self._loyalty = {
            1: LoyaltyTier("gold", 15, 5000),
            2: LoyaltyTier("bronze", 5, 10000),
        }
        self._addresses = {
            1: Address(
                AddressId(1), UserId(1), "123 Main St", "Seattle", "WA", "98101", "US"
            ),
            2: Address(
                AddressId(2), UserId(2), "456 Oak Ave", "Portland", "OR", "97201", "US"
            ),
        }
        self._payments = {
            1: PaymentMethod(PaymentMethodId("pm_1"), UserId(1), "Visa", "4242", True),
            2: PaymentMethod(
                PaymentMethodId("pm_2"), UserId(2), "Mastercard", "5555", True
            ),
        }

    async def get_profile(self, user_id: UserId) -> UserProfile:
        await asyncio.sleep(0.04)
        print(f"      [UserService.profile] {user_id.value}")
        profile = self._profiles.get(user_id.value)
        if not profile:
            raise CheckoutError("USER_NOT_FOUND", f"User {user_id.value} not found")
        return profile

    async def get_loyalty(self, user_id: UserId) -> LoyaltyTier:
        await asyncio.sleep(0.04)
        print(f"      [UserService.loyalty] {user_id.value}")
        return self._loyalty.get(user_id.value, LoyaltyTier("bronze", 0, 10000))

    async def get_default_address(self, user_id: UserId) -> Address:
        await asyncio.sleep(0.04)
        print(f"      [UserService.address] {user_id.value}")
        addr = self._addresses.get(user_id.value)
        if not addr:
            raise CheckoutError("NO_ADDRESS", f"User {user_id.value} has no address")
        return addr

    async def get_default_payment(self, user_id: UserId) -> PaymentMethod:
        await asyncio.sleep(0.04)
        print(f"      [UserService.payment] {user_id.value}")
        pm = self._payments.get(user_id.value)
        if not pm:
            raise CheckoutError(
                "NO_PAYMENT", f"User {user_id.value} has no payment method"
            )
        return pm


# ═══════════════════════════════════════════════════════════════════════════════
# Catalog Service (~30ms)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class CatalogService:
    _products: dict[str, Product] = field(default_factory=dict[str, Product])

    def seed(self) -> None:
        self._products = {
            "LAPTOP": Product(
                ProductId("LAPTOP"), "MacBook Pro", 199900, 2000, "electronics"
            ),
            "PHONE": Product(
                ProductId("PHONE"), "iPhone 15", 99900, 200, "electronics"
            ),
            "CABLE": Product(
                ProductId("CABLE"), "USB-C Cable", 1999, 50, "accessories"
            ),
            "CASE": Product(ProductId("CASE"), "Phone Case", 2999, 100, "accessories"),
        }

    async def get(self, product_id: ProductId) -> Product:
        await asyncio.sleep(0.03)
        print(f"      [CatalogService] {product_id.value}")
        product = self._products.get(product_id.value)
        if not product:
            raise CheckoutError(
                "PRODUCT_NOT_FOUND", f"Product {product_id.value} not found"
            )
        return product

    def list_all(self) -> list[Product]:
        return list(self._products.values())


# ═══════════════════════════════════════════════════════════════════════════════
# Inventory Service (~35ms)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class InventoryReservation:
    """Reservation for saga compensation."""

    product_id: ProductId
    quantity: int
    reservation_id: str


@dataclass
class InventoryService:
    _stock: dict[str, int] = field(default_factory=dict[str, int])
    _reservations: dict[str, InventoryReservation] = field(
        default_factory=dict[str, InventoryReservation]
    )
    _reservation_counter: int = 0

    def seed(self) -> None:
        self._stock = {"LAPTOP": 5, "PHONE": 10, "CABLE": 100, "CASE": 50}
        self._reservations = {}
        self._reservation_counter = 0

    async def check(self, product_id: ProductId, quantity: int) -> InventoryStatus:
        await asyncio.sleep(0.035)
        available = self._stock.get(product_id.value, 0)
        print(f"      [InventoryService] {product_id.value}: {available} available")
        if available < quantity:
            raise CheckoutError(
                "OUT_OF_STOCK", f"{product_id.value}: need {quantity}, have {available}"
            )
        return InventoryStatus(product_id, available, 0, "WH-01")

    async def reserve(
        self, product_id: ProductId, quantity: int
    ) -> InventoryReservation:
        """Reserve inventory for checkout (saga step)."""
        await asyncio.sleep(0.03)
        available = self._stock.get(product_id.value, 0)
        if available < quantity:
            raise CheckoutError(
                "OUT_OF_STOCK", f"{product_id.value}: need {quantity}, have {available}"
            )

        self._reservation_counter += 1
        reservation_id = f"RSV-{self._reservation_counter:04d}"

        # Deduct from available stock
        self._stock[product_id.value] = available - quantity

        reservation = InventoryReservation(product_id, quantity, reservation_id)
        self._reservations[reservation_id] = reservation

        print(
            f"      [InventoryService.reserve] {product_id.value}: reserved {quantity} -> {reservation_id}"
        )
        return reservation

    async def release(self, reservation: InventoryReservation) -> None:
        """Release reservation (saga compensation)."""
        await asyncio.sleep(0.02)
        if reservation.reservation_id in self._reservations:
            # Return stock
            current = self._stock.get(reservation.product_id.value, 0)
            self._stock[reservation.product_id.value] = current + reservation.quantity
            del self._reservations[reservation.reservation_id]
            print(
                f"      [InventoryService.release] {reservation.reservation_id}: released {reservation.quantity}"
            )
        else:
            print(
                f"      [InventoryService.release] {reservation.reservation_id}: already released"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Promotions Service (~45ms)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class PromotionsService:
    async def get_for_product(self, product_id: ProductId) -> ProductPromotion | None:
        await asyncio.sleep(0.045)
        # Simulate: CABLE has 20% off
        if product_id.value == "CABLE":
            print(f"      [PromotionsService] {product_id.value}: 20% off")
            return ProductPromotion(product_id, 20, "Flash sale")
        print(f"      [PromotionsService] {product_id.value}: no promo")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Shipping Service (~50ms per item)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ShippingService:
    async def calculate(
        self, product_id: ProductId, address: Address
    ) -> ShippingOption:
        await asyncio.sleep(0.05)
        # Simulate shipping calculation based on state
        base_cost = 599 if address.state == "WA" else 999
        days = 2 if address.state == "WA" else 5
        print(
            f"      [ShippingService] {product_id.value} -> {address.state}: ${base_cost / 100:.2f}"
        )
        return ShippingOption(product_id, "USPS", base_cost, days)


# ═══════════════════════════════════════════════════════════════════════════════
# Tax Service (~40ms)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class TaxService:
    async def calculate(self, subtotal: int, address: Address) -> TaxCalculation:
        await asyncio.sleep(0.04)
        # State tax rates
        rates = {"WA": 0.10, "OR": 0.0, "CA": 0.0825}
        rate = rates.get(address.state, 0.05)
        tax = int(subtotal * rate)
        print(
            f"      [TaxService] {address.state}: {rate * 100:.1f}% = ${tax / 100:.2f}"
        )
        return TaxCalculation(subtotal, rate, tax, address.state)


# ═══════════════════════════════════════════════════════════════════════════════
# Fraud Service (~60ms)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class FraudService:
    async def check(self, user_id: UserId, amount: int) -> FraudCheckResult:
        await asyncio.sleep(0.06)
        # Simulate: amounts over $5000 get flagged for user 2
        risk = 0.1 if user_id.value == 1 else 0.3
        approved = not (user_id.value == 2 and amount > 500000)
        reason = "OK" if approved else "High risk transaction"
        print(
            f"      [FraudService] User {user_id.value}: risk={risk:.1f}, approved={approved}"
        )
        return FraudCheckResult(user_id, risk, approved, reason)


# ═══════════════════════════════════════════════════════════════════════════════
# Payment Service (~55ms)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class PaymentService:
    _counter: int = 0
    _authorizations: dict[str, PaymentAuthorization] = field(
        default_factory=dict[str, PaymentAuthorization]
    )

    async def authorize(
        self, payment_method: PaymentMethod, amount: int
    ) -> PaymentAuthorization:
        await asyncio.sleep(0.055)
        self._counter += 1
        auth_code = f"AUTH-{self._counter:04d}"
        auth = PaymentAuthorization(payment_method.id, amount, auth_code, True)
        self._authorizations[auth_code] = auth
        print(
            f"      [PaymentService] {payment_method.last_four}: ${amount / 100:.2f} -> {auth_code}"
        )
        return auth

    async def void(self, auth: PaymentAuthorization) -> None:
        """Void authorization (saga compensation)."""
        await asyncio.sleep(0.03)
        if auth.auth_code in self._authorizations:
            del self._authorizations[auth.auth_code]
            print(
                f"      [PaymentService.void] {auth.auth_code}: voided ${auth.amount / 100:.2f}"
            )
        else:
            print(f"      [PaymentService.void] {auth.auth_code}: already voided")


# ═══════════════════════════════════════════════════════════════════════════════
# Singletons
# ═══════════════════════════════════════════════════════════════════════════════

user_service = UserService()
catalog_service = CatalogService()
inventory_service = InventoryService()
promotions_service = PromotionsService()
shipping_service = ShippingService()
tax_service = TaxService()
fraud_service = FraudService()
payment_service = PaymentService()


def seed_all() -> None:
    user_service.seed()
    catalog_service.seed()
    inventory_service.seed()
