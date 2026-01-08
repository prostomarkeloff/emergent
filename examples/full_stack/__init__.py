"""
Full Stack Example — Graph Parallelism Demo.

Shows WHY graphs matter:
- 4 independent data fetches run IN PARALLEL
- Framework figures out optimal execution order
- You declare dependencies, it handles the rest

Structure:
- domain.py  — Types (User, Product, Order, etc.)
- repo.py    — Repositories (simulated microservices)
- graph.py   — Order processing graph with parallel nodes
- cli.py     — Interactive CLI
- main.py    — Entry point

Run: uv run python -m examples.full_stack.main
"""
