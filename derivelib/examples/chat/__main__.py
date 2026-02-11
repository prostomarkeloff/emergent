"""Run: uv run python -m derivelib.examples.chat"""

from .app import app, fastapi_app


if __name__ == "__main__":
    import uvicorn

    from derivelib import endpoint_count
    n = endpoint_count(app)
    print(f"\n  3 entities -> {n} endpoints. AI replies automatically.\n")
    print("  # 1. create user (public)")
    print("  curl -X POST http://localhost:8000/users -H 'Content-Type: application/json' \\")
    print("       -d '{\"name\": \"Alice\"}'")
    print()
    print("  # 2. login -> get token (public)")
    print("  curl -X POST http://localhost:8000/login -H 'Content-Type: application/json' \\")
    print("       -d '{\"name\": \"Alice\"}'")
    print()
    print("  # 3. create chat (auth required)")
    print("  curl -X POST http://localhost:8000/chats \\")
    print("       -H 'Content-Type: application/json' \\")
    print("       -H 'Authorization: Bearer tok_1' \\")
    print("       -d '{\"user_id\": 1, \"title\": \"My first chat\"}'")
    print()
    print("  # 4. send message -> AI replies with suggestions (auth required)")
    print("  curl -X POST http://localhost:8000/messages \\")
    print("       -H 'Content-Type: application/json' \\")
    print("       -H 'Authorization: Bearer tok_1' \\")
    print("       -d '{\"chat_id\": 1, \"text\": \"Hello!\"}'")
    print()
    print("  # 5. list messages (public)")
    print("  curl 'http://localhost:8000/messages?chat_id=1'\n")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)
