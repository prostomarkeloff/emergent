"""Import/export — bulk operations from schema inspection.

with_import_export() = DerivationT that adds:
  - POST /path/import: JSON array -> bulk insert
  - GET /path/export: fetch all -> JSON array

Fields derived automatically from entity schema.

    from examples.ultimate.import_export import with_import_export

    @derive(
        http_crud("/products", provider_node=Products)
            .chain(with_import_export())
    )
    @dataclass
    class Product: ...
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kungfu import Ok, Result, Error

from emergent.wire.axis.query import relational
from emergent.wire.axis.surface.triggers.http import HTTPRouteTrigger

from derivelib import (
    exposure, SurfaceCtx, Derivation, DerivationT,
    dict_converter, provider_field, InvalidData,
)
from derivelib._protocols import HasProvider


# ═══════════════════════════════════════════════════════════════════════════════
# Import Step — bulk insert from JSON array
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BulkImportStep:
    """POST /path/import: accept JSON array, bulk insert."""

    base_path: str
    provider_node: type

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        from derivelib._errors import DomainError
        schema = ctx.schema
        entity = schema.entity
        id_names = schema.identity_names()
        non_id = schema.non_identity_fields()
        non_id_names = list(non_id.keys())

        # Handler returns Any to work around ExposureBuilder[EntityT, E] variance
        # dict_converter handles Result[dict, E] -> response dataclass conversion
        async def handler(op: HasProvider[Any]) -> Result[Any, DomainError]:
            items: list[dict[str, str | int | float | bool]] = getattr(op, "items")
            created = 0
            errors: list[str] = []
            for i, item in enumerate(items):
                try:
                    d = {n: item[n] for n in non_id_names if n in item}
                    for name in id_names:
                        d[name] = 0
                    await op.provider.insert(entity(**d))
                    created += 1
                except Exception as e:
                    errors.append(f"row {i}: {e}")
            if errors:
                return Error(InvalidData(entity=entity.__name__, reason="; ".join(errors)))
            result: dict[str, int | list[str]] = {"created": created, "errors": errors}
            return Ok(result)

        fields = {
            "items": list[dict[str, str | int | float | bool]],
            "provider": provider_field(self.provider_node),
        }
        return ctx.add_exposure(
            exposure("import", entity)
            .request(**fields)
            .response(created=int, errors=list[str])
            .response_converter(dict_converter)
            .handler(handler).trigger(HTTPRouteTrigger("POST", f"{self.base_path}/import"))
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Export Step — fetch all as JSON array
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BulkExportStep:
    """GET /path/export: fetch all entities as JSON array."""

    base_path: str
    provider_node: type

    def derive_surface[EntityT](self, ctx: SurfaceCtx[EntityT]) -> SurfaceCtx[EntityT]:
        from derivelib._errors import DomainError
        schema = ctx.schema
        entity = schema.entity
        field_names = list(schema.fields.keys())

        # Handler returns Any to work around ExposureBuilder[EntityT, E] variance
        # dict_converter handles Result[dict, E] -> response dataclass conversion
        async def handler(op: HasProvider[Any]) -> Result[Any, DomainError]:
            q = relational(entity)
            all_entities = await op.provider.fetch_many(q)
            items: list[dict[str, str | int | float | bool]] = [
                {name: getattr(e, name) for name in field_names}
                for e in all_entities
            ]
            result: dict[str, list[dict[str, str | int | float | bool]] | int] = {"items": items, "count": len(items)}
            return Ok(result)

        fields = {
            "provider": provider_field(self.provider_node),
        }
        return ctx.add_exposure(
            exposure("export", entity)
            .request(**fields)
            .response(items=list[dict[str, str | int | float | bool]], count=int)
            .response_converter(dict_converter)
            .handler(handler).trigger(HTTPRouteTrigger("GET", f"{self.base_path}/export"))
        )


# ═══════════════════════════════════════════════════════════════════════════════
# with_import_export — DerivationT
# ═══════════════════════════════════════════════════════════════════════════════


def with_import_export(
    base_path: str | None = None,
    provider_node: type | None = None,
) -> DerivationT:
    """Add import/export endpoints. Path + provider inferred from existing CRUD ops.

        .chain(with_import_export())
    """

    def transform(steps: Derivation) -> Derivation:
        from derivelib.axes.surface import DeriveOp

        # Infer path and provider from first DeriveOp trigger
        path = base_path
        prov = provider_node
        if path is None or prov is None:
            for s in steps:
                if isinstance(s, DeriveOp) and hasattr(s.trigger, "path"):
                    if path is None:
                        raw_path: str = getattr(s.trigger, "path")
                        path = raw_path.split("{")[0].rstrip("/")
                    if prov is None:
                        # Find provider_node from query context in preamble
                        for p in steps:
                            node_t: type | None = getattr(p, "node_type", None)
                            if node_t is not None:
                                prov = node_t
                                break
                    break

        if path is None or prov is None:
            return steps  # Can't infer, return unchanged

        # Prepend so /export and /import register before /{id} in FastAPI
        return (BulkImportStep(path, prov), BulkExportStep(path, prov), *steps)

    return transform


__all__ = (
    # Steps
    "BulkImportStep",
    "BulkExportStep",
    # Transform
    "with_import_export",
)
