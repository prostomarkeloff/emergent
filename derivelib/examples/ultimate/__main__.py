"""Run: cd derivelib && PYTHONPATH=src:.. uv run python -m examples.ultimate"""

from ._demo import app, fastapi_app


if __name__ == "__main__":
    import uvicorn

    from derivelib import endpoint_count
    n = endpoint_count(app)
    print(f"\n  ultimate demo: 1 entity -> {n} endpoints. boilerplate is dead.\n")
    print("  CRUD + audit + tenant + soft-delete + events + approval + import/export\n")
    print("  # create article")
    print("  curl -X POST http://localhost:8000/articles \\")
    print("       -H 'Content-Type: application/json' \\")
    print("       -H 'X-Tenant-Id: acme' \\")
    print("       -d '{\"tenant_id\":\"acme\",\"title\":\"hello\",\"body\":\"world\"}'")
    print()
    print("  # list (tenant-filtered)")
    print("  curl http://localhost:8000/articles -H 'X-Tenant-Id: acme'")
    print()
    print("  # submit for approval")
    print("  curl -X POST http://localhost:8000/articles/1/submit")
    print()
    print("  # approve")
    print("  curl -X POST http://localhost:8000/articles/1/approve")
    print()
    print("  # soft-delete")
    print("  curl -X DELETE http://localhost:8000/articles/1 -H 'X-Tenant-Id: acme'")
    print()
    print("  # bulk import")
    print('  curl -X POST http://localhost:8000/articles/import \\')
    print("       -H 'Content-Type: application/json' \\")
    print("       -d '{\"items\":[{\"tenant_id\":\"acme\",\"title\":\"a\",\"body\":\"b\"}]}'")
    print()
    print("  # bulk export")
    print("  curl http://localhost:8000/articles/export")
    print()
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)
