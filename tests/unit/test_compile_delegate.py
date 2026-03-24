"""Tests for compile._delegate — compose dialect resolution for handler params.

Covers:
- resolve_handler_params: Node, Optional, Retrieve, fallback, skip logic
- _extract_compose_capability: Annotated extraction
- _get_base_type: base type unwrapping
- _compose_node: nodnod composition wrapper
"""

from __future__ import annotations

from typing import Annotated
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kungfu import Some, Nothing
from nodnod.agent.base import Agent

from emergent.wire.compile._delegate import (
    resolve_handler_params,
    _extract_compose_capability,  # pyright: ignore[reportPrivateUsage]  # tests must exercise internal helpers
    _get_base_type,  # pyright: ignore[reportPrivateUsage]  # tests must exercise internal helpers
    _compose_node,  # pyright: ignore[reportPrivateUsage]  # tests must exercise internal helpers
)
from emergent.wire.axis.schema.dialects.compose import (
    Node as ComposeNode,
    Optional as ComposeOptional,
    Retrieve as ComposeRetrieve,
)


class DummyAgent(Agent):
    """Minimal Agent subclass for test use."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Domain types for tests
# ═══════════════════════════════════════════════════════════════════════════════


class UserNode:
    """Fake nodnod node type."""
    pass


class ConfigNode:
    """Another fake node type."""
    pass


class AuthToken:
    """Fake scope type."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# _extract_compose_capability
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractComposeCapability:
    def test_annotated_with_compose_node(self) -> None:
        cap = ComposeNode(node_type=UserNode)
        annotated_type = Annotated[int, cap]
        result = _extract_compose_capability(annotated_type)
        assert isinstance(result, ComposeNode)
        assert result.node_type is UserNode

    def test_annotated_with_compose_optional(self) -> None:
        cap = ComposeOptional(node_type=ConfigNode)
        annotated_type = Annotated[str, cap]
        result = _extract_compose_capability(annotated_type)
        assert isinstance(result, ComposeOptional)
        assert result.node_type is ConfigNode

    def test_annotated_with_compose_retrieve(self) -> None:
        cap = ComposeRetrieve(from_type=AuthToken)
        annotated_type = Annotated[str, cap]
        result = _extract_compose_capability(annotated_type)
        assert isinstance(result, ComposeRetrieve)
        assert result.from_type is AuthToken

    def test_annotated_without_compose(self) -> None:
        """Annotated with non-compose metadata returns None."""
        annotated_type = Annotated[int, "not a compose cap"]
        result = _extract_compose_capability(annotated_type)
        assert result is None

    def test_plain_type(self) -> None:
        """Non-Annotated type returns None."""
        result = _extract_compose_capability(int)
        assert result is None

    def test_annotated_with_multiple_args_first_compose(self) -> None:
        """Multiple annotations, first compose cap is returned."""
        cap = ComposeNode(node_type=UserNode)
        annotated_type = Annotated[int, "docs", cap]
        result = _extract_compose_capability(annotated_type)
        assert isinstance(result, ComposeNode)

    def test_annotated_single_arg_no_compose(self) -> None:
        """Annotated with only one non-compose annotation."""
        annotated_type = Annotated[str, 42]
        result = _extract_compose_capability(annotated_type)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# _get_base_type
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetBaseType:
    def test_plain_class(self) -> None:
        assert _get_base_type(int) is int

    def test_plain_str(self) -> None:
        assert _get_base_type(str) is str

    def test_annotated_returns_base(self) -> None:
        annotated_type = Annotated[int, "metadata"]
        assert _get_base_type(annotated_type) is int

    def test_annotated_with_non_type_base(self) -> None:
        """Annotated[non_type, ...] returns None when base is not a type."""
        # This requires a special Annotated where first arg is not a type
        # In practice this is unusual, but the function handles it
        result = _get_base_type("not_a_type")
        assert result is None

    def test_list_origin(self) -> None:
        """list[int] has origin list, not Annotated, returns None since list[int] is not a type."""
        result = _get_base_type(list[int])
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# _compose_node
# ═══════════════════════════════════════════════════════════════════════════════


class TestComposeNode:
    @pytest.mark.asyncio
    async def test_successful_composition(self) -> None:
        """Successful composition returns (True, value)."""
        mock_scope = MagicMock()
        mock_agent_cls = DummyAgent

        mock_composer = MagicMock()
        mock_composer.compose = AsyncMock(return_value=(True, "composed_value"))

        with patch(
            "emergent.graph._compose.Composer.create",
            return_value=mock_composer,
        ):
            success, value = await _compose_node(UserNode, mock_scope, mock_agent_cls)
            assert success is True
            assert value == "composed_value"

    @pytest.mark.asyncio
    async def test_failed_composition(self) -> None:
        """Failed composition returns (False, None)."""
        mock_scope = MagicMock()
        mock_agent_cls = DummyAgent

        mock_composer = MagicMock()
        mock_composer.compose = AsyncMock(return_value=(False, "error msg"))

        with patch(
            "emergent.graph._compose.Composer.create",
            return_value=mock_composer,
        ):
            success, value = await _compose_node(UserNode, mock_scope, mock_agent_cls)
            assert success is False
            assert value is None


# ═══════════════════════════════════════════════════════════════════════════════
# resolve_handler_params
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveHandlerParams:
    @pytest.mark.asyncio
    async def test_skip_self_and_cls(self) -> None:
        """Parameters named 'self' and 'cls' are skipped."""

        async def handler(self: int, cls: str, name: str) -> None:
            pass

        mock_scope = MagicMock()
        mock_scope.retrieve = MagicMock(return_value=Some(MagicMock(value="test")))
        mock_agent_cls = DummyAgent

        with patch(
            "emergent.graph._compose.Composer.create",
        ) as mock_create:
            mock_composer = MagicMock()
            mock_composer.compose = AsyncMock(return_value=(False, "err"))
            mock_create.return_value = mock_composer

            result = await resolve_handler_params(handler, mock_scope, mock_agent_cls)

        assert "self" not in result
        assert "cls" not in result

    @pytest.mark.asyncio
    async def test_skip_unannotated_params(self) -> None:
        """Parameters without type annotations are skipped."""

        def handler(x):  # pyright: ignore[reportMissingParameterType, reportUnknownParameterType]  # intentionally unannotated for test
            pass

        mock_scope = MagicMock()
        mock_agent_cls = DummyAgent

        result = await resolve_handler_params(handler, mock_scope, mock_agent_cls)  # pyright: ignore[reportUnknownArgumentType]  # handler intentionally has unknown param type
        assert result == {}

    @pytest.mark.asyncio
    async def test_compose_node_success(self) -> None:
        """ComposeNode annotation resolves via nodnod composition."""

        async def handler(
            user: Annotated[str, ComposeNode(UserNode)],
        ) -> None:
            pass

        mock_scope = MagicMock()
        mock_agent_cls = DummyAgent

        mock_composer = MagicMock()
        mock_composer.compose = AsyncMock(return_value=(True, "user_value"))

        with patch(
            "emergent.graph._compose.Composer.create",
            return_value=mock_composer,
        ):
            result = await resolve_handler_params(handler, mock_scope, mock_agent_cls)

        assert result["user"] == "user_value"

    @pytest.mark.asyncio
    async def test_compose_node_with_map(self) -> None:
        """ComposeNode with map function transforms the value."""

        async def handler(
            user: Annotated[str, ComposeNode(UserNode, map=lambda v: f"mapped:{v}")],
        ) -> None:
            pass

        mock_scope = MagicMock()
        mock_agent_cls = DummyAgent

        mock_composer = MagicMock()
        mock_composer.compose = AsyncMock(return_value=(True, "raw"))

        with patch(
            "emergent.graph._compose.Composer.create",
            return_value=mock_composer,
        ):
            result = await resolve_handler_params(handler, mock_scope, mock_agent_cls)

        assert result["user"] == "mapped:raw"

    @pytest.mark.asyncio
    async def test_compose_node_failure_with_default(self) -> None:
        """ComposeNode fails but default is provided."""

        async def handler(
            user: Annotated[str, ComposeNode(UserNode, default="guest")],
        ) -> None:
            pass

        mock_scope = MagicMock()
        mock_agent_cls = DummyAgent

        mock_composer = MagicMock()
        mock_composer.compose = AsyncMock(return_value=(False, "error"))

        with patch(
            "emergent.graph._compose.Composer.create",
            return_value=mock_composer,
        ):
            result = await resolve_handler_params(handler, mock_scope, mock_agent_cls)

        assert result["user"] == "guest"

    @pytest.mark.asyncio
    async def test_compose_node_failure_no_default(self) -> None:
        """ComposeNode fails with no default -- param is not in result."""

        async def handler(
            user: Annotated[str, ComposeNode(UserNode)],
        ) -> None:
            pass

        mock_scope = MagicMock()
        mock_agent_cls = DummyAgent

        mock_composer = MagicMock()
        mock_composer.compose = AsyncMock(return_value=(False, "error"))

        with patch(
            "emergent.graph._compose.Composer.create",
            return_value=mock_composer,
        ):
            result = await resolve_handler_params(handler, mock_scope, mock_agent_cls)

        assert "user" not in result

    @pytest.mark.asyncio
    async def test_compose_optional_success(self) -> None:
        """ComposeOptional returns Some on success."""

        async def handler(
            config: Annotated[str, ComposeOptional(ConfigNode)],
        ) -> None:
            pass

        mock_scope = MagicMock()
        mock_agent_cls = DummyAgent

        mock_composer = MagicMock()
        mock_composer.compose = AsyncMock(return_value=(True, "config_val"))

        with patch(
            "emergent.graph._compose.Composer.create",
            return_value=mock_composer,
        ):
            result = await resolve_handler_params(handler, mock_scope, mock_agent_cls)

        assert isinstance(result["config"], Some)

    @pytest.mark.asyncio
    async def test_compose_optional_failure(self) -> None:
        """ComposeOptional returns Nothing on failure."""

        async def handler(
            config: Annotated[str, ComposeOptional(ConfigNode)],
        ) -> None:
            pass

        mock_scope = MagicMock()
        mock_agent_cls = DummyAgent

        mock_composer = MagicMock()
        mock_composer.compose = AsyncMock(return_value=(False, "error"))

        with patch(
            "emergent.graph._compose.Composer.create",
            return_value=mock_composer,
        ):
            result = await resolve_handler_params(handler, mock_scope, mock_agent_cls)

        assert isinstance(result["config"], Nothing)

    @pytest.mark.asyncio
    async def test_compose_retrieve_found(self) -> None:
        """ComposeRetrieve gets value from scope when available."""

        async def handler(
            token: Annotated[str, ComposeRetrieve(from_type=AuthToken)],
        ) -> None:
            pass

        mock_value = MagicMock()
        mock_value.value = "token_123"
        mock_scope = MagicMock()
        mock_scope.retrieve = MagicMock(return_value=Some(mock_value))
        mock_agent_cls = DummyAgent

        result = await resolve_handler_params(handler, mock_scope, mock_agent_cls)
        assert result["token"] == "token_123"

    @pytest.mark.asyncio
    async def test_compose_retrieve_not_found(self) -> None:
        """ComposeRetrieve skips param when type not in scope."""

        async def handler(
            token: Annotated[str, ComposeRetrieve(from_type=AuthToken)],
        ) -> None:
            pass

        mock_scope = MagicMock()
        mock_scope.retrieve = MagicMock(return_value=Nothing())
        mock_agent_cls = DummyAgent

        result = await resolve_handler_params(handler, mock_scope, mock_agent_cls)
        assert "token" not in result

    @pytest.mark.asyncio
    async def test_fallback_scope_retrieve(self) -> None:
        """Plain typed param resolved from scope via retrieve fallback."""

        async def handler(token: AuthToken) -> None:
            pass

        mock_value = MagicMock()
        mock_value.value = "scoped_token"
        mock_scope = MagicMock()
        mock_scope.retrieve = MagicMock(return_value=Some(mock_value))
        mock_agent_cls = DummyAgent

        result = await resolve_handler_params(handler, mock_scope, mock_agent_cls)
        assert result["token"] == "scoped_token"

    @pytest.mark.asyncio
    async def test_fallback_compose_node_when_not_in_scope(self) -> None:
        """Plain typed param not in scope triggers nodnod composition."""

        async def handler(token: AuthToken) -> None:
            pass

        mock_scope = MagicMock()
        mock_scope.retrieve = MagicMock(return_value=Nothing())
        mock_agent_cls = DummyAgent

        mock_composer = MagicMock()
        mock_composer.compose = AsyncMock(return_value=(True, "composed_token"))

        with patch(
            "emergent.graph._compose.Composer.create",
            return_value=mock_composer,
        ):
            result = await resolve_handler_params(handler, mock_scope, mock_agent_cls)

        assert result["token"] == "composed_token"

    @pytest.mark.asyncio
    async def test_fallback_compose_node_also_fails(self) -> None:
        """Plain typed param: scope fails, nodnod fails -- param omitted."""

        async def handler(token: AuthToken) -> None:
            pass

        mock_scope = MagicMock()
        mock_scope.retrieve = MagicMock(return_value=Nothing())
        mock_agent_cls = DummyAgent

        mock_composer = MagicMock()
        mock_composer.compose = AsyncMock(return_value=(False, "error"))

        with patch(
            "emergent.graph._compose.Composer.create",
            return_value=mock_composer,
        ):
            result = await resolve_handler_params(handler, mock_scope, mock_agent_cls)

        assert "token" not in result

    @pytest.mark.asyncio
    async def test_broken_type_hints_handled_gracefully(self) -> None:
        """If get_type_hints raises, function does not crash.

        With `from __future__ import annotations`, param.annotation is a string,
        not a type. So when get_type_hints fails, the parameter is gracefully
        skipped (string annotations cannot be resolved without get_type_hints).
        """

        async def handler(x: int) -> None:
            pass

        mock_scope = MagicMock()
        mock_scope.retrieve = MagicMock(return_value=Some(MagicMock(value=42)))
        mock_agent_cls = DummyAgent

        # Patch get_type_hints to raise -- should not crash
        with patch(
            "emergent.wire.compile._delegate.get_type_hints",
            side_effect=Exception("broken"),
        ):
            result = await resolve_handler_params(handler, mock_scope, mock_agent_cls)

        # With __future__ annotations, param.annotation is a string 'int'
        # which is not a type, so it's skipped gracefully
        assert isinstance(result, dict)
