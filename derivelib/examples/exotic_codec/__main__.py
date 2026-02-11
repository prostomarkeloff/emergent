"""Run: uv run python -m derivelib.examples.exotic_codec"""

from .app import app, fastapi_app


if __name__ == "__main__":
    import uvicorn

    from derivelib import endpoint_count
    n = endpoint_count(app)
    codecs_used: set[str] = set()
    for ep in app.endpoints:
        for exp in ep.exposures:
            codecs_used.add(type(exp.codec).__name__)

    print(f"\n  {n} endpoints, {len(codecs_used)} codec types: {', '.join(sorted(codecs_used))}")
    print("  GET  /sensors/stream → SSE event stream (ServerSentEventsCodec)")
    print("  POST /sensors        → create sensor (RequestResponseCodec)")
    print("  GET  /sensors/health → health check (ImmediateFactoryCodec)\n")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)
