"""
Interactive CLI — demonstrates compositional commands.

Each command is a different COMPOSITION of the same building blocks:

┌─────────────────────────────────────────────────────────────────────────┐
│  COMMAND      NODES USED                           WHAT'S SKIPPED       │
├─────────────────────────────────────────────────────────────────────────┤
│  user         Profile, Loyalty, Address, Payment   Items, Tax, Saga     │
│  shipping     Address, Items                       Tax, Fraud, Saga     │
│  preview      All totals nodes                     Fraud, Saga          │
│  checkout     ALL nodes                            Nothing              │
└─────────────────────────────────────────────────────────────────────────┘

The graph only runs what's needed for each command!
"""

from kungfu import Ok, Error

from examples.full_stack.domain import UserId, ProductId, Cart, CartItem
from examples.full_stack.repo import catalog_service, seed_all
from examples.full_stack.graph import (
    CreateOrderNode,
    PreviewNode,
    UserInfoNode,
    ShippingEstimateNode,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Help
# ═══════════════════════════════════════════════════════════════════════════════

HELP_TEXT = """
┌─────────────────────────────────────────────────────────────────────────────┐
│                              COMMANDS                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  user <id>                  Show user info (profile, loyalty, address)      │
│  shipping <id> <items>      Estimate shipping costs                         │
│  preview <id> <items>       Preview order (totals, no payment)              │
│  checkout <id> <items>      Full checkout with payment                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  users                      List available users                            │
│  products                   List available products                         │
│  help                       Show this help                                  │
│  quit                       Exit                                            │
└─────────────────────────────────────────────────────────────────────────────┘

Items format: PRODUCT:QTY,PRODUCT:QTY  (e.g., CABLE:2,PHONE:1)

Examples:
  user 1                    → Show Alice's profile
  shipping 1 LAPTOP:1       → Shipping cost for laptop to Alice
  preview 1 CABLE:2,CASE:1  → Order preview without payment
  checkout 1 CABLE:2,CASE:1 → Full checkout with saga
"""


def print_help() -> None:
    print(HELP_TEXT)


# ═══════════════════════════════════════════════════════════════════════════════
# Data Display
# ═══════════════════════════════════════════════════════════════════════════════

def print_users() -> None:
    print("\n┌────────────────────────────────────────┐")
    print("│              USERS                     │")
    print("├────────────────────────────────────────┤")
    print("│  [1] Alice  gold   15% discount        │")
    print("│  [2] Bob    bronze  5% discount        │")
    print("└────────────────────────────────────────┘")


def print_products() -> None:
    print("\n┌────────────────────────────────────────────────┐")
    print("│                  PRODUCTS                       │")
    print("├────────────────────────────────────────────────┤")
    for p in catalog_service.list_all():
        line = f"│  [{p.id.value:6}] {p.name:20} ${p.base_price/100:>8.2f} │"
        print(line)
    print("└────────────────────────────────────────────────┘")


# ═══════════════════════════════════════════════════════════════════════════════
# Parsing
# ═══════════════════════════════════════════════════════════════════════════════

def parse_items(items_str: str) -> list[CartItem]:
    """Parse 'CABLE:2,PHONE:1' into CartItem list."""
    items: list[CartItem] = []
    for part in items_str.split(","):
        if ":" not in part:
            raise ValueError(f"Invalid format: {part} (expected PRODUCT:QTY)")
        product_id, qty = part.split(":")
        items.append(CartItem(ProductId(product_id.upper()), int(qty)))
    return items


def make_cart(user_id: int, items_str: str) -> Cart | None:
    """Create cart from CLI input."""
    try:
        items = parse_items(items_str)
        return Cart(UserId(user_id), tuple(items))
    except ValueError as e:
        print(f"  ✗ Error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Commands
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_user(user_id: int) -> None:
    """Show user info — only runs user-related nodes."""
    result = await UserInfoNode.execute(UserId(user_id))
    
    match result:
        case Ok(info):
            profile_badge = " 📦" if info.profile_cached else ""
            loyalty_badge = " 📦" if info.loyalty_cached else ""
            print(f"""
┌────────────────────────────────────────────────┐
│  USER {info.user_id}                                       │
├────────────────────────────────────────────────┤
│  Name:     {info.name:26}{profile_badge:9} │
│  Email:    {info.email:35} │
├────────────────────────────────────────────────┤
│  Loyalty:  {info.loyalty_level:10} ({info.loyalty_discount}% discount){loyalty_badge:6} │
│  Free ship: orders over ${info.free_shipping_threshold/100:.0f}               │
├────────────────────────────────────────────────┤
│  Address:  {info.address_full:35} │
│  Payment:  {info.payment_type} ****{info.payment_last_four:27} │
└────────────────────────────────────────────────┘
""")
            if info.profile_cached or info.loyalty_cached:
                print("  📦 = served from cache")
        
        case Error(e):
            print(f"\n  ✗ Failed: [{e.code}] {e.message}")


async def cmd_shipping(user_id: int, items_str: str) -> None:
    """Estimate shipping — only runs address + items nodes."""
    cart = make_cart(user_id, items_str)
    if not cart:
        return
    
    print(f"\n  Shipping estimate for user {user_id}:")
    for item in cart.items:
        print(f"    • {item.quantity}x {item.product_id.value}")
    
    result = await ShippingEstimateNode.execute(cart)
    
    match result:
        case Ok(estimate):
            print(f"""
┌────────────────────────────────────────────────┐
│  SHIPPING ESTIMATE                              │
│  Ship to: {estimate.ship_to_city}, {estimate.ship_to_state:28} │
├────────────────────────────────────────────────┤""")
            for line in estimate.lines:
                print(f"│  {line.quantity}x {line.product_name:20} ${line.cost/100:>6.2f}  {line.days}d │")
            print(f"""├────────────────────────────────────────────────┤
│  TOTAL: ${estimate.total_cost/100:>6.2f}  ({estimate.estimated_days} days max)           │
└────────────────────────────────────────────────┘
""")
        
        case Error(e):
            print(f"\n  ✗ Failed: [{e.code}] {e.message}")


async def cmd_preview(user_id: int, items_str: str) -> None:
    """Preview order — runs all except fraud/saga/payment."""
    cart = make_cart(user_id, items_str)
    if not cart:
        return
    
    print(f"\n  Order preview for user {user_id}:")
    for item in cart.items:
        print(f"    • {item.quantity}x {item.product_id.value}")
    
    result = await PreviewNode.execute(cart)
    
    match result:
        case Ok(preview):
            print(f"""
┌────────────────────────────────────────────────┐
│  ORDER PREVIEW (no payment)                     │
├────────────────────────────────────────────────┤
│  Customer: {preview.user_name:35} │
│  Loyalty:  {preview.loyalty_level} ({preview.loyalty_discount_percent}% off)                    │
│  Ship to:  {preview.shipping_city}, {preview.shipping_state:27} │
├────────────────────────────────────────────────┤
│  Items:                                         │""")
            for item in preview.items:
                disc = item.pricing.product_discount + item.pricing.loyalty_discount
                disc_str = f" (-${disc/100:.2f})" if disc else ""
                print(f"│    {item.item.quantity}x {item.product.name:18} ${item.pricing.unit_price/100:.2f}{disc_str:10} │")
            print(f"""├────────────────────────────────────────────────┤
│  Subtotal:   ${preview.subtotal/100:>8.2f}                       │
│  Discounts: -${preview.discounts/100:>8.2f}                       │
│  Shipping:   ${preview.shipping/100:>8.2f}                       │
│  Tax ({preview.tax_rate*100:.0f}%):    ${preview.tax_amount/100:>8.2f}                       │
├────────────────────────────────────────────────┤
│  TOTAL:      ${preview.grand_total/100:>8.2f}                       │
└────────────────────────────────────────────────┘

  ⚠️  This is a preview. Use 'checkout' to complete the order.
""")
        
        case Error(e):
            print(f"\n  ✗ Failed: [{e.code}] {e.message}")


async def cmd_checkout(user_id: int, items_str: str) -> None:
    """Full checkout — runs ALL nodes including saga."""
    cart = make_cart(user_id, items_str)
    if not cart:
        return
    
    print(f"\n  Checkout for user {user_id}:")
    for item in cart.items:
        print(f"    • {item.quantity}x {item.product_id.value}")
    
    result = await CreateOrderNode.execute(cart)

    match result:
        case Ok(order):
            print(f"""
╔════════════════════════════════════════════════╗
║  ORDER {order.order_id.value:39} ║
╠════════════════════════════════════════════════╣
║  Customer: {order.user.name:35} ║
║  Loyalty:  {order.loyalty_tier.level:35} ║
║  Ship to:  {order.shipping_address.city}, {order.shipping_address.state:27} ║
║  Payment:  ****{order.payment_method.last_four:32} ║
╠════════════════════════════════════════════════╣
║  Items:                                         ║""")
            for item in order.items:
                disc_str = f" (-${item.discounts/100:.2f})" if item.discounts else ""
                print(f"║    {item.quantity}x {item.product.name:18} ${item.unit_price/100:.2f}{disc_str:10} ║")
            print(f"""╠════════════════════════════════════════════════╣
║  Subtotal:   ${order.subtotal/100:>8.2f}                       ║
║  Discounts: -${order.total_discounts/100:>8.2f}                       ║
║  Shipping:   ${order.shipping_total/100:>8.2f}                       ║
║  Tax ({order.tax.tax_rate*100:.0f}%):    ${order.tax.tax_amount/100:>8.2f}                       ║
╠════════════════════════════════════════════════╣
║  TOTAL:      ${order.grand_total/100:>8.2f}                       ║
╠════════════════════════════════════════════════╣
║  Auth Code:  {order.auth_code:33} ║
╚════════════════════════════════════════════════╝

  ✓ Order complete! Inventory reserved, payment authorized.
""")

        case Error(e):
            print(f"\n  ✗ Checkout failed: [{e.code}] {e.message}")


# ═══════════════════════════════════════════════════════════════════════════════
# Main Loop
# ═══════════════════════════════════════════════════════════════════════════════

BANNER = """
╔════════════════════════════════════════════════════════════════════════════╗
║                    EMERGENT FULL STACK EXAMPLE                              ║
╠════════════════════════════════════════════════════════════════════════════╣
║                                                                             ║
║  This demo shows COMPOSITIONAL COMMANDS built from reusable nodes:          ║
║                                                                             ║
║    • user      → ProfileNode + LoyaltyNode + AddressNode + PaymentNode     ║
║    • shipping  → AddressNode + ItemsDataNode                               ║
║    • preview   → All totals (no fraud/saga)                                ║
║    • checkout  → EVERYTHING (including saga with rollback)                  ║
║                                                                             ║
║  Each command reuses the same building blocks — the graph only runs        ║
║  what's needed. Cache hits show on repeat calls!                           ║
║                                                                             ║
╚════════════════════════════════════════════════════════════════════════════╝
"""


async def run_cli() -> None:
    seed_all()

    print(BANNER)
    print_help()
    print_products()
    print_users()

    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not line:
            continue

        parts = line.split(maxsplit=2)
        cmd = parts[0].lower()

        match cmd:
            case "quit" | "exit" | "q":
                print("Bye!")
                break
            
            case "help" | "h" | "?":
                print_help()
            
            case "users":
                print_users()
            
            case "products":
                print_products()
            
            case "user":
                if len(parts) != 2:
                    print("  Usage: user <user_id>")
                    print("  Example: user 1")
                    continue
                try:
                    await cmd_user(int(parts[1]))
                except ValueError:
                    print("  ✗ user_id must be a number")
            
            case "shipping":
                if len(parts) != 3:
                    print("  Usage: shipping <user_id> <items>")
                    print("  Example: shipping 1 CABLE:2,PHONE:1")
                    continue
                try:
                    await cmd_shipping(int(parts[1]), parts[2])
                except ValueError:
                    print("  ✗ user_id must be a number")
            
            case "preview":
                if len(parts) != 3:
                    print("  Usage: preview <user_id> <items>")
                    print("  Example: preview 1 CABLE:2,PHONE:1")
                    continue
                try:
                    await cmd_preview(int(parts[1]), parts[2])
                except ValueError:
                    print("  ✗ user_id must be a number")
            
            case "checkout":
                if len(parts) != 3:
                    print("  Usage: checkout <user_id> <items>")
                    print("  Example: checkout 1 CABLE:2,PHONE:1")
                    continue
                try:
                    await cmd_checkout(int(parts[1]), parts[2])
                except ValueError:
                    print("  ✗ user_id must be a number")
            
            case _:
                print(f"  ✗ Unknown command: {cmd}")
                print("  Type 'help' for available commands.")
