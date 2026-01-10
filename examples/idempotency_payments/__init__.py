"""
Idempotent Payments — Production-Ready Example

This example demonstrates enterprise-grade idempotency for payment processing
using SQLAlchemy + nodnod graph.

Structure:
    domain.py     — Domain models (Order, Payment, etc.)
    db.py         — SQLAlchemy models and session factory
    store.py      — IdempotencyStore implementation for SQLAlchemy
    operations.py — Business operations (payment processing)
    main.py       — Example runner

Run:
    uv run python -m examples.idempotency_payments.main
"""
