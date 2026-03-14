"""Tests for py2rust transpiler — fold-based Python→Rust translation."""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from typing import Annotated

from kungfu import Error, Ok, Result

from emergent.wire.axis.schema._universal import Identity
from emergent.wire.derive.patterns.methods import get, post

from py2rust._ast import (
    AwaitExpr,
    Binary,
    BinOp,
    Block,
    ExprStmt,
    FieldAccess,
    FnCall,
    Ident,
    IfExpr,
    Let,
    Lit,
    MacroCall,
    MethodCall,
    Path,
    ReturnStmt,
    StructExpr,
    TryExpr,
    Unary,
    UnOp,
)
from py2rust._render import _render_block, render_item
from py2rust._target import RustAppContext, axum_sqlx_sqlite, fold_target
from py2rust._transpile import (
    DiscoveredMethod,
    TranspileContext,
    Translator,
    discover_methods,
    transpile_method,
)
from py2rust._transpile_rules import DEFAULT_TRANSLATOR, build_default_translator


# =============================================================================
# Test fixtures
# =============================================================================


@dataclass
class Bounty:
    id: Annotated[int, Identity]
    title: str
    reward: int
    status: str
    hunter: str | None = None

    @classmethod
    @post("/bounties/{bounty_id}/claim")
    async def claim(cls, db, bounty_id: int, hunter: str) -> Result[Bounty, str]:
        bounty = await db.fetch_one(None)
        if bounty is None:
            return Error(f"bounty {bounty_id} not found")
        if bounty.status != "open":
            return Error(f"already {bounty.status}")
        updated = replace(bounty, status="claimed", hunter=hunter)
        return Ok(updated)

    @classmethod
    @get("/bounties")
    async def list_all(cls, db) -> Result[list, str]:
        items = await db.fetch_many(None)
        return Ok(items)


def _ctx(entity_name: str = "Bounty") -> TranspileContext:
    return TranspileContext(
        entity_name=entity_name,
        entity_type=type,
        entity_fields={},
        id_cols=("id",),
        sa_table=None,
        app=RustAppContext(),
    )


def _translate_expr(code: str, ctx: TranspileContext | None = None) -> object:
    node = ast.parse(code, mode="eval").body
    return DEFAULT_TRANSLATOR.translate_expr(node, ctx or _ctx())


def _translate_body(code: str, ctx: TranspileContext | None = None) -> Block:
    return DEFAULT_TRANSLATOR.translate_body(ast.parse(code).body, ctx or _ctx())


def _render_body(code: str, ctx: TranspileContext | None = None) -> str:
    block = _translate_body(code, ctx)
    return _render_block(block, 0)


# =============================================================================
# Tier 1 — Expression rules
# =============================================================================


class TestLiteralRule:
    def test_int(self) -> None:
        assert _translate_expr("42") == Lit(42)

    def test_float(self) -> None:
        assert _translate_expr("3.14") == Lit(3.14)

    def test_string(self) -> None:
        assert _translate_expr('"hello"') == Lit("hello")

    def test_bool_true(self) -> None:
        assert _translate_expr("True") == Lit(True)

    def test_bool_false(self) -> None:
        assert _translate_expr("False") == Lit(False)

    def test_none(self) -> None:
        assert _translate_expr("None") == Path("None")


class TestNameRule:
    def test_simple(self) -> None:
        assert _translate_expr("x") == Ident("x")


class TestAttributeRule:
    def test_field_access(self) -> None:
        result = _translate_expr("obj.field")
        assert result == FieldAccess(Ident("obj"), "field")


class TestBinOpRule:
    def test_add(self) -> None:
        result = _translate_expr("a + b")
        assert result == Binary(Ident("a"), BinOp.ADD, Ident("b"))

    def test_sub(self) -> None:
        result = _translate_expr("a - b")
        assert result == Binary(Ident("a"), BinOp.SUB, Ident("b"))

    def test_mul(self) -> None:
        result = _translate_expr("a * b")
        assert result == Binary(Ident("a"), BinOp.MUL, Ident("b"))


class TestCompareRule:
    def test_eq(self) -> None:
        result = _translate_expr("x == 5")
        assert result == Binary(Ident("x"), BinOp.EQ, Lit(5))

    def test_ne(self) -> None:
        result = _translate_expr('x != "open"')
        assert result == Binary(Ident("x"), BinOp.NE, Lit("open"))

    def test_is_none(self) -> None:
        result = _translate_expr("x is None")
        assert result == MethodCall(Ident("x"), "is_none", ())

    def test_is_not_none(self) -> None:
        result = _translate_expr("x is not None")
        assert result == MethodCall(Ident("x"), "is_some", ())


class TestUnaryRule:
    def test_not(self) -> None:
        result = _translate_expr("not x")
        assert result == Unary(UnOp.NOT, Ident("x"))

    def test_neg(self) -> None:
        result = _translate_expr("-x")
        assert result == Unary(UnOp.NEG, Ident("x"))


class TestAwaitRule:
    def test_await(self) -> None:
        node = ast.parse("await foo()").body[0].value
        result = DEFAULT_TRANSLATOR.translate_expr(node, _ctx())
        assert isinstance(result, AwaitExpr)


class TestCallRule:
    def test_fn_call(self) -> None:
        result = _translate_expr("foo(1, 2)")
        assert result == FnCall(Path("foo"), (Lit(1), Lit(2)))


class TestMethodCallRule:
    def test_method_call(self) -> None:
        result = _translate_expr("obj.method(a, b)")
        assert result == MethodCall(Ident("obj"), "method", (Ident("a"), Ident("b")))


# =============================================================================
# Tier 2 — Statement rules
# =============================================================================


class TestAssignRule:
    def test_simple_assign(self) -> None:
        block = _translate_body("x = 42")
        assert len(block.stmts) == 1
        stmt = block.stmts[0]
        assert isinstance(stmt, Let)
        assert stmt.value == Lit(42)


class TestReturnRule:
    def test_return_value(self) -> None:
        block = _translate_body("return 42")
        assert len(block.stmts) == 1
        stmt = block.stmts[0]
        assert isinstance(stmt, ReturnStmt)
        assert stmt.value == Lit(42)


class TestIfRule:
    def test_if_else(self) -> None:
        code = "if x > 0:\n    return 1\nelse:\n    return 0"
        block = _translate_body(code)
        # The if is the last (and only) statement, so it becomes the block's trailing expr
        if block.expr is not None:
            assert isinstance(block.expr, IfExpr)
        else:
            assert len(block.stmts) == 1
            stmt = block.stmts[0]
            assert isinstance(stmt, ExprStmt)
            assert isinstance(stmt.expr, IfExpr)


class TestForRule:
    def test_for_loop(self) -> None:
        code = "for x in items:\n    pass"
        block = _translate_body(code)
        assert len(block.stmts) == 1


# =============================================================================
# Tier 3 — Domain rules
# =============================================================================


class TestResultRule:
    def test_ok(self) -> None:
        result = _translate_expr("Ok(x)")
        assert isinstance(result, FnCall)
        assert isinstance(result.func, Path)
        assert result.func.path == "Ok"
        inner = result.args[0]
        assert isinstance(inner, FnCall)
        assert isinstance(inner.func, Path)
        assert inner.func.path == "Json"

    def test_error(self) -> None:
        result = _translate_expr('Error("bad")')
        assert isinstance(result, FnCall)
        assert isinstance(result.func, Path)
        assert result.func.path == "Err"


class TestDataclassReplaceRule:
    def test_replace(self) -> None:
        result = _translate_expr('replace(obj, status="claimed")')
        assert isinstance(result, StructExpr)
        assert result.name == "Bounty"
        assert len(result.fields) == 1
        assert result.fields[0].name == "status"
        assert result.rest == Ident("obj")


# =============================================================================
# Tier 4 — Advanced rules
# =============================================================================


class TestFStringRule:
    def test_fstring(self) -> None:
        node = ast.parse('f"hello {name}"', mode="eval").body
        result = DEFAULT_TRANSLATOR.translate_expr(node, _ctx())
        assert isinstance(result, MacroCall)
        assert result.name == "format"
        assert '"hello {}"' in (result.raw_args or "")


class TestNoneGuardFusionRule:
    def test_fusion(self) -> None:
        code = 'if x is None:\n    return Error("not found")'
        block = _translate_body(code)
        # Should produce a Let with .ok_or()?
        assert len(block.stmts) == 1
        stmt = block.stmts[0]
        assert isinstance(stmt, Let)
        assert isinstance(stmt.value, TryExpr)


# =============================================================================
# Rendering integration
# =============================================================================


class TestRendering:
    def test_claim_body(self) -> None:
        code = """\
if bounty is None:
    return Error(f"bounty {bounty_id} not found")
if bounty.status != "open":
    return Error(f"already {bounty.status}")
updated = replace(bounty, status="claimed", hunter=hunter)
return Ok(updated)
"""
        rendered = _render_body(code)
        assert "ok_or" in rendered
        assert "AppError::BadRequest" in rendered
        assert "Bounty {" in rendered
        assert "..bounty" in rendered
        assert "Ok(Json(updated))" in rendered
        assert 'format!("bounty {} not found", bounty_id)' in rendered
        assert 'format!("already {}", bounty.status)' in rendered


# =============================================================================
# Discovery
# =============================================================================


class TestDiscovery:
    def test_discover_methods(self) -> None:
        methods = discover_methods(Bounty)
        assert len(methods) == 2
        names = {m.name for m in methods}
        assert "claim" in names
        assert "list_all" in names

    def test_trigger_info(self) -> None:
        methods = discover_methods(Bounty)
        claim = next(m for m in methods if m.name == "claim")
        assert claim.trigger.method == "POST"
        assert claim.trigger.path == "/bounties/{bounty_id}/claim"
        assert claim.is_async

    def test_list_all_trigger(self) -> None:
        methods = discover_methods(Bounty)
        list_all = next(m for m in methods if m.name == "list_all")
        assert list_all.trigger.method == "GET"
        assert list_all.trigger.path == "/bounties"


# =============================================================================
# Transpilation end-to-end
# =============================================================================


class TestTranspileMethod:
    def test_claim_transpiles(self) -> None:
        methods = discover_methods(Bounty)
        claim = next(m for m in methods if m.name == "claim")
        app = fold_target(axum_sqlx_sqlite())
        output = transpile_method(claim, Bounty, app, None, DEFAULT_TRANSLATOR)
        source = render_item(output.handler)
        assert "async fn" in source
        assert "claim_bounty" in source
        assert "ok_or" in source
        assert "Bounty {" in source

    def test_list_all_transpiles(self) -> None:
        methods = discover_methods(Bounty)
        list_all = next(m for m in methods if m.name == "list_all")
        app = fold_target(axum_sqlx_sqlite())
        output = transpile_method(list_all, Bounty, app, None, DEFAULT_TRANSLATOR)
        source = render_item(output.handler)
        assert "async fn" in source

    def test_claim_has_request_struct(self) -> None:
        methods = discover_methods(Bounty)
        claim = next(m for m in methods if m.name == "claim")
        app = fold_target(axum_sqlx_sqlite())
        output = transpile_method(claim, Bounty, app, None, DEFAULT_TRANSLATOR)
        assert output.request_struct is not None
        assert "Request" in output.request_struct.name


# =============================================================================
# Translator extensibility
# =============================================================================


class TestTranslatorExtension:
    def test_with_rule_prepends(self) -> None:
        original = DEFAULT_TRANSLATOR
        new = original.with_rule(PrintToLogRule())
        assert len(new.expr_overrides) == len(original.expr_overrides) + 1

    def test_with_handler_overrides(self) -> None:
        """with_handler replaces base dispatch for a specific node type."""
        def custom_name(node: ast.expr, ctx: TranspileContext, t: Translator) -> object:
            assert isinstance(node, ast.Name)
            return MacroCall("custom", raw_args=f'"{node.id}"')

        custom = DEFAULT_TRANSLATOR.with_handler(ast.Name, custom_name)
        result = custom.translate_expr(ast.parse("x", mode="eval").body, _ctx())
        assert isinstance(result, MacroCall)
        assert result.name == "custom"

    def test_custom_rule_overrides(self) -> None:
        custom = DEFAULT_TRANSLATOR.with_rule(PrintToLogRule())
        node = ast.parse('print("hello")', mode="eval").body
        result = custom.translate_expr(node, _ctx())
        assert isinstance(result, MacroCall)
        assert result.name == "log::info"


@dataclass(frozen=True, slots=True)
class PrintToLogRule:
    def can_translate_expr(self, node: ast.expr, ctx: TranspileContext) -> bool:
        return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"

    def translate_expr(self, node: ast.expr, ctx: TranspileContext, t: Translator) -> object:
        args = tuple(t.translate_expr(a, ctx) for a in node.args)
        return MacroCall("log::info", args=args)


# =============================================================================
# Emergent-specific patterns — real-world coverage
# =============================================================================


class TestAssignTargets:
    """Complex assignment targets that appear in emergent code."""

    def test_field_assign(self) -> None:
        """obj.field = val → obj.field = val;"""
        block = _translate_body("obj.status = \"done\"")
        from py2rust._ast import Assign as RustAssign
        assert len(block.stmts) == 1
        stmt = block.stmts[0]
        assert isinstance(stmt, RustAssign)

    def test_subscript_assign(self) -> None:
        """d[key] = val → d[key] = val;"""
        block = _translate_body("d[\"key\"] = 42")
        from py2rust._ast import Assign as RustAssign
        assert len(block.stmts) == 1
        stmt = block.stmts[0]
        assert isinstance(stmt, RustAssign)

    def test_tuple_destructure(self) -> None:
        """(a, b) = expr → let (a, b) = expr;"""
        block = _translate_body("(a, b) = pair")
        assert len(block.stmts) == 1
        stmt = block.stmts[0]
        assert isinstance(stmt, Let)


class TestCollectionLiterals:
    """Collection expressions common in emergent code."""

    def test_list(self) -> None:
        result = _translate_expr("[1, 2, 3]")
        assert isinstance(result, MacroCall)
        assert result.name == "vec"
        assert len(result.args) == 3

    def test_dict(self) -> None:
        result = _translate_expr('{"a": 1}')
        assert isinstance(result, FnCall)
        assert isinstance(result.func, Path)
        assert result.func.path == "HashMap::from"

    def test_list_comprehension(self) -> None:
        result = _translate_expr("[x * 2 for x in items]")
        assert isinstance(result, MethodCall)
        assert result.method == "collect"

    def test_ternary(self) -> None:
        result = _translate_expr("x if cond else y")
        from py2rust._ast import IfExpr
        assert isinstance(result, IfExpr)


class TestWhileBreakContinue:
    """Loop control flow."""

    def test_while(self) -> None:
        code = "while x > 0:\n    x = x - 1"
        block = _translate_body(code)
        from py2rust._ast import WhileLoop
        assert len(block.stmts) == 1
        assert isinstance(block.stmts[0], WhileLoop)

    def test_break_in_loop(self) -> None:
        code = "for x in items:\n    break"
        block = _translate_body(code)
        from py2rust._ast import ForLoop, BreakStmt
        assert isinstance(block.stmts[0], ForLoop)
        loop_body = block.stmts[0].body
        assert isinstance(loop_body.stmts[0], BreakStmt)

    def test_continue_in_loop(self) -> None:
        code = "for x in items:\n    continue"
        block = _translate_body(code)
        from py2rust._ast import ForLoop, ContinueStmt
        assert isinstance(block.stmts[0], ForLoop)
        loop_body = block.stmts[0].body
        assert isinstance(loop_body.stmts[0], ContinueStmt)


class TestRaiseAssertDelete:
    """Error handling and cleanup patterns."""

    def test_raise_expr(self) -> None:
        block = _translate_body('raise ValueError("bad")')
        assert len(block.stmts) == 1
        stmt = block.stmts[0]
        assert isinstance(stmt, ReturnStmt)
        # Should produce Err(AppError::BadRequest(...))
        assert isinstance(stmt.value, FnCall)

    def test_assert(self) -> None:
        block = _translate_body("assert x > 0")
        # assert is the only stmt, so it becomes trailing expr
        if block.expr is not None:
            assert isinstance(block.expr, MacroCall)
            assert block.expr.name == "assert"
        else:
            assert len(block.stmts) == 1
            stmt = block.stmts[0]
            assert isinstance(stmt, ExprStmt)
            assert isinstance(stmt.expr, MacroCall)
            assert stmt.expr.name == "assert"

    def test_delete(self) -> None:
        block = _translate_body("del x")
        # Single ExprStmt may become trailing expr
        if block.expr is not None:
            assert isinstance(block.expr, FnCall)
            assert isinstance(block.expr.func, Path)
            assert block.expr.func.path == "drop"
        else:
            assert len(block.stmts) == 1
            stmt = block.stmts[0]
            assert isinstance(stmt, ExprStmt)
            assert isinstance(stmt.expr, FnCall)


class TestBoolOps:
    """Boolean operators used in emergent guard conditions."""

    def test_and(self) -> None:
        result = _translate_expr("a and b")
        assert isinstance(result, Binary)
        assert result.op == BinOp.AND

    def test_or(self) -> None:
        result = _translate_expr("a or b")
        assert isinstance(result, Binary)
        assert result.op == BinOp.OR


class TestPatternMatch:
    """Python match/case → Rust match (used heavily in emergent code)."""

    def test_match_value(self) -> None:
        code = 'match status:\n    case "open":\n        x = 1\n    case _:\n        x = 0'
        block = _translate_body(code)
        from py2rust._ast import MatchExpr
        # Single match becomes trailing expr
        if block.expr is not None:
            assert isinstance(block.expr, MatchExpr)
            assert len(block.expr.arms) == 2
        else:
            assert len(block.stmts) == 1
            stmt = block.stmts[0]
            assert isinstance(stmt, ExprStmt)
            assert isinstance(stmt.expr, MatchExpr)
            assert len(stmt.expr.arms) == 2


class TestNestedFunction:
    """Nested function definitions → closures."""

    def test_nested_def(self) -> None:
        code = "def helper(x):\n    return x + 1"
        block = _translate_body(code)
        assert len(block.stmts) == 1
        stmt = block.stmts[0]
        assert isinstance(stmt, Let)
        assert stmt.pattern.name == "helper"
        from py2rust._ast import ClosureExpr
        assert isinstance(stmt.value, ClosureExpr)


class TestLambda:
    """Lambda expressions — filters in emergent queries."""

    def test_lambda(self) -> None:
        result = _translate_expr("lambda x: x + 1")
        from py2rust._ast import ClosureExpr
        assert isinstance(result, ClosureExpr)
        assert len(result.params) == 1
        assert result.params[0].name == "x"


class TestRenderingEmergent:
    """End-to-end rendering tests for emergent patterns."""

    def test_field_assign_renders(self) -> None:
        rendered = _render_body("obj.status = \"done\"")
        assert 'obj.status = "done"' in rendered

    def test_break_continue_render(self) -> None:
        rendered = _render_body("for x in items:\n    if x > 0:\n        break\n    continue")
        assert "break;" in rendered
        assert "continue;" in rendered


from py2rust._ast import BreakStmt, ContinueStmt
