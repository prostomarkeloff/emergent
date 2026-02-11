"""Run: cd derivelib && PYTHONPATH=src:.. uv run python -m examples.authlib"""

from ._demo import app, fastapi_app


if __name__ == "__main__":
    import uvicorn

    from derivelib import endpoint_count
    n = endpoint_count(app)
    print(f"\n  authlib demo: 2 entities -> {n} endpoints. Identity = str (login name).\n")
    print("  # 1. create user (public)")
    print("  curl -X POST http://localhost:8000/users -H 'Content-Type: application/json' \\")
    print("       -d '{\"name\": \"alice\"}'")
    print()
    print("  # 2. login -> get token (public)")
    print("  curl -X POST http://localhost:8000/login -H 'Content-Type: application/json' \\")
    print("       -d '{\"name\": \"alice\"}'")
    print()
    print("  # 3. create post without auth -> 401")
    print("  curl -X POST http://localhost:8000/posts -H 'Content-Type: application/json' \\")
    print("       -d '{\"author\": \"alice\", \"title\": \"hi\"}'")
    print()
    print("  # 4. create post with auth -> 200 (use token from step 2)")
    print("  curl -X POST http://localhost:8000/posts -H 'Content-Type: application/json' \\")
    print("       -H 'Authorization: Bearer <TOKEN>' \\")
    print("       -d '{\"author\": \"alice\", \"title\": \"hi\"}'")
    print()
    print("  # 5. list posts (public) -> 200")
    print("  curl http://localhost:8000/posts")
    print()
    print("  # 6. login unknown -> {token: null, error: \"not found\"}")
    print("  curl -X POST http://localhost:8000/login -H 'Content-Type: application/json' \\")
    print("       -d '{\"name\": \"nobody\"}'")
    print()
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)
