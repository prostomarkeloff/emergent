"""Schema patterns — common capability compositions.

Patterns are pre-built combinations of universal capabilities.

    from emergent.wire.axis.schema import Id, Email, Slug

    @dataclass
    class User:
        id: Annotated[int, Id]
        email: Annotated[str, Email]
        slug: Annotated[str, Slug]
"""

from emergent.wire.axis.schema._universal import (
    Identity,
    Unique,
    MinLen,
    MaxLen,
    Pattern,
    Min,
    Max,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Identity Patterns
# ═══════════════════════════════════════════════════════════════════════════════


# Primary identifier
Id = (Identity(),)


# ═══════════════════════════════════════════════════════════════════════════════
# String Patterns
# ═══════════════════════════════════════════════════════════════════════════════


# Email: unique, reasonable length
Email = (Unique(), MaxLen(255))

# Slug: URL-friendly, unique
Slug = (Unique(), MaxLen(100), Pattern(r"^[a-z0-9]+(?:-[a-z0-9]+)*$"))

# Username: unique, length constrained
Username = (Unique(), MinLen(3), MaxLen(50))

# Short text (names, titles)
Short = (MaxLen(100),)

# Medium text (descriptions)
Medium = (MaxLen(500),)

# Non-empty short
RequiredShort = (MinLen(1), MaxLen(100))


# ═══════════════════════════════════════════════════════════════════════════════
# Numeric Patterns
# ═══════════════════════════════════════════════════════════════════════════════


# Non-negative number (>= 0)
NonNegative = (Min(0),)

# Percentage (0-100)
Percentage = (Min(0), Max(100))

# Probability (0-1)
Probability = (Min(0), Max(1))


# ═══════════════════════════════════════════════════════════════════════════════
# Indexed Patterns
# ═══════════════════════════════════════════════════════════════════════════════


# Just unique
UniqueValue = (Unique(),)


__all__ = (
    # Identity
    "Id",
    # Strings
    "Email",
    "Slug",
    "Username",
    "Short",
    "Medium",
    "RequiredShort",
    # Numeric
    "NonNegative",
    "Percentage",
    "Probability",
    # Indexed
    "UniqueValue",
)
