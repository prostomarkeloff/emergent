# So You Want to Build an API

You've done this before.

You open a new file. You write a Pydantic model for the request. Another for the response. A handler function. A route. Then you do it again for GET. And again for list. And for update. And delete. You wire up the database. You handle 404s. Validation errors. You copy-paste the pattern from the last entity you wrote, change the field names, fix the imports, miss one, get a runtime error, fix that too.

Fifteen endpoints later, you look at your project. It works. But it's 800 lines of *plumbing* wrapping 50 lines of actual domain logic. And now the PM wants a CLI tool that does the same thing. And maybe a Telegram bot.

You sigh. You open another file.

---

emergent asks a different question: **what if the plumbing wrote itself?**

Not from templates. Not from code generation. Not from YAML. From the shape of your data — the fields you already declared, the types you already annotated. One dataclass, one decorator, and the framework *derives* everything else: endpoints, request types, response types, error handling, OpenAPI docs. All from what you already wrote.

```python
@schema_meta(http_crud("/users", UserStore))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique]
```

Six endpoints. You wrote the fields. emergent wrote everything else.

But here's the part that matters: emergent is *not* a CRUD generator. CRUD is the first thing you'll build. It's not the last. The same algebra that derives REST endpoints can derive task queues, state machines, event-sourced systems, Telegram bots — anything that can be described as "typed data compiled to a target." The framework doesn't know about your domain. It doesn't need to. It just knows how to read types and fold them through compilers.

This tutorial will take you from "I've never seen emergent" to "I can build my own derivation dialect." Each chapter builds something real, introduces one new idea, and (hopefully) makes you go "huh, that's clever" at least once.

Let's start.

---

**Install:**

```bash
uv add git+https://github.com/prostomarkeloff/emergent.git
```

**Next:** [Your First API →](01-first-api.md)
