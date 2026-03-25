# 2. Building Abstractions with Data

> We forget about what the symbols stand for. ... [The mathematician] need not be idle; there are many operations which he may carry out with these symbols, without ever having to look at the things they stand for.
>
> — Hermann Weyl, *The Mathematical Way of Thinking* (1940)

Chapter 1 introduced capabilities as the primitive: frozen dataclasses that carry facts and compile themselves through fold. We traced a single capability through multiple targets, and arrived at a crisis — `MaxLen(255)` is not an annotation but a defunctionalized decision, generating different *processes* through different folds.

But we built only simple things. A capability on a field. A list of capabilities on an entity. The artifacts were direct: a Pydantic FieldInfo, a SQLAlchemy column, a constraint record. We never asked: what happens when the artifacts themselves have structure? When one artifact depends on another, when artifacts compose into larger artifacts, and when those compositions compose further?

This is the question of *compound data*. SICP opens its second chapter with rational numbers — a value that cannot be represented by a single number but requires *two* numbers traveling together (numerator and denominator). The rest of the chapter develops what this simple need implies: the closure property, conventional interfaces, symbolic data, multiple representations, and generic operations.

emergent faces the same progression. A field with one capability is trivial. A field with *two* capabilities requires them bundled (the Annotated tuple). An entity with multiple fields requires the field compilations bundled (the FieldCompilation dict). An entity with schema-level capabilities requires those bundled with field capabilities. Endpoints bundled into applications. Applications compiled to targets. At each level, the result of combination is itself combinable. This is the closure property — and it is the engine that makes compilation scale from a single constraint to a running distributed system.

---

## 2.1 Introduction to Data Abstraction

### 2.1.1 Why Compound Data?

In Chapter 1, we compiled individual capabilities on individual fields. Each fold consumed a flat list and produced a single context. This was sufficient for understanding *how* compilation works. But it is not sufficient for building real systems.

Consider a query. "Find all users whose balance exceeds 100." This is not a single fact like `MaxLen(255)`. It is a *compound* description: a *field reference* ("balance"), a *comparison operator* ("greater than"), and a *constant value* (100). These three elements must travel together — you cannot ask "greater than" without knowing "greater than *what*" and "greater than *where*."

In SICP, Abelson and Sussman confront the same need with rational numbers. You cannot do rational arithmetic with two separate integers. You need them *paired*: make-rat, numer, denom. The rational number is the first compound datum — the gateway to everything that follows.

emergent's rational number is the *query expression*. Consider the simplest possible query:

```python
Gt(Field("balance"), Const(100))
```

Three frozen dataclasses, composed into a tree. `Field("balance")` is a leaf — a reference to a field on an entity. `Const(100)` is a leaf — a literal value. `Gt` is a binary node — it takes two child expressions and means "left is greater than right."

Before reading on, predict: what is the type of `Gt(Field("balance"), Const(100))`? It extends `Expr`, the abstract base. What is the type of `Field("balance")`? Also `Expr`. What is the type of `Const(100)`? Also `Expr`. The children of a compound expression are themselves expressions. This is the property that will dominate this chapter.

You can build more complex expressions from simpler ones:

```python
And(
    Gt(Field("balance"), Const(100)),
    Eq(Field("active"), Const(True)),
)
```

"Balance above 100 AND active is true." An `And` node whose children are themselves compound expressions. The expression is a tree — and the tree is built from the same elements at every level. This is what SICP calls the *closure property*: the result of combining expressions is itself an expression, suitable for further combination.

But why is this compound data, rather than just "nested dataclasses"? Because the expression will be *consumed by different evaluators*, just as capabilities are consumed by different folds. The same expression tree, interpreted by different backends, produces categorically different artifacts:

```python
expr = And(Gt(Field("balance"), Const(100)), Eq(Field("active"), Const(True)))

# Memory backend: Python predicate
lambda u: u.balance > 100 and u.active == True

# SQL backend: WHERE clause
WHERE balance > 100 AND active = TRUE

# HTTP backend: query parameters
?balance_gt=100&active=true
```

This should remind you of Chapter 1's crisis: `MaxLen(255)` producing `Field(max_length=255)` in Pydantic-land and `String(255)` in SQLAlchemy-land. The same frozen data, different evaluation, different result. But the expression is *compound* — it has structure that the evaluator must traverse. Capabilities were a flat list; expressions are a tree. The evaluator for trees is not a flat fold but a *recursive* fold — a catamorphism over trees rather than lists.

### 2.1.2 The Expression AST

The full expression language lives in `emergent/wire/axis/query/_expr.py`. Every node is a frozen dataclass extending the abstract `Expr` class:

```python
class Expr(ABC):
    @abstractmethod
    def evaluate(self, obj) -> Any: ...

    def children(self) -> tuple[Expr, ...]:
        return tuple(
            getattr(self, f.name)
            for f in dataclasses.fields(self)
            if isinstance(getattr(self, f.name), Expr)
        )

    def __and__(self, other): return And(self, other)
    def __or__(self, other): return Or(self, other)
    def __invert__(self): return Not(self)
```

Three things to notice.

**First**, `children()` is not abstract. It uses dataclass field introspection to find all `Expr`-typed fields automatically. A leaf node (`Field`, `Const`) has no Expr-typed fields and returns `()`. A binary node (`Eq`, `And`) returns its two children. `Between` returns three (field, low, high). The tree structure is implicit in the data — no explicit tree pointers needed.

**Second**, every node carries an `evaluate` method — the *interpreted* semantics. `Eq.evaluate(obj)` returns `self.left.evaluate(obj) == self.right.evaluate(obj)`. This is the direct evaluation: walk the tree, compute the result. It is the *simplest possible* backend — the one that needs no compilation at all.

**Third**, the operator overloads (`__and__`, `__or__`, `__invert__`) let you compose expressions with Python syntax. But the real composition mechanism is the `EntityProxy` — a proxy object that turns lambda syntax into expression trees:

```python
from emergent.wire.axis.query._proxy import EntityProxy

u = EntityProxy(User)
expr = (u.balance > 100) & (u.active == True)
# produces: And(Gt(Field("balance"), Const(100)), Eq(Field("active"), Const(True)))
```

The proxy intercepts attribute access (`u.balance` becomes `FieldProxy("balance")`), then intercepts comparison operators (`> 100` becomes `Gt(Field("balance"), Const(100))`). The lambda `lambda u: u.balance > 100` never actually *runs* as Python logic — it *builds a data structure*. The lambda is syntactic sugar for constructing a tree. The tree is the data. The data is what gets compiled.

This is Weyl's epigraph made concrete: "we forget about what the symbols stand for." The Python comparison operators `>`, `==`, `&` do not compute boolean values. They construct symbolic expressions. We have repurposed Python's evaluation to build *data that represents evaluation*.

### 2.1.3 Abstraction Barriers for Queries

The query expression system has a layered structure that separates concerns:

```
Programs that USE queries
──────────────────────────────────────────
.filter(lambda u: u.balance > 100)         Human API (proxy + lambda)
──────────────────────────────────────────
Filter(Gt(Field("balance"), Const(100)))   Query operations (relational)
──────────────────────────────────────────
Expr nodes: Gt, Field, Const, And, Or      Expression AST (symbolic)
──────────────────────────────────────────
compile_memory_query, compile_sa_query     Providers (interpreted/compiled)
```

Each layer uses the one below without knowing its implementation. The lambda author does not know about `Gt` nodes. The `Filter` operation does not know about SQL compilation. The expression AST does not know about any specific backend. Each barrier can be reimplemented independently.

This is SICP's *abstraction barrier* applied to queries. SICP draws the barrier for rational numbers: "programs that use rationals" / "rationals as numerator-denominator pairs" / "pairs as cons." Our barrier serves the same purpose — insulation between layers of abstraction.

**Exercise 2.1.** The proxy trick turns `u.balance > 100` into `Gt(Field("balance"), Const(100))`. What happens if you write `100 < u.balance`? Does Python call `__lt__` on the integer `100` or `__gt__` on the proxy? Trace through the proxy mechanism. (Hint: Python calls `__gt__` on the right operand when the left operand's `__lt__` returns `NotImplemented`.)

**Exercise 2.2.** The `children()` method uses dataclass field introspection. This means adding a new Expr node with Expr-typed fields automatically makes it traversable. What would break if `children()` were abstract and each node had to implement it manually? Consider: (a) adding a new node type, (b) forgetting to override, (c) maintaining consistency.

---

## 2.2 Hierarchical Data and the Closure Property

### 2.2.1 The Closure Property

We now develop the idea that makes compound data powerful.

Consider the operation `And(expr1, expr2)`. Both arguments are `Expr`. The result is also `Expr`. This means `And(And(a, b), c)` is valid — you can nest arbitrarily. The result of combining expressions *can itself be combined*. SICP calls this the *closure property*:

> An operation for combining data objects satisfies the closure property if the results of combining things with that operation can themselves be combined using the same operation.

The name comes from abstract algebra (a set is *closed* under an operation if the operation's result stays within the set), not from programming language closures. SICP notes the unfortunate terminological collision.

The closure property is what separates toys from tools. Without it, you can build `And(a, b)` but not `And(And(a, b), c)`. You could have flat conjunctions but not trees. You could filter by one condition but not by compound conditions. The closure property is what makes hierarchical structure possible.

emergent satisfies the closure property at *every level of its architecture*. Let us enumerate them:

**1. Expressions close over expressions.** `And(Gt(a, b), Eq(c, d))` — compound expressions are expressions. The tree grows without bound.

**2. Capabilities close over capabilities.** `Annotated[str, MaxLen(255), Unique]` — the tuple of capabilities is consumed by fold, and fold produces a context that can be consumed by another fold. Adding a capability never changes the type of the result.

**3. Phases close over phases.** `PYDANTIC_PHASE + OPENAPI_PHASE` yields a `SchemaCompiler`. `SchemaCompiler + SchemaCompiler` yields a `SchemaCompiler`. The algebra: `+` is left-biased union, `-` is subtraction, `&` is intersection, `|` is right-biased merge.

**4. Endpoints close over endpoints.** `application().mount(ep1).mount(ep2)` returns an `Application`. `Application` can be mounted into another `Application` (via stacking). Applications compose into applications.

**5. Operations close over operations.** `query.filter(f1).filter(f2).order_by(o).limit(n)` — each method returns a new `RelationalQuerySet`, which supports the same methods. Query operations compose into queries.

**6. Scopes close over scopes.** `scoped(generator, modifier1, modifier2)` produces a `Scoped` capability that is itself a `SchemaCapability`. Scoped groups can be nested.

This is not a coincidence. It is a design principle: *every combinator in emergent returns the same type it consumes*. This is what makes the system compositional in the mathematical sense — not merely "you can put things together" but "you can put together things that were themselves put together."

### 2.2.2 Representing Sequences: Query Operations

A `RelationalQuerySet` is a sequence of query operations:

```python
q = (
    relational(User)
        .filter(lambda u: u.active == True)
        .filter(lambda u: u.balance > 100)
        .order_by(lambda u: u.created_at.desc())
        .limit(50)
)
```

Each method call returns a *new* `RelationalQuerySet` with the operation appended. The query is immutable — `.filter(...)` does not modify the original. The operations are frozen dataclasses:

```python
@dataclass(frozen=True, slots=True)
class Filter:
    expr: Expr

    def compile_memory_query(self, ctx: MemoryQueryContext) -> MemoryQueryContext:
        return replace(ctx, data=[item for item in ctx.data if self.expr.evaluate(item)])

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        clause = ctx.compile_expr(self.expr)
        return replace(ctx, stmt=ctx.stmt.where(clause))
```

Notice the pattern. `Filter` is a frozen dataclass with `compile_*` methods. It is a *capability* — the same encoding we learned in Chapter 1. fold consumes it the same way: `isinstance` check, method dispatch, context accumulation. The query system is not a separate mechanism. It is *the same mechanism applied to a different domain*.

When the memory provider executes a query, it folds the operations:

```python
ctx = MemoryQueryContext(data=all_users)
ctx = fold(query.ops, ctx, MemoryQueryCompilable, "compile_memory_query")
# ctx.data is now the filtered, ordered, limited subset
```

When the SQLAlchemy provider executes the same query, it folds with a different protocol:

```python
ctx = SAQueryContext(stmt=select(User), compile_expr=sa_compile_expr)
ctx = fold(query.ops, ctx, SAQueryCompilable, "compile_sa_query")
# ctx.stmt is now: SELECT * FROM users WHERE active = TRUE AND balance > 100
#                  ORDER BY created_at DESC LIMIT 50
```

Same operations. Same fold. Different protocol. Different result. The query is a *program*. Each fold is a different *evaluation* of that program. The memory fold interprets it immediately (filtering a Python list). The SQL fold compiles it to a SQL statement (building a query string). The closure property guarantees that any sequence of operations is itself a valid input to the fold.

Before reading on, predict: what does the HTTP API provider do with the same query? The answer is not "execute it against a database." The HTTP provider compiles the query to *URL parameters*:

```python
ctx = HTTPAPIContext(params={}, encode_filter=http_encode)
ctx = fold(query.ops, ctx, HTTPAPICompilable, "compile_http_api")
# ctx.params = {"active": "true", "balance_gt": "100",
#               "order": "-created_at", "limit": "50"}
```

Three categorically different artifacts from one query: a filtered Python list, a SQL statement, a set of URL parameters. The query description is more fundamental than any of its compilations.

### 2.2.3 Representing Trees: Expression Compilation

Sequences (flat lists of operations) are compiled by the flat fold from Chapter 1. But expressions are *trees*. `And(Gt(Field("balance"), Const(100)), Eq(Field("active"), Const(True)))` has internal structure — children, grandchildren, recursion. How do we compile a tree?

The answer is `fold_expr` — the tree analog of fold:

```python
def fold_expr(expr, handlers, *, default=None):
    def recurse(node):
        handler = handlers.get(type(node))
        if handler is not None:
            return handler(node, recurse)
        if default is not None:
            return default(node, recurse)
        raise TypeError(f"No handler for {type(node).__name__}")
    return recurse(expr)
```

Same structure as flat fold: dispatch by type, call the handler, accumulate the result. But with a critical difference: each handler receives a `recurse` function that applies the same dispatch to child nodes. The recursion follows the tree structure. The handler controls *what to do at each node*. The fold controls *how to traverse*.

This is Meijer's catamorphism generalized from lists to trees. On lists, the catamorphism processes head-then-tail. On trees, it processes node-then-children. The algebraic structure is the same — a unique structurally recursive consumer of the data type.

The `algebra.py` example makes this concrete. Expression nodes (Num, Sym, Add, Mul, etc.) are frozen dataclasses. Each node compiles itself for multiple targets — Python source, LaTeX, evaluation, symbolic differentiation. The compilation driver builds a context that carries the recursive `compile_expr` closure:

```python
def compile_python(expr):
    def _compile(e):
        ctx = PythonCtx(result="", compile_expr=_compile)
        result = fold([e], ctx, PythonCompilable, "compile_python")
        return result.result
    return _compile(expr)
```

The context carries `compile_expr = _compile` — a reference to the compilation function itself. When `Add.compile_python` needs to compile its children, it calls `ctx.compile_expr(self.left)` and `ctx.compile_expr(self.right)`. The recursion is threaded through the context, not hardcoded in the node.

Let us trace the compilation of `Add(Num(2), Mul(Sym("x"), Num(3)))` — the expression `2 + x * 3`.

**Step 1:** `compile_python(Add(Num(2), Mul(Sym("x"), Num(3))))` calls `_compile(Add(...))`.

**Step 2:** `_compile` creates `PythonCtx(result="", compile_expr=_compile)` and calls `fold([Add(...)], ctx, PythonCompilable, "compile_python")`.

**Step 3:** fold dispatches to `Add.compile_python`. Inside:
```python
left_str = ctx.compile_expr(self.left)   # _compile(Num(2))
right_str = ctx.compile_expr(self.right)  # _compile(Mul(Sym("x"), Num(3)))
return replace(ctx, result=f"({left_str} + {right_str})")
```

**Step 4:** `_compile(Num(2))` dispatches to `Num.compile_python` which returns `"2"`.

**Step 5:** `_compile(Mul(Sym("x"), Num(3)))` dispatches to `Mul.compile_python`:
```python
left_str = ctx.compile_expr(self.left)   # _compile(Sym("x")) returns "x"
right_str = ctx.compile_expr(self.right)  # _compile(Num(3)) returns "3"
return replace(ctx, result="x * 3")
```

**Step 6:** Back in Step 3, `left_str = "2"`, `right_str = "x * 3"`. Result: `"(2 + x * 3)"`.

Now predict: what does the same expression produce when compiled through `compile_latex`?

```
(2 + x \cdot 3)
```

The tree structure is identical. Only the format strings change — `+` stays `+`, `*` becomes `\cdot`, fractions use `\frac{}{}`. Same tree, different fold, different output. The closure property of expressions guarantees that any sub-expression can be compiled by the same mechanism.

**Exercise 2.3.** Trace the compilation of `Mul(Add(Sym("x"), Num(1)), Add(Sym("x"), Num(-1)))` (i.e., `(x + 1)(x - 1)`) through `compile_python` and `compile_latex`. Then trace the same expression through `compile_eval` with `env = {"x": 5}`. Verify that the Python code, when evaluated, gives the same answer as `compile_eval`.

**Exercise 2.4.** The context carries `compile_expr` as a field. This means a handler could *replace* the recursive function with a different one — say, one that simplifies before recursing. Design such a "simplifying compiler": a `compile_python` variant that calls `simplify(child)` before `_compile(child)`. What are the trade-offs of weaving simplification into the compiler versus running it as a separate pass?

### 2.2.4 Conventional Interfaces

SICP 2.2.3 identifies `map`, `filter`, and `accumulate` as *conventional interfaces* — standard patterns for processing sequences that allow modules to be combined. The insight: programs that look different (sum-odd-squares, even-fibs) share the same signal-flow structure when expressed with conventional interfaces.

emergent has *two* conventional interfaces:

1. **fold** — the linear conventional interface. Consumes a flat sequence of capabilities, accumulates a context. This is Chapter 1's primitive.

2. **fold_expr** — the tree conventional interface. Consumes a tree of expressions, dispatches by node type, recurses into children. This is the tree catamorphism.

`map` is fold that transforms each element. `filter` is fold with open-world skip. `accumulate` is fold itself. The banana split theorem (Chapter 1, Section 1.2.3) formalizes why multiple independent folds over the same list fuse into one pass: phases are independent, so the inner loop iterates phases while the outer loop iterates fields.

But fold_expr adds something fold cannot express: *structure-dependent recursion*. When `Add.compile_python` calls `ctx.compile_expr(self.left)`, it is following the tree's structure. The recursion pattern is dictated by the data, not by the programmer. This is the mathematical content of catamorphisms: the recursion scheme is *determined by the data type*.

The two interfaces together cover all compilation in emergent:

| Data shape | Interface | Example |
|-----------|-----------|---------|
| Flat list of capabilities | fold | Schema compilation, derive phases |
| Tree of expressions | fold_expr | Query compilation, algebra compilation |
| Flat list of query ops | fold | Memory/SQL/HTTP query execution |
| Flat list of pipeline steps | fold | Request/response pipeline |

The uniformity is the point. Any new compilation domain — a new query backend, a new expression language, a new pipeline step — plugs into one of these two interfaces. No new mechanism is needed.

### 2.2.5 The Derive Language: A Picture Language for Endpoints

SICP 2.2.4 presents a *picture language* where painters compose into painters. `beside(wave, flip-vert(wave))` takes two painters, combines them, and returns a painter. The result is a painter — the closure property. The picture language demonstrates stratified design: primitives, combinators, and abstractions layered atop one another.

emergent's derive system is its picture language. The "painters" are schema capabilities. The "canvas" is the DeriveCtx. The "painting" is a set of endpoints.

**Primitive painters** — capabilities that *generate* structure:

```python
http_crud("/users", provider_node=Users)
# Generates 6 OpSpecs: List, Get, Create, Update, Patch, Delete
```

**Combinators** — capabilities that *transform* structure:

```python
Paginated(20)      # Replaces List handler with paginated version
Readonly()         # Removes all mutation ops
SoftDelete("d")    # Replaces hard delete with soft delete
Sorted()           # Adds sorting support to List
```

**Abstractions** — named compositions of primitives and combinators:

```python
scoped(
    http_crud("/users", Users),
    Paginated(20),
    Readonly(),
)
```

`scoped` takes a generator and zero or more modifiers, returns a `Scoped` capability — which is itself a `SchemaCapability`. Scoped groups can be composed with other scoped groups:

```python
@derive(
    scoped(
        http_crud("/users", Users),
        Paginated(20),
        Readonly(),
    ),
    scoped(
        http_crud("/admin/users", Users),
        Authenticated(BearerExtract(), TokenValidate(AuthUser, lookup)),
    ),
)
```

This is SICP's picture language. Each `scoped(...)` is a "painter." `@derive(painter1, painter2)` is `beside(painter1, painter2)`. The result — a set of endpoints — is the "picture." And the closure property holds: any composition of capabilities is itself a capability, suitable for further composition.

SICP draws the crucial lesson:

> A complex system should be structured as a sequence of levels that are described using a sequence of languages. Each level is constructed by combining parts that are regarded as primitive at that level, and the parts constructed at each level are used as primitives at the next level.

emergent's five stratification levels:

| Level | Language | Primitives | Combinators | Produces |
|-------|----------|------------|-------------|----------|
| 1. Capability | `MaxLen(255)`, `Unique`, `Identity` | Frozen dataclasses | `Annotated[T, ...]` | Field constraints |
| 2. Schema | `SchemaCompiler`, `CompilationPhase` | Phases | `+`, `-`, `&`, `\|` | Compiled models |
| 3. Derive | `http_crud(...)`, `Paginated(...)` | OpSpecs | `scoped(...)`, `@derive(...)` | Endpoints |
| 4. Application | `endpoint(...)`, `application()` | Endpoints | `.mount(...)` | Application |
| 5. Target | `fastapi_compile(...)`, `cli_compile(...)` | Applications | Target compilers | Running program |

Changes at one level do not affect other levels. Adding `MaxLen(128)` to a field (Level 1) does not change the derive structure (Level 3) or the application topology (Level 4). Adding a new endpoint (Level 3) does not change existing field constraints (Level 1). This is SICP's "robust design" — each level absorbs changes locally.

**Exercise 2.5.** In SICP's picture language, `rotate180(painter)` applies a transformation to a painter, producing a new painter. What is the emergent analog? Design a capability `PrefixRoutes(prefix)` that takes all endpoints produced by a generator and adds a URL prefix. Where in the three-phase derive pipeline would it execute? Which protocol would it implement?

**Exercise 2.6.** The SchemaCompiler algebra has `+`, `-`, `&`, `|`. The expression algebra has `&`, `|`, `~`. Both are closed under their operations. Are there other algebraic laws that hold? Does `A + B == B + A` for SchemaCompiler? Does `e1 & e2 == e2 & e1` for expressions? What is the identity element for each?

---

## 2.3 Symbolic Data

### 2.3.1 Expressions as Data

We now confront a theme that Weyl's epigraph anticipated. In Section 2.1, we built expressions from proxy objects: `u.balance > 100` produced `Gt(Field("balance"), Const(100))`. We noted that the comparison operator was repurposed — instead of computing a boolean, it *built a data structure*.

This is the idea of *symbolic data*: data that represents *expressions*, not values. The expression `Gt(Field("balance"), Const(100))` does not tell you whether any specific user's balance exceeds 100. It is a *description* of that question — a symbolic representation that can be interpreted, compiled, simplified, serialized, and inspected without ever answering the question.

SICP introduces symbolic data through quotation: `(quote (+ 1 2))` is not 3, it is the *list* containing the symbol `+`, the number `1`, and the number `2`. Data that represents code. emergent achieves the same thing through frozen dataclasses: `Gt(Field("balance"), Const(100))` is not a boolean, it is the *tree* containing the node `Gt`, the field reference `"balance"`, and the constant `100`. Data that represents a query.

The full expression vocabulary:

- **Leaf nodes:** `Field(name)`, `Const(value)`
- **Comparison:** `Eq`, `Ne`, `Lt`, `Le`, `Gt`, `Ge`
- **Logical:** `And`, `Or`, `Not`
- **Collection:** `In`, `Contains`, `StartsWith`, `EndsWith`
- **Null checks:** `IsNull`, `IsNotNull`
- **Range:** `Between`
- **Pattern:** `Like`, `ILike`, `Regex`
- **Array:** `ArrayContains`, `ArrayAny`, `ArrayAll`, `ArrayOverlap`
- **JSON:** `JsonExtract`, `JsonContains`, `JsonHasKey`

Twenty-six node types. Every one a frozen dataclass. Every one carrying an `evaluate` method for direct interpretation. Every one composable with logical operators. The expression AST is a *language* — a language for describing queries, just as SICP's symbolic expressions are a language for describing computations.

And like any language, it can be processed by different interpreters.

### 2.3.2 Symbolic Differentiation — A Parallel

SICP 2.3.2 is one of the most celebrated sections in computer science education. It presents *symbolic differentiation*: a program that takes an expression and produces a new expression — the mathematical derivative. The expression `ax^2 + bx + c` becomes `2ax + b`. The key insight: the derivative of a sum is the sum of the derivatives. The derivative of a product uses the product rule. Each rule reduces a complex expression to simpler ones.

SICP's simplification rules are the real gem. The raw derivative of `x + 3` with respect to `x` is `(+ 1 0)`. Unreduced but correct. The simplification rules clean it up: `(+ a 0) -> a`, `(* a 1) -> a`, `(* a 0) -> 0`. The simplified result is `1`.

emergent has the exact same structure in `_simplify.py`. The domain is different — boolean algebra instead of calculus — but the technique is identical: *algebraic rewriting on frozen expression trees*.

Here is the simplifier:

```python
def simplify_expr(expr: Expr) -> Expr:
    match expr:
        case And(left=left, right=right):
            left_s = simplify_expr(left)
            right_s = simplify_expr(right)
            if _is_true(right_s):  return left_s       # And(x, True) -> x
            if _is_true(left_s):   return right_s       # And(True, x) -> x
            if _is_false(left_s) or _is_false(right_s):
                return Const(False)                      # And(x, False) -> False
            if left_s == right_s:  return left_s         # And(x, x) -> x
            if left_s is not left or right_s is not right:
                return And(left_s, right_s)
            return expr

        case Or(left=left, right=right):
            left_s = simplify_expr(left)
            right_s = simplify_expr(right)
            if _is_true(left_s) or _is_true(right_s):
                return Const(True)                       # Or(x, True) -> True
            if _is_false(right_s): return left_s         # Or(x, False) -> x
            if _is_false(left_s):  return right_s        # Or(False, x) -> x
            if left_s == right_s:  return left_s         # Or(x, x) -> x
            if left_s is not left or right_s is not right:
                return Or(left_s, right_s)
            return expr

        case Not(operand=operand):
            inner = simplify_expr(operand)
            if isinstance(inner, Not): return inner.operand  # Not(Not(x)) -> x
            if _is_true(inner):  return Const(False)         # Not(True) -> False
            if _is_false(inner): return Const(True)          # Not(False) -> True
            if inner is not operand: return Not(inner)
            return expr

        case _:
            return _simplify_children(expr)
```

Let us trace a simplification step by step. Start with:

```python
And(
    Eq(Field("active"), Const(True)),
    And(Gt(Field("balance"), Const(100)), Const(True))
)
```

**Step 1:** Match outer `And`. Simplify left: `Eq(Field("active"), Const(True))` — no simplification applies (it is a comparison, not a logical op). `left_s` unchanged.

**Step 2:** Simplify right: `And(Gt(Field("balance"), Const(100)), Const(True))`. Inner match on `And`:
- left_s = `Gt(Field("balance"), Const(100))` — comparison, no simplification.
- right_s = `Const(True)` — leaf, unchanged.
- `_is_true(right_s)` is True. Rule fires: `And(x, True) -> x`.
- Returns `Gt(Field("balance"), Const(100))`.

**Step 3:** Back in outer And: left = `Eq(Field("active"), Const(True))`, right = `Gt(Field("balance"), Const(100))`. Right changed from original, so return `And(Eq(...), Gt(...))`.

The redundant `Const(True)` is eliminated. The simplified tree is smaller, semantically equivalent, and when compiled to SQL, produces a cleaner WHERE clause.

Compare SICP's simplification rules with emergent's side by side:

| SICP (arithmetic) | emergent (boolean) | Algebraic law |
|---|---|---|
| `(+ a 0) -> a` | `And(x, True) -> x` | Identity element |
| `(* a 0) -> 0` | `And(x, False) -> False` | Annihilation |
| `(* a 1) -> a` | `Or(x, False) -> x` | Identity element |
| `(+ a a) -> (* 2 a)` | `And(x, x) -> x` | Idempotence |
| `(- a a) -> 0` | `Or(x, x) -> x` | Idempotence |
| `(- (- a)) -> a` | `Not(Not(x)) -> x` | Double negation / involution |

The technique is structurally identical: pattern-match on the expression tree, check for algebraically trivial cases, recursively simplify children. Both are catamorphisms over the expression AST. Both operate on frozen data structures. Both produce new frozen data structures. Neither mutates anything.

The `algebra.py` example extends this to calculus. The derivative rules are:

```python
# d/dx c = 0
Num.compile_deriv = lambda self, ctx: replace(ctx, result=Num(0))

# d/dx x = 1, d/dx y = 0 (if y != x)
Sym.compile_deriv = lambda self, ctx: replace(
    ctx, result=Num(1) if self.name == ctx.var else Num(0)
)

# d/dx (f + g) = df + dg  (sum rule)
Add.compile_deriv = lambda self, ctx: replace(
    ctx, result=ctx.compile_expr(self.left) + ctx.compile_expr(self.right)
)

# d/dx (f * g) = f * dg + df * g  (product rule)
Mul.compile_deriv = lambda self, ctx: replace(ctx, result=(
    ctx.compile_expr(self.left) * self.right
    + self.left * ctx.compile_expr(self.right)
))

# d/dx (f^n) = n * f^(n-1) * df  (power rule)
Pw.compile_deriv = lambda self, ctx: replace(ctx, result=(
    self.exponent * (self.base ** (self.exponent - 1))
    * ctx.compile_expr(self.base)
))
```

Let us trace the derivative of `x**2 + 2*x + 1` with respect to `x`. The expression tree is `Add(Add(Pw(Sym("x"), Num(2)), Mul(Num(2), Sym("x"))), Num(1))`.

The outer `Add` applies the sum rule: d/dx(left) + d/dx(right).

- d/dx(`Num(1)`) = `Num(0)` (constant rule)
- d/dx(`Add(Pw(x, 2), Mul(2, x))`) = sum rule again:
  - d/dx(`Pw(x, 2)`) = power rule: `2 * x^1 * 1` = `Mul(Num(2), Sym("x"))`
  - d/dx(`Mul(2, x)`) = product rule: `0 * x + 2 * 1` = `Add(Mul(Num(0), Sym("x")), Mul(Num(2), Num(1)))`

Raw result: `Add(Add(Mul(Num(2), Sym("x")), Add(Mul(Num(0), Sym("x")), Mul(Num(2), Num(1)))), Num(0))`.

Simplification cleans up the `Num(0)` and `Mul(Num(1), ...)` terms. Final simplified: `Add(Mul(Num(2), Sym("x")), Num(2))` — that is, `2x + 2`. Correct.

The compiled derivative *is itself an expression*. You can differentiate it again (`compile_deriv(d, "x")` gives `Num(2)` — the second derivative). You can compile it to Python, to LaTeX, to an evaluator. The derivative of data is data. The map is the territory.

**Exercise 2.7.** Trace the simplification of `Or(And(Field("a"), Const(True)), Const(False))` step by step. How many rule applications are needed? What is the final expression?

**Exercise 2.8.** SICP Exercise 2.56 asks the reader to extend the differentiator with the power rule. The algebra.py example already has it. Extend the *simplifier* instead: add rules `Pw(x, Num(1)) -> x` and `Pw(x, Num(0)) -> Num(1)`. Where in the `simplify` function would these rules go?

**Exercise 2.9.** SICP 2.3.2 notes that the simplifier's "intelligence" is limited — it does not simplify `(x + 0 + 0)` in one pass because the outer `+` sees `(+ (+ x 0) 0)`, not `(+ x 0 0)`. The same limitation exists in emergent's simplifier. Design a `flatten_and` function that rewrites `And(And(a, b), c)` to a flat list `[a, b, c]`, simplifies each element, removes all `Const(True)` values, and rebuilds the And tree. (Hint: the real `_simplify.py` has `flatten_and` and `unflatten_and` for exactly this purpose.)

---

## 2.4 Multiple Representations for Abstract Data

### 2.4.1 The Problem of Representation

We have been building compound data — expressions, queries, operations — and compiling them through fold. But we have been working within single domains: expressions within the query axis, operations within the derive axis. The real power of emergent — and the real crisis of this chapter — emerges when we consider how a *single entity* passes through *multiple axes simultaneously*.

Consider User:

```python
@derive(http_crud("/users", provider_node=Users), Paginated(20))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique, MaxLen(255)]
```

In Chapter 1, we traced the field-level compilation: `MaxLen(255)` through Pydantic, OpenAPI, SQLAlchemy. In this chapter, we traced query expressions through memory, SQL, HTTP. But User is not compiled by one axis in isolation. User passes through *all* axes:

1. **Schema axis** — field capabilities compiled to Pydantic models, OpenAPI schemas, SQLAlchemy columns, constraints
2. **Derive axis** — `http_crud` generates OpSpecs, `Paginated` modifies them, materialization produces types and handlers
3. **Surface axis** — endpoints with triggers, codecs, capabilities mounted into an Application
4. **Query axis** — `RelationalQuerySet` operations compiled to memory/SQL/HTTP backends

Four axes. Dozens of folds. One entity. And here is where the model that Chapter 1 established — "same data, different fold, different result" — proves insufficient.

SICP 2.4 opens with the same insufficiency. Abelson and Sussman present complex numbers. Ben Bitdiddle implements them in rectangular form (real + imaginary parts). Alyssa P. Hacker implements them in polar form (magnitude + angle). Both representations are correct. Both compute the same results. But they are *different programs*.

The question is: what happens when a system needs *both*?

### 2.4.2 Tagged Data and Protocol Dispatch

SICP's first solution is *tagged data*: attach a type tag ('rectangular or 'polar) to each complex number, then dispatch based on the tag. This works but is fragile — every operation must know about every representation.

emergent's fold already solves this. The "type tag" is the Python class. The "dispatch" is `isinstance`. When fold encounters a capability, it checks whether the capability implements the target protocol. If yes, it calls the method. If no, it skips. The capability carries its own "tag" (its type) and its own "operations" (its methods). There is no central dispatch table.

But the real parallel is deeper. SICP's crisis is not about dispatch *mechanics*. It is about *independent development*. Ben builds rectangular. Alyssa builds polar. Neither knows about the other. The system must accommodate both *without modification*.

emergent faces the same situation. Consider two teams building query providers independently:

**Team A** builds a memory provider. It processes queries by iterating a Python list:
```python
def compile_memory_query(self, ctx: MemoryQueryContext) -> MemoryQueryContext:
    return replace(ctx, data=[item for item in ctx.data if self.expr.evaluate(item)])
```

**Team B** builds a SQL provider. It processes the same queries by building SQL clauses:
```python
def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
    clause = ctx.compile_expr(self.expr)
    return replace(ctx, stmt=ctx.stmt.where(clause))
```

Neither team knows about the other. Team A's memory provider cannot compile to SQL. Team B's SQL provider cannot filter Python lists. But both teams implement methods on the *same* `Filter` class, using *different* protocols. When a new team arrives — say, Team C building an HTTP provider — they add `compile_http_api` to `Filter`. No existing code changes. Team A's memory provider is unaffected. Team B's SQL provider is unaffected.

This is the resolution of SICP's crisis, but through *protocols* instead of through tagged data or a central dispatch table. The capability is the meeting point. It carries all representations. fold selects the one matching its protocol.

SICP 2.4.3 calls this *message passing*: "intelligent data objects that dispatch on operation names." The capability IS the intelligent data object. The method name (`"compile_memory_query"`, `"compile_sa_query"`) IS the operation name. fold IS the generic dispatch.

### 2.4.3 The Expression Problem

SICP Exercise 2.76 asks a question that has become one of the deepest in programming language theory:

> Which organization would be most appropriate for a system in which new types must often be added? For a system in which new operations must often be added?

This is the *Expression Problem*, named by Philip Wadler in 1998. Data-directed programming makes it easy to add new operations (add a row to the table) but hard to add new types (must modify every operation). Message-passing makes it easy to add new types (add a new data object with all methods) but hard to add new operations (must modify every data object).

emergent chose message-passing. Capabilities carry their own `compile_*` methods. Adding a new capability (a new "type") is trivial: define a frozen dataclass with the relevant methods. No existing code changes. But adding a new compilation target (a new "operation") requires adding a new method to every relevant capability.

Why this choice? Because in emergent's domain, *new capabilities are added far more often than new targets*. A user might define dozens of custom capabilities (`Sensitive`, `Encrypted`, `Deprecated`, `RateLimited`) but will rarely add a new compilation target (FastAPI, CLI, Telegram — the list is short and stable). The Expression Problem is biased by usage patterns, and emergent's bias is correct for its domain.

But emergent adds a twist that dissolves the problem further: the *open-world property*. When fold encounters a capability that does not implement the target protocol, it *skips* it. A new capability that only implements `compile_pydantic` works immediately in Pydantic folds and is silently ignored by SQL folds. You do not need to implement *all* compile methods — only the ones relevant to your domain. This is not a full solution to the Expression Problem in the theoretical sense (you still cannot add a new target without modifying capabilities that want to participate in it). But in practice, it means *most* capabilities need only *a few* methods, and the rest are gracefully absent.

Swierstra (2008) formalized this as *Data Types a la Carte*: expression functors composed via coproducts, algebras as type classes, fold as the universal consumer. emergent achieves the same extensibility through a simpler mechanism — frozen dataclasses with protocol dispatch on a flat list. Swierstra needs free monads and coproduct functors because Haskell expressions are recursive trees. emergent's capabilities are a flat tuple, so the free monoid (tuple concatenation) suffices. The algebraic content is the same; the encoding is simpler.

**Exercise 2.10.** Per SICP Exercise 2.76: design a scenario where emergent's message-passing organization is *wrong* — where it would be better to have a centralized dispatch table. What would the domain look like? (Hint: consider a system where new targets are added weekly but capabilities are fixed.)

**Exercise 2.11.** Swierstra's coproduct composes expression types: `Val :+: Add :+: Mul`. emergent's capability tuple does the same: `(MaxLen(255), Unique, Identity)`. But Swierstra's composition is *typed* (the coproduct is a type-level operator), while emergent's is *untyped* (any capability can go in any tuple). What does emergent lose by not having typed composition? What does it gain? Consider verification: can emergent catch "incompatible capabilities" at import time?

---

## 2.5 Systems with Generic Operations

### 2.5.1 The Crisis: Compilation IS the Semantics

We are now in a position to confront the central crisis of this chapter.

In Chapter 1, the crisis was: capabilities are not annotations — they are defunctionalized decisions that generate different processes through different folds. The reader learned that `MaxLen(255)` is the *meaning*, and fold is the *evaluator*.

The Chapter 2 crisis goes deeper. Consider what happens when we compile one User entity to three different targets:

```python
app = build_application_from_decorated(User)

# Target 1: FastAPI
fastapi_app = targets.fastapi.compile(app, axes)

# Target 2: CLI
cli_parser = targets.cli.compile(app, axes)

# Target 3: Telegram
tg_dispatch = targets.telegrinder.compile(app, axes)
```

Three function calls. Three completely different programs.

The FastAPI app is an HTTP server. It has routes (`GET /users`, `POST /users`, `GET /users/{id}`, ...), Pydantic models for request validation, OpenAPI documentation, async request handlers, middleware chains, exception handlers. It imports `fastapi`, `starlette`, `pydantic`, `uvicorn`. It runs as a long-lived process listening on a port.

The CLI parser is a command-line tool. It has subcommands (`users list`, `users get`, `users create`, ...), argparse argument specs, synchronous handlers that print to stdout. It imports `argparse`. It runs once, prints a result, and exits.

The Telegram bot is an event-driven system. It has command handlers (`/users`, `/start`), message parsers, inline keyboards, polling loops. It imports `telegrinder`. It runs as a long-lived process polling the Telegram API.

These three programs share *no runtime code*. The FastAPI app does not import argparse. The CLI tool does not import starlette. The Telegram bot does not import either. They have different dependency trees, different execution models, different error handling strategies, different I/O patterns. They are not "the same program in three formats." They are *three different programs*.

And yet they all came from the same source:

```python
@derive(http_crud("/users", provider_node=Users), Paginated(20))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique, MaxLen(255)]
```

Eleven lines. Three categorically different programs.

Now consider what `MaxLen(255)` means in each:

| Target | What MaxLen(255) *becomes* | When it runs |
|--------|--------------------------|-------------|
| FastAPI | `Field(max_length=255)` on a Pydantic model | Every HTTP request |
| FastAPI (docs) | `{"maxLength": 255}` in OpenAPI schema | Design time (Swagger UI) |
| SQLAlchemy | `Column(String(255))` | Migration time |
| CLI | `help="(max 255 chars)"` in argparse | When user runs `--help` |
| Verification | `max_length=255` in constraint ctx | Import time |

Five different artifacts. Five different runtimes. Five different *meanings*. `MaxLen(255)` does not have a single meaning. Its meaning is determined by which fold evaluates it. The fold is not "reading" a fixed meaning — the fold is *creating* the meaning.

This is the crisis.

In Chapter 1, we said: "the protocol determines the semantics." But the full implication is this: *there is no meaning apart from compilation*. `MaxLen(255)` in isolation — without any fold — is just a frozen dataclass with one field. It means nothing. It becomes meaningful only when a fold consumes it. Different folds, different meanings. No fold is privileged. There is no "true" interpretation of `MaxLen(255)` that the others approximate.

SICP arrives at the same insight through complex numbers. Ben's rectangular representation and Alyssa's polar representation are not "views of the same thing." They are different concrete objects that happen to satisfy the same abstract interface. You can convert between them, but neither is more fundamental.

But emergent pushes past SICP. Ben's rectangular and Alyssa's polar can be interconverted — `z = r * e^(i*theta)` translates between forms. There is an *isomorphism*. A FastAPI app and an argparse parser do not look isomorphic — they are *different things* generated from a common source. But emergent goes further: the `wire.bridge` module provides the inverse of compilation.

`compile` is the forward direction: `Application → Framework`. `bridge` is the inverse: `Framework → Application`. Given a FastAPI app, you can recover the wire Application and cross-compile it to a CLI parser:

```python
from emergent.wire.bridge import build_application
from emergent.wire.compile import cli_compile

# OUT: Application → FastAPI (compilation)
fastapi_app = http_compile(wire_app, axes)

# IN: FastAPI → Application (bridge)
recovered_app = build_application(fastapi_app)

# OUT again: Application → CLI (cross-compilation)
cli_parser = cli_compile(recovered_app, compile_axes)
```

This is a round trip. The capability description survives it. What is lost in any single projection — the full structure, the metadata, the other targets — is preserved in the wire Application that bridge recovers. You can prove this: compile to FastAPI, bridge back, compile to CLI. You get the same CLI you would have gotten by compiling directly.

The common source — the capability description — is more fundamental than any of its compilations. The description *is* the program. Any specific target is one *projection* of the program into a particular runtime. Bridge recovers the source from the projection. The concept of "the program" does not live in any one runtime. It lives in the capabilities.

This is what "compilation IS the semantics" means — and bridge makes the claim stronger, not weaker. The capabilities are not descriptions of a program that exists somewhere else. They *are* the program. Compilation does not translate — it *creates*. And bridge proves it: if you can recover the program from any one of its projections, the projections contain the program. The round trip closes.

### 2.5.2 The Dispatch Table

SICP 2.5 presents the operation-type table — a two-dimensional table with operations on one axis and types on the other. Each cell contains a specific implementation. `(put 'real-part '(rectangular) real-part-rectangular)` installs an implementation at coordinates (real-part, rectangular). `apply-generic` looks up the table at runtime.

emergent's capabilities form the same table — but distributed across capability classes instead of centralized in a mutable registry:

```
                   | PydanticCompilable  | OpenAPICompilable  | SQLAlchemyCompilable | ArgparseCompilable
-------------------+---------------------+--------------------+----------------------+-------------------
MaxLen(255)        | compile_pydantic    | compile_openapi    | compile_sqlalchemy   | compile_argparse
Identity           | --                  | --                 | compile_sqlalchemy   | --
Unique             | --                  | --                 | compile_sqlalchemy   | --
Min(0)             | compile_pydantic    | compile_openapi    | --                   | compile_argparse
Ref(User)          | --                  | --                 | compile_sqlalchemy   | --
```

This IS SICP Figure 2.22. Each row is a capability (a "type" in SICP's vocabulary). Each column is a compilation target (an "operation" in SICP's vocabulary). Each cell is a `compile_*` method (a specific implementation). The `--` cells are the open-world skips.

SICP installs entries with `(put op type procedure)` — a mutation of a global table. emergent installs entries by *defining a class with methods* — at definition time, immutably. SICP retrieves entries with `(get op type)`. emergent retrieves entries with `isinstance(item, protocol)` and `getattr(item, method)`.

The structural difference: SICP's table is *mutable and centralized*. emergent's table is *immutable and distributed*. There is no global registry. Each capability carries its own row. fold reads the row at dispatch time. This means:

1. **No installation step.** Defining a capability class automatically populates the table.
2. **No mutation.** The table cannot be modified after definition. There is no `(put ...)` that overwrites an entry.
3. **No coordination.** Teams can define capabilities independently. Their rows coexist in any fold.

And crucially: fold does not need to know the table's dimensions. It iterates capabilities, checks isinstance, calls the method if found. A capability with ten compile methods and a capability with one compile method are processed identically. The table's sparsity (the `--` cells) is handled by the skip, not by explicit null entries.

### 2.5.3 Five Folds from One Declaration

We can now trace the full compilation path for one User entity. This is the culminating example — emergent's analog of SICP 2.5's generic arithmetic package that combines rational, complex-rectangular, complex-polar, and ordinary arithmetic into one dispatch system.

```python
@derive(http_crud("/users", provider_node=Users), Paginated(20))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    email: Annotated[str, Unique, MaxLen(255)]
```

**Fold 1: Schema compilation (field-level).**

`SchemaCompiler.compile(User, axes)` iterates each field. For each field and each phase, it calls `fold_field`. The capabilities on `email` — `(MaxLen(255), Unique)` — are folded through Pydantic, OpenAPI, SQLAlchemy, and Constraints phases. Nine dispatch decisions per field (3 fields x 3 capabilities including empty sets). Result: a `FieldCompilation` dict for each field.

**Fold 2: Derive compilation (schema-level, three sub-folds).**

`compile_derive(User)` retrieves `(CRUD(...), Paginated(20))` from schema_meta.

Phase 1 (Generate): fold with `DeriveGeneratable`. CRUD fires, generates 6 OpSpecs. Paginated skips.

Phase 2 (Modify): fold with `DeriveModifiable`. CRUD skips. Paginated fires, modifies List with pagination.

Phase 3 (Augment): fold with `DeriveAugmentable`. Neither fires.

Three folds over the same two capabilities. Each fold sees a different subset — the protocol-compatible ones.

**Fold 3: Materialization (OpSpec -> types + handlers).**

Each OpSpec becomes a request type, a response type, and an async handler. `build_from_spec` generates Python types at runtime using `create_dataclass`. The List endpoint gets `ListUsersRequest(page: int, page_size: int)` and `PaginatedResponse[User]`.

**Fold 4: Application assembly.**

Endpoints are mounted into an `Application`. Each endpoint has a runner (the async handler), exposures (trigger + codec + capabilities), and capabilities. The application is a tree of endpoints — the closure property at work.

**Fold 5: Target compilation (application -> framework).**

`targets.fastapi.compile(app, axes)` iterates each endpoint. For each exposure, it seeds a `FastAPIWrapContext` from the codec, folds surface capabilities through `FastAPIPipelineCompilable`, and assembles a `fastapi.APIRoute`. The result is a `fastapi.FastAPI` application with routes, middleware, exception handlers, lifespan management.

Five folds (with sub-folds). One declaration. The declaration — eleven lines of Python — is the *source*. The FastAPI app — with its routes, Pydantic models, OpenAPI schema, async handlers, and middleware — is one *projection*. A different target compiler would produce a different projection. The projection is *derived from* the source. The source is *more fundamental than* any projection.

**Exercise 2.12.** Repeat the five-fold trace, but add `Readonly()` to the derive capabilities: `@derive(http_crud("/users", Users), Paginated(20), Readonly())`. At which fold does Readonly have its effect? How many endpoints survive? What does the final FastAPI app look like?

**Exercise 2.13.** Trace the same User entity through `targets.cli.compile(app, axes)`. How does the CLI target differ from FastAPI at each fold? At which fold do the paths diverge? (Hint: folds 1-4 are identical. Only fold 5 differs.)

### 2.5.4 The Polynomial Tower

SICP culminates Chapter 2 with polynomial arithmetic — polynomials whose coefficients can be numbers, rationals, complex numbers, or *other polynomials*. This recursive tower demonstrates the full power of generic operations: the system that processes data can process data-about-data, recursively.

emergent's analog is `examples/fractal.py`. Recall from Chapter 1's Section 1.3.5 — the fractal example has four levels:

**Level 0:** Expressions as capabilities. `Poly(1, 2, 1)` represents `x^2 + 2x + 1`. It is a frozen dataclass with `compile_eval`, `compile_latex`, `compile_python`, `compile_derivative`.

**Level 1:** Compile entity to multiple targets. `Physics` has fields annotated with `Poly` and `Scale`. `FULL_ALGEBRA.compile(Physics, axes)` compiles each field through all four phases — evaluation, LaTeX, Python, derivative.

**Level 2:** Derive new entities. `derive_derivatives(Physics)` compiles through the `DERIVATIVE_PHASE`, extracts the derivative coefficients, and *constructs a new entity type* whose fields are `Poly` capabilities built from those coefficients. Data in, new data out — and the new data is itself compilable.

```python
PhysicsDerivative = derive_derivatives(Physics)
# PhysicsDerivative has fields:
#   d_position: Annotated[float, Poly(1.0, 0)]     # derivative of 0.5*t^2 is t
#   d_velocity: Annotated[float, Poly(1.0)]         # derivative of t is 1
#   d_energy: Annotated[float, Poly(1.0, 0)]        # derivative of 0.5*t^2 is t
```

The derivative entity can be compiled through the *same* phases: `FULL_ALGEBRA.compile(PhysicsDerivative, axes)` produces LaTeX, Python, evaluation for the derivative formulas. And you can differentiate *again*: `derive_derivatives(PhysicsDerivative)` gives the second derivative.

**Level 3:** Compile the compiler configuration. `FullReport` is a dataclass whose fields are annotated with meta-capabilities: `IncludePhase(LATEX_PHASE)`, `IncludePhase(PYTHON_PHASE)`, `OutputFormat("text")`. Folding these meta-capabilities produces a *compiler configuration* — which phases to run and how to format output. The fold produces a compiler. The compiler is itself the output of a fold.

```python
@dataclass
class FullReport:
    formulas: Annotated[str, IncludePhase(LATEX_PHASE), IncludePhase(PYTHON_PHASE),
                         OutputFormat("text")]
    values: Annotated[str, IncludePhase(EVAL_PHASE), OutputFormat("dict")]
    derivatives: Annotated[str, IncludePhase(DERIVATIVE_PHASE), OutputFormat("text")]
```

This is the polynomial tower. SICP's polynomials have coefficients that are polynomials. emergent's compile output is input to another compile. The fractal: fold consuming fold-described data, producing data that is itself fold-describable.

Hutton (1999) proved why this works: fold is the *unique morphism* from the initial algebra to any target algebra. If the target algebra is "compiler configurations," fold produces compiler configurations. If the target algebra is "new capabilities," fold produces new capabilities. The universal property guarantees: any structural processing of a capability list *is* a fold. This is not a library pattern — it is a mathematical necessity.

**Exercise 2.14.** In SICP's polynomial system, a polynomial's coefficients can be other polynomials: `(polynomial y (1 1))` as a coefficient means `y + 1`. Design the emergent equivalent: a capability `NestedPoly` whose coefficients are themselves `Poly` capabilities. What does `compile_derivative` produce for a nested polynomial? How deep can the nesting go?

---

## 2.6 The Query System as Generic Dispatch

### 2.6.1 Relational Queries: Operations as Capabilities

We now return to the query system introduced in Section 2.1, equipped with the full machinery of this chapter: closure property, conventional interfaces, symbolic data, multiple representations, generic dispatch.

A relational query is a sequence of operations:

```python
q = (
    relational(User)
        .filter(lambda u: u.active == True)
        .filter(lambda u: u.balance > 100)
        .order_by(lambda u: u.created_at.desc())
        .limit(50)
)
```

Each operation is a frozen dataclass — a capability:

- `Filter(expr)` — WHERE clause
- `OrderBy(specs)` — ORDER BY clause
- `Limit(n)` — LIMIT clause
- `Offset(n)` — OFFSET clause

Each implements multiple compile protocols:

```python
@dataclass(frozen=True, slots=True)
class OrderBy:
    specs: tuple[OrderSpec, ...]

    def compile_memory_query(self, ctx): ...  # Sort Python list
    def compile_sa_query(self, ctx): ...      # Add .order_by() to SQLAlchemy stmt
    def compile_http_api(self, ctx): ...      # Add ?order=... to params
```

When a provider executes a query, it folds the operations:

```python
# Memory provider:
ctx = MemoryQueryContext(data=all_users)
ctx = fold(query.ops, ctx, MemoryQueryCompilable, "compile_memory_query")
result = ctx.data  # Filtered, sorted, limited Python list

# SQL provider:
ctx = SAQueryContext(stmt=select(User))
ctx = fold(query.ops, ctx, SAQueryCompilable, "compile_sa_query")
result = await session.execute(ctx.stmt)  # Filtered, sorted, limited SQL query
```

Same operations. Same fold. Different protocol. Different artifact. The query is a *program in a domain-specific language*. The provider is the *interpreter for that language*. Different interpreters give different semantics — just as different folds give `MaxLen(255)` different meanings.

### 2.6.2 The Expression Compilers

Within the SQL fold, something interesting happens. When `Filter.compile_sa_query` encounters an expression like `Gt(Field("balance"), Const(100))`, it must compile *the expression* to a SQLAlchemy clause. The context carries a `compile_expr` function:

```python
def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
    clause = ctx.compile_expr(self.expr)
    return replace(ctx, stmt=ctx.stmt.where(clause))
```

`ctx.compile_expr` is a *nested fold* — it recursively walks the expression tree and produces a SQLAlchemy expression. `Field("balance")` becomes `User.balance` (a column reference). `Const(100)` becomes `literal(100)`. `Gt(left, right)` becomes `left > right` (SQLAlchemy's operator overloading).

This is fold inside fold. The outer fold processes the *list* of query operations (Filter, OrderBy, Limit). When it hits Filter, the Filter's compile method invokes an *inner fold* over the expression *tree*. The list fold calls the tree fold. Two different catamorphisms, nested, each consuming a different data shape.

The memory provider does not need `compile_expr`. It calls `self.expr.evaluate(item)` directly — the `evaluate` method on each Expr node. The tree traversal is implicit in the method dispatch. The SQL provider compiles the tree to a clause. The HTTP provider serializes it to query parameters. Three interpreters for the same expression language.

### 2.6.3 Composing Axes

The culminating insight of this chapter: axes *compose*. A single User entity participates in all four axes simultaneously:

- **Schema** provides the field types and capabilities
- **Surface** provides the endpoint structure (triggers, codecs)
- **Storage** provides the persistence backend
- **Query** provides the data access operations

The `@derive` decorator bridges them: it reads schema capabilities, generates derive operations (which define surface endpoints), each of which uses a query strategy (which targets a storage backend). The axes are orthogonal — you can change the query provider (memory -> SQL) without changing the surface structure, or change the surface trigger (HTTP -> CLI) without changing the schema capabilities.

This orthogonality is the closure property at the architectural level. Each axis composes internally (capabilities compose, endpoints compose, queries compose). And the axes compose with each other (schema + surface + storage + query = a working system). The composition is not additive ("glue four things together") but multiplicative ("each axis multiplied by each other axis"). Four axes with five options each give not 20 but potentially 625 combinations — and every combination works because each axis consumes its own protocols independently.

**Exercise 2.15.** The memory provider interprets expressions directly: `self.expr.evaluate(item)` walks the tree at runtime. The SQL provider compiles them to SQL clauses at query-build time. Which is "better"? Consider: (a) a table with 10 rows, (b) a table with 10 million rows, (c) a table behind an API that charges per query. How does the representation choice (interpreted vs compiled) affect performance? This is the emergent analog of SICP 2.3.3's question about set representations (unordered list vs ordered list vs binary tree).

---

## 2.7 Summary and Forward References

We have built compound data from the primitives of Chapter 1.

**Expressions** are the emergent analog of SICP's pairs: compound symbolic data with the closure property. An expression that combines two expressions is itself an expression. The tree grows without bound, and every sub-tree is compilable by the same mechanism.

**The closure property** holds at every level: expressions, capabilities, phases, endpoints, applications, queries. This is what makes composition compositional — not merely "you can combine things" but "combinations are things of the same kind."

**Symbolic data** — expressions that represent queries, not values — enables algebraic rewriting. Simplification rules on frozen expression trees are structurally identical to SICP's symbolic differentiation: pattern-match, simplify children, reduce. Both are catamorphisms over trees. Both produce new trees.

**Multiple representations** — the same capability compiled to different targets — produce categorically different programs. A FastAPI server, a CLI tool, and a Telegram bot from one entity declaration. These are not "views of the same thing." They are different things generated from the same description. The description is more fundamental than any output.

**Generic dispatch** — fold consuming capabilities via protocol check — is SICP's message-passing style. Each capability is an "intelligent data object" that carries its own compile methods. fold is `apply-generic`. The dispatch table is distributed, immutable, and extensible.

**The crisis**: compilation IS the semantics. There is no meaning of `MaxLen(255)` apart from its compilations. Different folds create different meanings. The capability description is the program. Any specific runtime is one projection.

Three questions open from here:

*What happens when the data changes over time?* Everything in this chapter is frozen. Expressions are immutable trees. Capabilities are frozen dataclasses. Queries describe *what to ask*, not *what has changed*. But real systems evolve — users are created, balances change, records are deleted. How do we model change without losing the properties that make fold tractable? Chapter 3 answers: the Log. Change is not mutation — it is accumulation. State is not stored — it is projected from immutable history.

*The fold that compiles capabilities... is itself described by capabilities.* We glimpsed this in the fractal (Level 3: `IncludePhase` as a meta-capability). Chapter 4 will develop it fully: fold consuming fold-described structures. The compiler compiling itself. Metacircular fold.

*What machine executes these folds?* We have been tracing folds by hand — treating fold as an abstraction. But the five folds that compile User run on real hardware, in real time, with real concurrency. The nodnod DAG, RuntimePolicy, and thread/coroutine scheduling that implement fold in practice are the subject of Chapter 5.

---

## Exercises

**Exercise 2.16.** The expression `And(Or(a, b), Or(c, d))` can be expanded by the distributive law to `Or(And(a, c), And(a, d), And(b, c), And(b, d))`. Implement a function `distribute_and_over_or(expr)` that applies this transformation. Then implement the reverse: `distribute_or_over_and`. Are both transformations guaranteed to terminate? Under what conditions does distribution increase expression size?

**Exercise 2.17.** SICP's `make-rat` enforces a representation invariant: the rational number is always in lowest terms (GCD reduction). Design an analogous invariant for query expressions. For example: `And(And(a, b), c)` should be automatically flattened to a balanced tree. Where should the invariant be enforced — in the `And` constructor, in a separate normalization pass, or in each compiler? What are the trade-offs?

**Exercise 2.18.** The `fold_expr` function in `_expr.py` uses a handler map keyed by exact type. The linear fold uses `isinstance` + `getattr`. Why the different dispatch strategies? What would happen if `fold_expr` used isinstance dispatch? What would happen if linear fold used exact-type handler maps?

**Exercise 2.19.** emergent's query simplifier handles boolean algebra (And, Or, Not). The algebra.py differentiator handles calculus. Both are algebraic rewriting on frozen trees. Design a *unified* simplifier that handles BOTH: given an expression tree that mixes boolean and arithmetic nodes (e.g., `And(Gt(Add(x, Num(0)), Num(5)), Const(True))`), apply both arithmetic simplification (`Add(x, Num(0)) -> x`) and boolean simplification (`And(expr, Const(True)) -> expr`). What data structure would you use for the combined expression AST?

**Exercise 2.20.** The five-fold trace in Section 2.5.3 shows how User goes from declaration to FastAPI app. But the trace is *forward-only* — from source to artifact. Design the *reverse* trace: given a running FastAPI endpoint `GET /users`, trace back to the capability that produced it. Which capabilities contributed? Which folds participated? emergent's `explain_derive` and `explain_entity` functions provide this introspection. Read `emergent/wire/derive/_explain.py` and describe how the reverse trace works.

**Exercise 2.21.** Consider two User entities compiled by two different SchemaCompilers:

```python
API_SCHEMA = PYDANTIC_PHASE + OPENAPI_PHASE
DB_SCHEMA = STORAGE_FIELD_PHASE + CONSTRAINTS_PHASE

api_result = API_SCHEMA.compile(User, axes)
db_result = DB_SCHEMA.compile(User, axes)
```

Both compile the same entity but produce different artifacts. Now consider: `FULL = API_SCHEMA + DB_SCHEMA`. Does `FULL.compile(User, axes)` produce the *union* of both results? Is `API_SCHEMA.compile(User, axes)` a *projection* of `FULL.compile(User, axes)`? Formalize the relationship. (Hint: think in terms of the banana split theorem.)

**Exercise 2.22.** SICP 2.4.3 presents message-passing as "intelligent data objects that dispatch on operation names." In emergent, the "operation name" is the method name string passed to fold: `"compile_pydantic"`, `"compile_sa_query"`, etc. What happens if two different protocols define a method with the same name? Can a capability implement two protocols that share a method name? What would fold do? Design a concrete example and trace the dispatch.
