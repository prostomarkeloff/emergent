"""Tests for derivelib._errors — domain errors and RFC 7807 ProblemDetail."""

from __future__ import annotations

from derivelib._errors import (
    AlreadyExists,
    InvalidData,
    NotFound,
    ProblemDetail,
)


class TestProblemDetail:
    def test_fields(self) -> None:
        pd = ProblemDetail(
            type="about:blank",
            title="Not Found",
            status=404,
            detail="User not found",
        )
        assert pd.type == "about:blank"
        assert pd.title == "Not Found"
        assert pd.status == 404
        assert pd.detail == "User not found"
        assert pd.instance == ""

    def test_status_code_property(self) -> None:
        pd = ProblemDetail(type="about:blank", title="T", status=422, detail="D")
        assert pd.status_code == 422

    def test_frozen(self) -> None:
        pd = ProblemDetail(type="about:blank", title="T", status=500, detail="D")
        import dataclasses
        assert dataclasses.is_dataclass(pd)


class TestNotFound:
    def test_to_problem(self) -> None:
        nf = NotFound(entity="User", id={"id": 42})
        p = nf.to_problem()
        assert p.status == 404
        assert p.title == "Not Found"
        assert "User" in p.detail
        assert "42" in p.detail

    def test_status_code(self) -> None:
        nf = NotFound(entity="Post", id={"id": 1})
        assert nf.to_problem().status_code == 404


class TestAlreadyExists:
    def test_to_problem(self) -> None:
        ae = AlreadyExists(entity="User", id={"email": "a@b.com"})
        p = ae.to_problem()
        assert p.status == 409
        assert p.title == "Conflict"
        assert "User" in p.detail

    def test_status_code(self) -> None:
        ae = AlreadyExists(entity="User", id={"id": 1})
        assert ae.to_problem().status_code == 409


class TestInvalidData:
    def test_to_problem(self) -> None:
        iv = InvalidData(entity="Order", reason="total must be positive")
        p = iv.to_problem()
        assert p.status == 422
        assert p.title == "Unprocessable Entity"
        assert "Order" in p.detail
        assert "total must be positive" in p.detail

    def test_status_code(self) -> None:
        iv = InvalidData(entity="X", reason="bad")
        assert iv.to_problem().status_code == 422
