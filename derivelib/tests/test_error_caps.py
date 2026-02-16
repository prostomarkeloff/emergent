"""Tests for derivelib._error_caps — error transform capabilities."""

from __future__ import annotations

from derivelib._error_caps import ERROR_CAPS, ErrorTransform, ProblemResponse
from derivelib._errors import InvalidData, NotFound, ProblemDetail


class TestErrorTransform:
    def test_converts_domain_error(self) -> None:
        transform = ErrorTransform()
        nf = NotFound(entity="User", id={"id": 1})
        result = transform.apply_response(nf)
        assert isinstance(result, ProblemDetail)
        assert result.status == 404

    def test_passthrough_non_error(self) -> None:
        transform = ErrorTransform()
        result = transform.apply_response(42)
        assert result == 42

    def test_invalid_data(self) -> None:
        transform = ErrorTransform()
        iv = InvalidData(entity="User", reason="bad email")
        result = transform.apply_response(iv)
        assert isinstance(result, ProblemDetail)
        assert result.status == 422


class TestProblemResponse:
    def test_wraps_problem_detail(self) -> None:
        pr = ProblemResponse()
        pd = ProblemDetail(
            type="about:blank", title="Not Found", status=404, detail="gone"
        )
        result = pr.apply_response(pd)
        # Should be a JSONResponse or similar
        assert hasattr(result, "status_code")
        assert result.status_code == 404

    def test_passthrough_non_problem(self) -> None:
        pr = ProblemResponse()
        result = pr.apply_response(42)
        assert result == 42


class TestErrorCaps:
    def test_tuple_of_two(self) -> None:
        assert len(ERROR_CAPS) == 2
        assert isinstance(ERROR_CAPS[0], ErrorTransform)
        assert isinstance(ERROR_CAPS[1], ProblemResponse)
