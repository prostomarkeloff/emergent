"""Legacy FastAPI notes management app.

Run:
    uvicorn examples.cross_compile.legacy_fastapi.app:app --reload

Endpoints:
    GET  /notes       - List all notes
    POST /notes       - Create a note
    GET  /notes/{id}  - Get note by ID
    DELETE /notes/{id} - Delete note
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Notes API", version="1.0.0")


# ─── In-memory storage ──────────────────────────────────────────────────────


_notes: dict[int, dict[str, str]] = {}
_next_id = 1


# ─── Models ─────────────────────────────────────────────────────────────────


class NoteCreate(BaseModel):
    title: str
    content: str


class Note(BaseModel):
    id: int
    title: str
    content: str


class NoteList(BaseModel):
    notes: list[Note]
    count: int


class Message(BaseModel):
    message: str


# ─── Endpoints ──────────────────────────────────────────────────────────────


@app.get("/notes", response_model=NoteList)
def list_notes() -> NoteList:
    """List all notes."""
    notes = [Note(id=id_, **data) for id_, data in _notes.items()]
    return NoteList(notes=notes, count=len(notes))


@app.post("/notes", response_model=Note)
def create_note(note: NoteCreate) -> Note:
    """Create a new note."""
    global _next_id
    note_id = _next_id
    _next_id += 1
    _notes[note_id] = {"title": note.title, "content": note.content}
    return Note(id=note_id, **_notes[note_id])


@app.get("/notes/{note_id}", response_model=Note)
def get_note(note_id: int) -> Note:
    """Get note by ID."""
    if note_id not in _notes:
        raise HTTPException(status_code=404, detail="Note not found")
    return Note(id=note_id, **_notes[note_id])


@app.delete("/notes/{note_id}", response_model=Message)
def delete_note(note_id: int) -> Message:
    """Delete note by ID."""
    if note_id not in _notes:
        raise HTTPException(status_code=404, detail="Note not found")
    del _notes[note_id]
    return Message(message=f"Note {note_id} deleted")
