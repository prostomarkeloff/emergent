"""Schema axis steps — inspect and validate entity structure.

Steps here implement SchemaDerivable and run in pass 1 of fold_derive.

    from derivelib.axes.schema import inspect_entity, require_identity

    derivation = (
        inspect_entity(),        # populate fields from entity
        require_identity(),      # validate Identity field exists
    )
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from derivelib._ctx import SchemaCtx


# ═══════════════════════════════════════════════════════════════════════════════
# Schema Steps
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class InspectEntity:
    """Step: ensure entity fields are inspected.

    SchemaCtx.from_entity() already does this, so this step is a no-op
    by default. Useful as explicit documentation in derivation pipelines,
    or as an extension point for custom inspection.
    """

    def derive_schema[EntityT](self, ctx: SchemaCtx[EntityT]) -> SchemaCtx[EntityT]:
        # SchemaCtx.from_entity already populates fields
        return ctx


@dataclass(frozen=True, slots=True)
class RequireIdentity:
    """Step: validate entity has an Identity field.

    Raises ValueError if entity lacks Annotated[T, Identity] field.
    """

    def derive_schema[EntityT](self, ctx: SchemaCtx[EntityT]) -> SchemaCtx[EntityT]:
        if not ctx.identity_fields:
            raise ValueError(
                f"{ctx.entity.__name__} needs Annotated[T, Identity] field"
            )
        return ctx


@dataclass(frozen=True, slots=True)
class ExcludeSchemaFields:
    """Step: remove fields from schema context.

    Useful for patterns that should ignore certain fields.

    NOTE: This is a schema STEP (SchemaDerivable), not a FieldProjection.
    For projections, use ExcludeFields from derivelib._project.
    """

    names: tuple[str, ...]

    def derive_schema[EntityT](self, ctx: SchemaCtx[EntityT]) -> SchemaCtx[EntityT]:
        filtered = {
            name: info
            for name, info in ctx.fields.items()
            if name not in self.names
        }
        return replace(ctx, fields=filtered)


# Backward compat alias
ExcludeFields = ExcludeSchemaFields


@dataclass(frozen=True, slots=True)
class RequireFields:
    """Step: validate specific fields exist."""

    names: tuple[str, ...]

    def derive_schema[EntityT](self, ctx: SchemaCtx[EntityT]) -> SchemaCtx[EntityT]:
        for name in self.names:
            if name not in ctx.fields:
                raise ValueError(
                    f"{ctx.entity.__name__} missing required field: {name}"
                )
        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience Constructors
# ═══════════════════════════════════════════════════════════════════════════════


def inspect_entity() -> InspectEntity:
    """Create InspectEntity step."""
    return InspectEntity()


def require_identity() -> RequireIdentity:
    """Create RequireIdentity step."""
    return RequireIdentity()


def exclude_fields(*names: str) -> ExcludeFields:
    """Create ExcludeFields step."""
    return ExcludeFields(names=names)


def require_fields(*names: str) -> RequireFields:
    """Create RequireFields step."""
    return RequireFields(names=names)


__all__ = (
    # Steps
    "InspectEntity",
    "RequireIdentity",
    "ExcludeSchemaFields",
    "ExcludeFields",  # backward compat alias
    "RequireFields",
    # Constructors
    "inspect_entity",
    "require_identity",
    "exclude_fields",
    "require_fields",
)
