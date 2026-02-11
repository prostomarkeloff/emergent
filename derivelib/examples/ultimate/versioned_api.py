"""API versioning — projection-based v1/v2 from same entity.

versioned() = DerivationT that duplicates ops with different field projections.
v1 = subset of fields. v2 = full fields.
One entity -> two API surfaces.

    from examples.ultimate.versioned_api import versioned

    @derive(
        http_crud("/v1/users", provider_node=Users, ops=(LIST, GET))
            .chain(versioned(fields=("name",)))
    )
    @dataclass
    class User:
        id: Annotated[int, Identity]
        name: str
        email: str
        avatar: str
"""

from __future__ import annotations

from dataclasses import replace

from derivelib import Derivation, DerivationT, Step, SelectFields


# ═══════════════════════════════════════════════════════════════════════════════
# versioned — DerivationT
# ═══════════════════════════════════════════════════════════════════════════════


def versioned(
    fields: tuple[str, ...],
) -> DerivationT:
    """Restrict read ops to specified field subset.

    Apply to a CRUD dialect to limit what fields are exposed.
    Use with separate @derive paths for v1/v2.

        # v1: only name
        http_crud("/v1/users", ..., ops=(LIST, GET)).chain(versioned(fields=("name",)))

        # v2: full entity (no .chain needed, or use all fields)
        http_crud("/v2/users", ..., ops=(LIST, GET))
    """
    projection = SelectFields(names=fields)

    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp
        from derivelib import Read, has_effect

        result: list[Step] = []
        for s in steps:
            if isinstance(s, DeriveOp) and has_effect(s.effects, Read):
                result.append(replace(s, input_proj=projection))
            else:
                result.append(s)
        return tuple(result)

    return transform


def exclude_fields(
    names: tuple[str, ...],
) -> DerivationT:
    """Remove specified fields from read ops' output.

    Complement of versioned() — exclude instead of select.

        # Hide internal fields:
        http_crud("/public/users", ...).chain(exclude_fields(("internal_score", "admin_notes")))
    """
    from derivelib import ExcludeFields

    projection = ExcludeFields(names=names)

    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp
        from derivelib import Read, has_effect

        result: list[Step] = []
        for s in steps:
            if isinstance(s, DeriveOp) and has_effect(s.effects, Read):
                result.append(replace(s, input_proj=projection))
            else:
                result.append(s)
        return tuple(result)

    return transform


__all__ = (
    "versioned",
    "exclude_fields",
)
