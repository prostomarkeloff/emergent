# Bridge

Compile takes a wire Application and produces a framework artifact: `Application → FastAPI`.

Bridge does the reverse: `FastAPI → Application`.

Why would you want that? Because you have a legacy app. It works. It's in production. You're not rewriting it. But you *would* like a CLI tool that does the same things. Or a Telegram bot. Or just to get your legacy routes into the wire IR so you can mix them with new emergent endpoints.

Bridge extracts the structure. Compile projects it to a new target. Legacy app in, CLI out.

---

## The legacy app

A standard FastAPI notes app. Module-level dict for storage. Nothing special.

```python
# legacy_app.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Notes API")

_notes: dict[int, dict[str, str]] = {}
_next_id = 1

class NoteCreate(BaseModel):
    title: str
    content: str

class Note(BaseModel):
    id: int
    title: str
    content: str

@app.get("/notes")
def list_notes():
    return {"notes": [Note(id=k, **v) for k, v in _notes.items()], "count": len(_notes)}

@app.post("/notes")
def create_note(note: NoteCreate):
    global _next_id
    _notes[_next_id] = {"title": note.title, "content": note.content}
    result = Note(id=_next_id, **_notes[_next_id])
    _next_id += 1
    return result

@app.get("/notes/{note_id}")
def get_note(note_id: int):
    if note_id not in _notes:
        raise HTTPException(status_code=404, detail="Note not found")
    return Note(id=note_id, **_notes[note_id])

@app.delete("/notes/{note_id}")
def delete_note(note_id: int):
    if note_id not in _notes:
        raise HTTPException(status_code=404, detail="Note not found")
    del _notes[note_id]
    return {"message": f"Note {note_id} deleted"}
```

Vanilla FastAPI. No emergent. No wire. No `@derive`.

## Bridging to CLI

```python
# bridge.py
from emergent.wire.bridge import build_application, Extracted, WrapAsDelegate, IsolateGlobal
from emergent.wire.bridge.bridgers import AddTrigger
from emergent.wire.bridge._types import RouteData
from emergent.wire.axis.surface.triggers.cli import CLITrigger
from emergent.wire.compile.targets import cli

from legacy_app import app as fastapi_app


def build_cli_trigger(handler: Extracted[RouteData]) -> CLITrigger:
    name = handler.name or "unknown"
    parts = name.split("_")
    cli_name = f"{parts[1]}-{parts[0]}" if len(parts) == 2 else name.replace("_", "-")
    return CLITrigger(command=cli_name, description=handler.description or name)


wire_app = build_application(
    fastapi_app,
    capabilities=(
        WrapAsDelegate(),
        IsolateGlobal(
            module_path="legacy_app",
            attr_name="_notes",
            factory=create_persistent_notes,  # your factory for persistent storage
        ),
        AddTrigger(
            trigger_type=CLITrigger,
            builder=build_cli_trigger,
        ),
    ),
)

cli_parser = cli.compile(wire_app, prog="notes-cli")

if __name__ == "__main__":
    cli.cli_run(cli_parser)
```

```bash
python bridge.py notes-create "Hello" "World"
python bridge.py notes-list
python bridge.py notes-get 1
```

Your FastAPI app is now a CLI tool. No rewriting. No adapters.

## What the bridge capabilities do

**`WrapAsDelegate()`** — each FastAPI handler gets wrapped in a `DelegateCodec`. This preserves the original function signature: `def create_note(note: NoteCreate)` stays as-is. The delegate codec calls it directly instead of going through the `to_domain/from_domain` dance.

**`IsolateGlobal(...)`** — the legacy app uses `_notes = {}` at module level. That's fine for a running server (state lives in memory). It's a disaster for a CLI tool (each invocation starts fresh). `IsolateGlobal` replaces the module-level dict with a persistent store before each handler call and restores it after. Your CLI writes to disk; the data survives between invocations.

**`AddTrigger(...)`** — the extracted endpoints only have HTTP triggers (that's what FastAPI has). This adds CLI triggers to each one. The `builder` function maps handler names to CLI command names.

## The asymmetry

Bridge is lossy. A FastAPI app has middleware, dependencies, exception handlers, custom response classes — none of which have a direct wire representation. Bridge extracts what it can (routes, handlers, path params) and discards what it can't.

Compile is lossless in the other direction. A wire Application compiles to a complete framework artifact with nothing missing.

Round-trip: `bridge(compile(app)) ≈ app` (approximately recovers the original). But `compile(bridge(fastapi_app))` produces a clean version that preserves behavior but loses framework-specific implementation details.

This isn't a bug. It's the nature of the operation. Bridge is a forgetful functor — it extracts structure from a framework artifact. You can't reconstruct what it forgot. That's why bridge *capabilities* exist — they're hints that tell the extraction what to do with framework-specific patterns.

---

**Next:** [What's Next →](14-whats-next.md)
