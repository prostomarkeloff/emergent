# 2. Building Abstractions with Data

> We now come to the decisive step of mathematical abstraction: we forget about what the symbols stand for. … [The mathematician] need not be idle; there are many operations which he may carry out with these symbols, without ever having to look at the things they stand for.
>
> — Hermann Weyl, *The Mathematical Way of Thinking*

We concentrated in Chapter 1 on compilation processes and on the role of capabilities in compilation design. We saw how to use primitive capabilities (MaxLen, Identity, Unique) and primitive contexts (PydanticContext, OpenAPIContext), how to combine capabilities into annotations through Annotated, and how to abstract compound capabilities by defining them as named phases and compilers. We saw that a capability can be regarded as a pattern for the local transformation of a compilation context, and we classified, reasoned about, and performed simple analyses of common compilation patterns — single-phase, multi-phase (banana split), derivation, and verification. We also saw that higher-order capabilities and capability factories enhance the power of our framework by enabling us to manipulate, and thereby to reason in terms of, general methods of compilation. This is much of the essence of compilation thinking.

In this chapter we are going to look at more complex data. All the capabilities in Chapter 1 operate on simple schema data — field types and constraints. Simple schema data are not sufficient for many of the problems we wish to address using compilation. Programs are typically designed to model complex phenomena, and more often than not one must construct computational objects that have several parts in order to model real-world phenomena that have several aspects. Thus, whereas our focus in Chapter 1 was on building abstractions by combining capabilities to form compound capabilities, we turn in this chapter to another key aspect of any compilation framework: the means it provides for building abstractions by combining data objects to form *compound data*.

Why do we want compound data in a compilation framework? For the same reasons that we want compound capabilities: to elevate the conceptual level at which we can design our compilations, to increase the modularity of our designs, and to enhance the expressive power of our framework. Just as the ability to define capabilities enables us to deal with compilations at a higher conceptual level than that of primitive fold operations, the ability to construct compound data objects — queries, expressions, operation specs, event streams — enables us to deal with data at a higher conceptual level than that of primitive field annotations.

Consider the task of designing a system to perform queries on collections of entities. We could imagine an operation `filter` that takes a collection and a predicate and produces the matching subset. In terms of simple data, a predicate might be thought of as a function — `lambda u: u.balance > 100`. But this would be awkward, because we would then be unable to serialize the predicate, send it to a different backend, simplify it algebraically, or explain what it does. In a system intended to perform many queries on many backends — memory, SQL, HTTP API — such opacity would clutter the programs substantially, to say nothing of what it would do to our ability to reason about them. It would be much better if we could "glue together" a field reference, a comparison operator, and a constant to form an expression — a *compound data object* — that our programs could manipulate in a way that would be consistent with regarding a predicate as a single conceptual unit.

The use of compound data also enables us to increase the modularity of our compilations. If we can manipulate expressions directly as objects in their own right, then we can separate the part of our program that deals with what the query *means* from the details of how the query may be *executed* on a particular backend. The general technique of isolating the parts of a program that deal with how data objects are represented from the parts of a program that deal with how data objects are used is a powerful design methodology called *data abstraction*. We will see how data abstraction makes compilations much easier to design, maintain, and modify.

The use of compound data leads to a real increase in the expressive power of our compilation framework. Consider the idea of forming a "filtered, sorted, limited query." We might like to write a compilation that would accept a filter predicate, a sort key, and a limit count as arguments and produce the correct result on any backend — memory, SQL, or HTTP. This presents no difficulty if all backends share the same query protocol, because we can readily define the query operations as self-compiling frozen dataclasses. But suppose we are not concerned only with one backend. Suppose we would like to express, in compilational terms, the idea that one can execute queries whenever filter, sort, and limit are defined — for in-memory lists, for SQL databases, for REST APIs, or whatever. We could express this as a set of self-compiling operations that carry `compile_memory_query`, `compile_sa_query`, `compile_http_api` methods. The key point is that the only thing the query should need to know is that the operations have compile methods for the target backend. From the perspective of the query, it is irrelevant what the backend is and even more irrelevant how it might happen to be implemented.

We begin this chapter by implementing the query expression system. This will form the background for our discussion of compound data and data abstraction. As with compound capabilities, the main issue to be addressed is that of abstraction as a technique for coping with complexity, and we will see how data abstraction enables us to erect suitable *abstraction barriers* between different parts of a compilation.

We will see that the key to forming compound data is that a compilation framework should provide some kind of "glue" so that data objects can be combined to form more complex data objects. There are many possible kinds of glue. Indeed, we will discover how to form compound data using no special "data" operations at all — only frozen dataclasses and fold. This will further blur the distinction between "capability" and "data," which was already becoming tenuous toward the end of Chapter 1. We will also explore some conventional techniques for representing expressions, queries, and operation specs. One key idea in dealing with compound data is the notion of *closure* — that the glue we use for combining data objects should allow us to combine not only primitive data objects, but compound data objects as well. In emergent, the SchemaCompiler algebra is closed: `SchemaCompiler + SchemaCompiler = SchemaCompiler`. The TargetCompiler algebra is closed: `TargetCompiler + CodecBinding = TargetCompiler`. Capabilities compose into tuples, tuples compose by concatenation, and the result is a tuple — closed.

We will then augment the representational power of our framework by introducing *symbolic expressions* — data whose elementary parts can be arbitrary field references, comparisons, and logical connectives rather than only annotations. We explore various alternatives for representing query predicates. We will find that, just as a given compilation can be performed by many different fold phases, there are many ways in which a given query can be compiled to a concrete backend, and the choice of backend can have significant impact on the performance of the result. We will investigate these ideas in the context of the query axis — relational, key-value, and API querysets.

Next we will take up the problem of working with data that may be represented differently by different parts of a program. This leads to the need to implement *generic operations*, which must handle many different kinds of data. Maintaining modularity in the presence of generic operations requires more powerful abstraction barriers than can be erected with simple data abstraction alone. In particular, we introduce *protocol-directed compilation* as a technique that allows individual data representations to be designed in isolation and then combined *additively* (i.e., without modification). To illustrate the power of this approach to system design, we close the chapter by applying what we have learned to the implementation of a package for performing symbolic algebra — differentiation, LaTeX rendering, and Python code generation — in which the expression nodes carry their own compilation methods, exactly like capabilities on fields.

---

## 2.1 Introduction to Data Abstraction

In 1.1.8, we noted that a capability used as an element in creating a more complex compilation could be regarded not only as a specific set of compile_* methods but also as a *capability abstraction*. That is, the details of how the capability was implemented could be suppressed, and the particular capability itself could be replaced by any other capability with the same overall behavior. In other words, we could make an abstraction that would separate the way the capability would be *used* from the details of how the capability would be *implemented* in terms of more primitive operations. The analogous notion for compound data is called *data abstraction*. Data abstraction is a methodology that enables us to isolate how a compound data object is used from the details of how it is constructed from more primitive data objects.

The basic idea of data abstraction is to structure the programs that use compound data objects so that they operate on "abstract data." That is, our programs should use data in such a way as to make no assumptions about the data that are not strictly necessary for performing the task at hand. At the same time, a "concrete" data representation is defined independent of the programs that use the data. The interface between these two parts of our system will be a set of capabilities called *selectors* and *constructors* that implement the abstract data in terms of the concrete representation.

### 2.1.1 Example: Query Expressions

To illustrate the idea of data abstraction, consider how a query expression is represented and used in emergent.

A query expression is a predicate on entities — "balance greater than 100," "name starts with A and active is true." The emergent query axis represents these as frozen dataclass ASTs:

```python
Gt(Field("balance"), Const(100))
And(StartsWith(Field("name"), Const("A")), Eq(Field("active"), Const(True)))
```

The constructors are the dataclass constructors: `Gt(left, right)`, `And(left, right)`, `Field(name)`, `Const(value)`. The selectors are attribute access: `expr.left`, `expr.right`, `field.name`, `const.value`.

But the user of the query system does not write ASTs by hand. The user writes lambdas:

```python
users.filter(lambda u: u.balance > 100)
users.filter(lambda u: u.name.startswith("A") & u.active)
```

The lambda receives an EntityProxy. `u.balance` returns a FieldProxy. `> 100` returns `Gt(Field("balance"), Const(100))`. The proxy trick — `__gt__`, `__and__`, `startswith` returning frozen AST nodes — is the *constructors* of the abstract query expression, hiding the concrete AST representation from the user.

The *selectors* are used by backends. MemoryRelationalProvider evaluates the expression directly:

```python
# inside Filter.compile_memory_query
[item for item in ctx.data if self.expr.evaluate(item)]
```

SQLRelationalProvider compiles to SQL:

```python
# inside Filter.compile_sa_query
clause = ctx.compile_expr(self.expr)
return replace(ctx, stmt=ctx.stmt.where(clause))
```

HTTPAPIProvider compiles to query parameters:

```python
# inside Filter.compile_http_api
filter_data = ctx.encode_filter(self.expr)
ctx.params.update(filter_data)
```

The key point of data abstraction: the query expression — `Gt(Field("balance"), Const(100))` — is a single object that three different backends interpret differently. The user writes the same `.filter(lambda u: u.balance > 100)` regardless of backend. The compilation produces different code depending on the target, but the expression itself is one object, one meaning, one piece of data.

This is the same pattern as Chapter 1's capability abstraction — `MaxLen(255)` compiles differently for Pydantic, OpenAPI, and SQL — but now applied to query predicates instead of field constraints. The abstraction barrier separates "what the query means" from "how the query executes."

### 2.1.2 Abstraction Barriers

In general, the underlying idea of data abstraction is to identify for each type of data object a basic set of operations in terms of which all manipulations of data objects of that type will be expressed, and then to use only those operations in manipulating the data.

For the query expression system, the abstraction barriers look like this:

```
Programs that use queries
─────────────────────────────────
.filter(), .order_by(), .limit()        (QuerySet API)
─────────────────────────────────
Filter, OrderBy, Limit                  (Self-compiling ops)
─────────────────────────────────
Expr AST: Gt, And, Field, Const         (Expression constructors)
─────────────────────────────────
compile_memory_query, compile_sa_query  (Backend interpreters)
```

Each horizontal line represents an abstraction barrier. Programs above the line do not know about the details below it. A user writing `.filter(lambda u: u.balance > 100)` does not know about Gt, Field, or Const. The Filter op does not know about compile_sa_query — it only knows it has a compile_* method that fold will call. The SQL provider does not know about the memory provider.

For the capability system from Chapter 1, the abstraction barriers are:

```
Programs that use capabilities
─────────────────────────────────
@derive(http_crud(...), Paginated(20))  (Derivation API)
─────────────────────────────────
CRUD, Paginated, SoftDelete             (Schema capabilities)
─────────────────────────────────
MaxLen, Identity, Unique                (Universal capabilities)
─────────────────────────────────
compile_pydantic, compile_openapi       (Target compilers)
```

The same structure. Multiple layers. Each layer uses the one below it without depending on its internal structure.

This methodology gives us a way to control complexity. It lets the user of a query think in terms of "filter by balance," the compilation framework think in terms of "Filter op with Gt expression," and the backend think in terms of "WHERE balance > 100" or `[item for item in data if item.balance > 100]`. Each level operates at its own level of abstraction.

---

## 2.2 Hierarchical Data and the Closure Property

As we saw in 2.1, the query expression system uses frozen dataclasses as its compound data primitives. We also saw that capabilities use frozen dataclasses. In fact, every data object in emergent is a frozen dataclass. The "glue" for constructing compound data is the dataclass constructor itself.

We should now consider the question: what kinds of compound data can we build with frozen dataclasses? In Chapter 1, capabilities were flat — a tuple of independent annotations on a field. But queries introduce *hierarchy*: `And(Gt(Field("x"), Const(5)), IsNull(Field("y")))` is a tree. Derivation introduces *stages*: compile_derive produces OpSpecs, materialize produces Endpoints, fastapi.compile produces routes. theworld introduces *nesting*: World contains Computations, each containing capabilities, which fold into nodes.

The key property that enables this hierarchy is *closure*: the result of combining data objects with a constructor can itself be combined with the same constructor. `And(expr1, expr2)` produces an Expr, which can itself be used as an argument to another And, or to Or, or to Not. The constructors are closed under composition.

In emergent, closure appears at every level:

- **Capabilities on fields:** `Annotated[str, MaxLen(255), Unique]` — a tuple. Tuples concatenate: `caps_a + caps_b` is a tuple. Closed.
- **Phases in compilers:** `PYDANTIC_PHASE + OPENAPI_PHASE` produces a SchemaCompiler. `SchemaCompiler + SchemaCompiler` produces a SchemaCompiler. Closed.
- **Targets in compilers:** `TargetCompiler + CodecBinding` produces a TargetCompiler. Closed.
- **Expressions in queries:** `And(expr1, expr2)` produces an Expr. `Or(And(...), Gt(...))` also produces an Expr. Closed.
- **Ops in querysets:** `users.filter(...).order_by(...).limit(10)` — each method appends an op and returns a new QuerySet. Closed.
- **Computations in worlds:** `World(computations=(a, b, c))` — a tuple. `scoped(a, b, Supervised())` — a tuple inside scoped. Closed.

This closure property is what Abelson and Sussman call the "closure property of cons" in SICP: the ability to build hierarchical structures from a single combining mechanism. In emergent, the mechanism is tuple concatenation for flat structures and dataclass nesting for hierarchical ones.

### 2.2.1 Representing Sequences

The most common compound data structure in emergent is the *sequence* — a tuple of frozen dataclasses. Capabilities on a field are a sequence. Ops in a query are a sequence. Phases in a compiler are a sequence. Computations in a world are a sequence.

Sequences are processed by fold. Every sequence in emergent — without exception — is consumed by the same six-line function. This uniformity is the reason emergent has one mechanism instead of many.

Consider the pipeline — a sequence of PipelineSteps:

```python
list_handler = Pipeline(ScopeQuery(), FetchAll(), WrapItems())
update_handler = Pipeline(
    ScopeQuery(), IdentityFilter(), FetchOrNotFound(),
    MergeFields(), ProviderUpdate(), WrapOk(),
)
```

Each PipelineStep is a frozen dataclass implementing `execute(pctx) -> PipelineContext | Result`. The Pipeline iterates them sequentially. A step can short-circuit by returning a Result (Ok or Error) instead of a PipelineContext.

This is fold with a twist: the accumulator (PipelineContext) is mutable within the scope of one request, but the step definitions are frozen. The pipeline definition is data — inspectable, printable, testable per step. The pipeline execution is fold — sequential application of steps to an accumulator.

### 2.2.2 Representing Trees

Query expressions are trees. `And(Gt(Field("balance"), Const(100)), IsNull(Field("deleted_at")))` has depth 3. The expression nodes are frozen dataclasses. Each node implements `evaluate(obj)` for in-memory interpretation and `children()` for traversal.

The algebra example from Chapter 1 section 1.1.7 demonstrates the same structure at a different scale. Symbolic expressions — `Mul(Fn("sin", Sym("x")), Pw(Sym("x"), Num(2)))` — are trees of frozen dataclasses. Each node has compile_python, compile_latex, compile_eval, compile_deriv. The compilation driver wraps fold with a recursive closure:

```python
def compile_python(expr):
    def _compile(e):
        ctx = PythonCtx(result="", compile_expr=_compile)
        result = fold([e], ctx, PythonCompilable, "compile_python")
        return result.result
    return _compile(expr)
```

`ctx.compile_expr` IS the recursive descent. fold dispatches to the node's compile_python. The node calls `ctx.compile_expr` on its children. Recursion through data — the context carries the recursive function, the node applies it. This is the emergent analog of SICP's tree accumulation: values percolate upward from terminal nodes, combining at each level through the compile method.

### 2.2.3 Conventional Interfaces

SICP identifies map, filter, and accumulate as "conventional interfaces" — patterns that recur across different domains of list processing. By naming these patterns and providing them as standard operations, the programmer can think at a higher level: not "iterate and conditionally collect" but "filter." Not "iterate and transform" but "map." Not "iterate and accumulate" but "fold."

In emergent, there is only ONE conventional interface: fold. Where SICP has three patterns, emergent has one. This might seem like a reduction — one pattern where SICP has three. But it is more accurately a unification. SICP's map, filter, and accumulate are all special cases of fold:

```scheme
;; SICP's three conventional interfaces
(map f list)       = (fold-right (lambda (x acc) (cons (f x) acc)) '() list)
(filter pred list) = (fold-right (lambda (x acc) (if (pred x) (cons x acc) acc)) '() list)
(accumulate op init list) = (fold-right op init list)
```

In emergent, these three operations appear within different fold invocations, but the fold itself is invariant:

**Schema compilation = fold as accumulate.** Each capability contributes to the context. `MaxLen(255)` adds max_length. `Unique` adds unique=True. The context is the accumulator. fold is `accumulate`.

**Query filtering = fold as filter.** `Filter(Gt(Field("balance"), Const(100))).compile_memory_query(ctx)` removes non-matching items from `ctx.data`. The data is the list. The capability is the predicate. fold-within-fold is `filter`.

**Derivation = fold as map.** `CRUD.compile_derive_generate(ctx)` maps the entity schema to OpSpecs. Each field of the entity contributes one aspect of each OpSpec. The entity-to-specs mapping is `map`.

But these are not separate functions. They are all fold with different capabilities and different contexts. The programmer does not need to choose between map, filter, and accumulate. The programmer provides capabilities; fold does whatever the capabilities' compile_* methods prescribe. If the method filters data, fold filters. If it accumulates metadata, fold accumulates. If it generates new structures, fold generates.

This unification has a consequence that SICP's three-interface approach does not: **the interfaces compose automatically.** In SICP, composing map-filter-accumulate requires explicit piping:

```scheme
(accumulate + 0
  (map square
    (filter odd?
      (enumerate-interval 0 n))))
```

In emergent, composition is implicit in the capability tuple:

```python
Annotated[str, MaxLen(255), Unique, sql.Index(), Doc("Email address")]
```

Four capabilities. fold processes all four in one pass. No explicit piping. No intermediate lists. The banana split theorem guarantees that running four accumulations simultaneously is as efficient as running them in sequence — and more efficient than running them separately, because the capability list is traversed once, not four times.

This is why emergent has one conventional interface rather than three. The unification is not a simplification — it is a *fusion*. Where SICP's interfaces compose by piping (the output of one feeds the input of the next), emergent's interface composes by simultaneity (all accumulations happen in the same traversal). Hutton (1999) calls this the banana split property. In practice, it means that adding a new compilation phase to an entity does not add a new traversal of the capability list — it adds one more accumulation to the same traversal.

The signal-flow diagram for a conventional SICP pipeline looks like:

```
enumerate → filter → map → accumulate
```

The signal-flow diagram for an emergent compilation looks like:

```
                    ┌→ PydanticContext
capabilities ──fold─┼→ OpenAPIContext
                    ├→ SQLAlchemyContext
                    └→ ConstraintsContext
```

One source (capabilities). One fold. Multiple simultaneous outputs. No intermediate data. This is why emergent programs are shorter than their SICP analogs — not because they omit steps, but because they fuse them.

The cost of this fusion is that you cannot interpose logic *between* phases within a single fold. If the OpenAPI compilation needed to read the result of the Pydantic compilation, the two could not be banana-split. They would need to run sequentially. This is why emergent's axes are orthogonal: each axis folds independently, through independent contexts, so that banana splitting is always valid. Dependencies between axes are handled at a higher level — by running one compilation after another, not by nesting them within a single fold.

The pattern is invariant: `fold(items, initial_context, protocol, method)`. The items change (capabilities, ops, computations). The context changes (PydanticContext, MemoryQueryContext, WorldContext). The protocol changes. But fold is the same. This is the conventional interface of emergent — the one pattern that connects all domains.

SICP identifies map, filter, and accumulate as the conventional interfaces for sequence operations. emergent identifies fold as the ONE conventional interface for ALL operations. Not map, not filter, not reduce — fold. Every operation in emergent is a fold. This uniformity is not a limitation — it is the source of the algebraic laws that make the system tractable.

---

## 2.3 Symbolic Data

One of the most interesting domains for compilation is *symbolic data* — expressions whose parts are not numbers or strings but arbitrary symbols. The query expression AST is one example. The symbolic algebra engine is another. In both cases, the data represents meaning rather than value, and the compilation transforms meaning into target-specific artifacts.

### 2.3.1 The Expression AST

The emergent query axis defines an expression language:

```python
class Expr(ABC):
    @abstractmethod
    def evaluate(self, obj) -> Any: ...
    def children(self) -> tuple[Expr, ...]: ...
    def __and__(self, other): return And(self, other)
    def __or__(self, other): return Or(self, other)
    def __invert__(self): return Not(self)

@dataclass(frozen=True, slots=True)
class Field(Expr):
    name: str
    def evaluate(self, obj): return getattr(obj, self.name)

@dataclass(frozen=True, slots=True)
class Const(Expr):
    value: Any
    def evaluate(self, obj): return self.value

@dataclass(frozen=True, slots=True)
class Gt(Expr):
    left: Expr
    right: Expr
    def evaluate(self, obj):
        return self.left.evaluate(obj) > self.right.evaluate(obj)
```

Comparison operators: Eq, Ne, Lt, Le, Gt, Ge. Logical: And, Or, Not. Collection: In, Contains, StartsWith, EndsWith. Null: IsNull, IsNotNull. Range: Between. Pattern: Like, ILike, Regex. Array: ArrayContains, ArrayAny, ArrayAll, ArrayOverlap. JSON: JsonExtract, JsonContains, JsonHasKey.

Every node is a frozen dataclass. Every node implements evaluate() for in-memory interpretation. The entire tree is serializable — `expr_to_dict(expr)` produces a JSON-compatible dict. Deserializable — `expr_from_dict(d)` reconstructs the tree. Simplifiable — `simplify_expr(expr)` applies boolean algebra optimizations. Measurable — `expr_complexity(expr)` counts nodes, `expr_depth(expr)` measures nesting.

This is symbolic data in the fullest sense: the expression is a manipulable object, not an opaque function. This is why emergent chose initial encoding (data) over final encoding (functions). The expression `Gt(Field("balance"), Const(100))` can be inspected, serialized, simplified, explained, and compiled. A lambda `lambda u: u.balance > 100` can only be called.

### 2.3.2 Symbolic Differentiation

SICP Section 2.3.2 develops symbolic differentiation as its primary example of symbolic data processing. We will do the same — but where SICP uses `cond` dispatch on expression types, we use fold with protocol dispatch. The result is a system where adding a new expression type does not require modifying any existing code, and adding a new compilation target does not require modifying any existing expression.

**The expression language.** We define expression nodes as frozen dataclasses:

```python
@dataclass(frozen=True, slots=True)
class Num(AlgExpr):
    value: float
    def evaluate(self, env): return self.value

@dataclass(frozen=True, slots=True)
class Sym(AlgExpr):
    name: str
    def evaluate(self, env): return env[self.name]

@dataclass(frozen=True, slots=True)
class Add(AlgExpr):
    left: AlgExpr
    right: AlgExpr
    def evaluate(self, env): return self.left.evaluate(env) + self.right.evaluate(env)

@dataclass(frozen=True, slots=True)
class Mul(AlgExpr):
    left: AlgExpr
    right: AlgExpr
    def evaluate(self, env): return self.left.evaluate(env) * self.right.evaluate(env)
```

Convenience: `x = Sym("x")`, and operator overloading — `x + 1` produces `Add(Sym("x"), Num(1))`, `x * x` produces `Mul(Sym("x"), Sym("x"))`. We also define `Div`, `Pw` (power), `Neg`, `Fn` (built-in functions like sin, cos, exp, log), and `LetIn` (local binding).

**The compilation contexts.** Each target has a frozen dataclass context:

```python
@dataclass(frozen=True, slots=True)
class PythonCtx:
    result: str
    compile_expr: Callable[[AlgExpr], str]

@dataclass(frozen=True, slots=True)
class LatexCtx:
    result: str
    compile_expr: Callable[[AlgExpr], str]

@dataclass(frozen=True, slots=True)
class DerivCtx:
    result: AlgExpr
    var: str
    compile_expr: Callable[[AlgExpr], AlgExpr]
```

Notice: each context carries a `compile_expr` field — a function. This is how recursion works in the fold model. The compilation driver creates a recursive closure and injects it into the context:

```python
def compile_python(expr):
    def _compile(e):
        ctx = PythonCtx(result="", compile_expr=_compile)
        result = fold([e], ctx, PythonCompilable, "compile_python")
        return result.result
    return _compile(expr)
```

`_compile` is the recursive function. It creates a context carrying itself as `compile_expr`, then folds the single expression through the protocol. The expression's compile_python method receives the context — and with it, the ability to recurse on sub-expressions by calling `ctx.compile_expr(child)`.

This is SICP's concept of "procedures as data" taken one step further. The context is data (frozen dataclass). The recursive function is data (a field on the context). The expression is data (frozen dataclass). fold dispatches on data (isinstance). The entire computation — recursive descent over an expression tree, producing Python code — is orchestrated by frozen data and a six-line function.

**Differentiation rules as compile methods.** Each expression node implements compile_deriv. The rules are mathematics:

```python
# d/dx c = 0  (constant)
Num.compile_deriv = lambda self, ctx: replace(ctx, result=Num(0))

# d/dx x = 1, d/dx y = 0  (variable)
Sym.compile_deriv = lambda self, ctx: replace(ctx, result=
    Num(1) if self.name == ctx.var else Num(0))

# d/dx (f + g) = f' + g'  (sum rule)
Add.compile_deriv = lambda self, ctx: replace(ctx, result=
    ctx.compile_expr(self.left) + ctx.compile_expr(self.right))

# d/dx (f * g) = f'g + fg'  (product rule)
Mul.compile_deriv = lambda self, ctx: replace(ctx, result=
    ctx.compile_expr(self.left) * self.right + self.left * ctx.compile_expr(self.right))

# d/dx (f / g) = (f'g - fg') / g²  (quotient rule)
Div.compile_deriv = lambda self, ctx: replace(ctx, result=
    (ctx.compile_expr(self.left) * self.right - self.left * ctx.compile_expr(self.right))
    / (self.right ** 2))

# d/dx x^n = n * x^(n-1) * x'  (power rule)
Pw.compile_deriv = lambda self, ctx: replace(ctx, result=
    self.exponent * (self.base ** (self.exponent - 1)) * ctx.compile_expr(self.base))
```

And the chain rule for built-in functions:

```python
def _fn_deriv(self, ctx):
    da = ctx.compile_expr(self.arg)   # derivative of argument
    match self.name:
        case "sin": return replace(ctx, result=cos(self.arg) * da)
        case "cos": return replace(ctx, result=-(sin(self.arg)) * da)
        case "exp": return replace(ctx, result=exp(self.arg) * da)
        case "log": return replace(ctx, result=da / self.arg)
        case "sqrt": return replace(ctx, result=da / (Num(2) * sqrt(self.arg)))
Fn.compile_deriv = _fn_deriv
```

Each rule is a compile method — a frozen relationship between an expression node and its derivative, mediated by the context. The chain rule appears naturally: `ctx.compile_expr(self.arg)` recursively differentiates the argument, and the result is multiplied by the outer derivative.

**Working through an example.** Let us trace `compile_deriv(sin(x) * x**2)` in detail.

The expression is `Mul(Fn("sin", Sym("x")), Pw(Sym("x"), Num(2)))`.

fold dispatches to Mul's compile_deriv (product rule):
```
result = ctx.compile_expr(self.left) * self.right + self.left * ctx.compile_expr(self.right)
```

`ctx.compile_expr(self.left)` = compile_deriv of `Fn("sin", Sym("x"))`:
- fold dispatches to Fn.compile_deriv (chain rule for sin):
  - `da` = compile_deriv of `Sym("x")` = `Num(1)` (variable rule)
  - result = `cos(Sym("x")) * Num(1)` = `Fn("cos", Sym("x"))`

`ctx.compile_expr(self.right)` = compile_deriv of `Pw(Sym("x"), Num(2))`:
- fold dispatches to Pw.compile_deriv (power rule):
  - `Num(2) * (Sym("x") ** Num(1)) * compile_deriv(Sym("x"))`
  - = `Num(2) * Sym("x") * Num(1)` = `Mul(Num(2), Sym("x"))` after simplification

Product rule combines:
```
cos(x) * x² + sin(x) * 2x
```

After simplification: `cos(x) * x² + sin(x) * 2 * x`. Mathematically correct.

**Four targets from one AST.** The same expression — `sin(x) * x**2` — compiles to four different representations:

```python
>>> compile_python(sin(x) * x**2)
'(math.sin(x) * (x ** 2))'

>>> compile_latex(sin(x) * x**2)
'\\sin(x) \\cdot {x}^{2}'

>>> compile_eval(sin(x) * x**2, {"x": 1.0})
0.8414709848078965

>>> simplify(compile_deriv(sin(x) * x**2))
# cos(x) * x² + sin(x) * 2 * x
```

Python source code. LaTeX notation. Numerical evaluation. Symbolic derivative. Four fold invocations. Same expression. Same six-line fold. Different protocol, different context, different result.

**Comparison with SICP's approach.** SICP 2.3.2 implements differentiation with a recursive procedure `deriv` that dispatches on expression type using `cond`:

```scheme
(define (deriv exp var)
  (cond ((number? exp) 0)
        ((variable? exp) (if (same-variable? exp var) 1 0))
        ((sum? exp) (make-sum (deriv (addend exp) var) (deriv (augend exp) var)))
        ((product? exp) ...)))
```

The difference is not syntactic but structural. In SICP's approach, adding a new expression type (e.g., exponentiation) requires adding a new clause to `deriv` — modifying existing code. Adding a new operation (e.g., LaTeX rendering) requires writing a new recursive procedure with its own `cond` dispatch.

In emergent's approach, adding a new expression type means defining a new frozen dataclass with compile_deriv, compile_python, compile_latex methods. Existing code is not modified. Adding a new operation means defining a new protocol and context — existing expression types that don't implement it are skipped (or raise, as discussed in 1.1.6). Both dimensions extensible. This is the Expression Problem dissolved — not just for web APIs (Chapter 1) and query backends (Section 2.4), but for symbolic mathematics.

The algebra example has nothing to do with web development, databases, or HTTP. It is pure mathematics. And yet it uses the same encoding, the same fold, the same dispatch. This is the strongest evidence that the encoding is not a web framework trick but a general-purpose computational pattern.

---

## 2.4 Multiple Representations for Abstract Data

We have introduced data abstraction, a methodology for structuring systems in such a way that much of a program can be specified independent of the choices involved in implementing the data objects that the program manipulates. For example, we saw in 2.1.1 how to separate the task of designing a program that uses query expressions from the task of implementing query expressions in terms of the concrete AST representation. The key idea was to erect an abstraction barrier — in this case, the proxy-based lambda syntax and the evaluate/compile_* methods — that isolates the way query expressions are used from their underlying representation.

But this kind of data abstraction is not yet powerful enough, because it may not always make sense to speak of "the underlying representation" for a data object.

For one thing, there might be more than one useful representation for a data object, and we might like to design systems that can deal with multiple representations. To take a central example: a query expression like `Gt(Field("balance"), Const(100))` may be represented in multiple ways depending on the backend. For the memory backend, it is an evaluable predicate. For the SQL backend, it is a WHERE clause. For the HTTP backend, it is a query parameter `?balance_gt=100`. Indeed, it is perfectly plausible to imagine a system in which the same query expression is used with all three backends simultaneously, and in which the operations for executing queries work with any representation.

More importantly, compilation systems are often designed by many people working over extended periods of time, subject to requirements that change over time. In such an environment, it is simply not possible for everyone to agree in advance on choices of data representation. So in addition to the data-abstraction barriers that isolate representation from use, we need abstraction barriers that isolate different design choices from each other and permit different choices to coexist in a single program. Furthermore, since large compilation systems are often created by combining pre-existing modules that were designed in isolation, we need conventions that permit programmers to incorporate modules into larger systems *additively*, that is, without having to redesign or reimplement these modules.

In this section, we will learn how to cope with data that may be represented in different ways by different parts of a program. This requires constructing *generic operations* — operations that can operate on data that may be represented in more than one way. Our main technique for building generic operations will be to work in terms of data objects that have *protocol tags* — that is, data objects that include explicit information about how they are to be processed. We will also discuss *protocol-directed compilation*, a powerful and convenient implementation strategy for additively assembling systems with generic operations.

### 2.4.1 Representations for Query Operations

Query operations in emergent are frozen dataclasses with multiple compile_* methods — one per backend. This is the key design decision that resolves the multiple-representation problem.

Consider Filter:

```python
@dataclass(frozen=True, slots=True)
class Filter:
    expr: Expr

    def compile_memory_query(self, ctx: MemoryQueryContext) -> MemoryQueryContext:
        return replace(ctx, data=[item for item in ctx.data if self.expr.evaluate(item)])

    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext:
        clause = ctx.compile_expr(self.expr)
        return replace(ctx, stmt=ctx.stmt.where(clause))

    def compile_memory_api(self, ctx: MemoryAPIContext) -> MemoryAPIContext:
        return replace(ctx, data=[item for item in ctx.data if self.expr.evaluate(item)])

    def compile_http_api(self, ctx: HTTPAPIContext) -> HTTPAPIContext:
        filter_data = ctx.encode_filter(self.expr)
        ctx.params.update(filter_data)
        return ctx
```

One Filter object. Four compile methods. Four backends. Let us trace what happens when the same query meets different backends.

Consider the query:

```python
q = users.filter(lambda u: u.balance > 100).order_by(lambda u: u.balance.desc()).limit(10)
```

This produces three ops: `Filter(Gt(Field("balance"), Const(100)))`, `OrderBy((OrderSpec("balance", ascending=False),))`, `Limit(10)`.

**Memory backend.** The provider creates `MemoryQueryContext(data=all_users)` — a list of entity objects in memory. fold iterates the three ops:

```
Step 1: Filter.compile_memory_query(ctx)
  → ctx.data = [u for u in all_users if u.balance > 100]
  (evaluates Gt(Field("balance"), Const(100)).evaluate(u) for each u)
  → 347 users remaining from 1000

Step 2: OrderBy.compile_memory_query(ctx)
  → ctx.data.sort(key=lambda u: u.balance, reverse=True)
  → sorted descending by balance

Step 3: Limit.compile_memory_query(ctx)
  → ctx.data = ctx.data[:10]
  → top 10 highest balances
```

The result is a list of 10 entity objects. The entire query executed in Python, in memory, on the list.

**SQL backend.** The provider creates `SAQueryContext(stmt=select(UserModel), get_column=..., compile_expr=...)` — a SQLAlchemy SELECT statement. fold iterates the same three ops:

```
Step 1: Filter.compile_sa_query(ctx)
  → clause = ctx.compile_expr(Gt(Field("balance"), Const(100)))
  → clause = UserModel.balance > 100
  → ctx.stmt = ctx.stmt.where(UserModel.balance > 100)
  → SQL: SELECT * FROM users WHERE balance > 100

Step 2: OrderBy.compile_sa_query(ctx)
  → col = ctx.get_column("balance")
  → ctx.stmt = ctx.stmt.order_by(col.desc())
  → SQL: SELECT * FROM users WHERE balance > 100 ORDER BY balance DESC

Step 3: Limit.compile_sa_query(ctx)
  → ctx.stmt = ctx.stmt.limit(10)
  → SQL: SELECT * FROM users WHERE balance > 100 ORDER BY balance DESC LIMIT 10
```

The result is a SQLAlchemy SELECT statement. No data has been fetched. The query is a description — it will execute when the provider calls `await session.execute(ctx.stmt)`.

**HTTP API backend.** The provider creates `HTTPAPIContext(params={}, base_url="https://api.example.com/users")`. fold iterates:

```
Step 1: Filter.compile_http_api(ctx)
  → filter_data = ctx.encode_filter(Gt(Field("balance"), Const(100)))
  → ctx.params = {"balance_gt": "100"}

Step 2: OrderBy.compile_http_api(ctx)
  → ctx.params = {"balance_gt": "100", "sort": "-balance"}

Step 3: Limit.compile_http_api(ctx)
  → ctx.params = {"balance_gt": "100", "sort": "-balance", "limit": "10"}
```

The result is a dict of query parameters. The provider will make an HTTP request: `GET https://api.example.com/users?balance_gt=100&sort=-balance&limit=10`.

Three backends. Same three ops. Same fold. Different contexts. Different results. The Filter object does not know which backend it will compile for — it implements all four compile_* methods and fold dispatches based on the protocol. The user writes `users.filter(lambda u: u.balance > 100)` and the backend determines whether this becomes a list comprehension, a SQL WHERE clause, or an HTTP query parameter.

This is "multiple representations" in the SICP sense — the same abstract operation with different concrete implementations. But where SICP's complex numbers use tagged data and external dispatch tables, emergent's query operations use *self-dispatch*: the operation carries its own implementations as methods, and fold dispatches via isinstance. The dispatch is not in a table maintained by the programmer. It is emergent from the Protocol type system.

OrderBy, Limit, Offset, Select, Join, GroupBy, Having, Distinct — each follows the same pattern. Each is a frozen dataclass with compile_* methods for whichever backends support it. GroupBy, for instance, has compile_memory_query (Python groupby) and compile_sa_query (SQL GROUP BY) but no compile_http_api (most REST APIs don't support server-side grouping). The HTTP backend's fold silently skips GroupBy — open-world dispatch at work.

This is the same pattern as capabilities from Chapter 1. MaxLen(255) has compile_pydantic, compile_openapi, compile_sqlalchemy. Filter(expr) has compile_memory_query, compile_sa_query, compile_http_api. The encoding is invariant: frozen dataclass + compile_* methods + fold dispatch. The domain changes (field annotations vs query operations). The mechanism does not.

### 2.4.2 Protocol-Directed Compilation

The emergent approach to generic operations can be characterized as *protocol-directed compilation*. For each target, there is a Protocol:

```python
@runtime_checkable
class MemoryQueryCompilable(Protocol):
    def compile_memory_query(self, ctx: MemoryQueryContext) -> MemoryQueryContext: ...

@runtime_checkable
class SAQueryCompilable(Protocol):
    def compile_sa_query(self, ctx: SAQueryContext) -> SAQueryContext: ...
```

fold dispatches by checking isinstance against the target protocol. This is structurally similar to SICP's data-directed programming — a dispatch table indexed by operation and type. But the dispatch table is not a separate data structure maintained by the programmer. It is emergent from the type system: isinstance checks whether the object has the right method. No registration. No dispatch table. No explicit tagging.

The power of this approach is *additivity*. To add a new backend — say, a graph database — you define a new Protocol and a new Context:

```python
@runtime_checkable
class GraphDBCompilable(Protocol):
    def compile_graph_db(self, ctx: GraphDBContext) -> GraphDBContext: ...
```

Then you add `compile_graph_db` methods to whichever query operations should support the new backend. Existing operations that don't implement the new protocol are silently skipped. Existing backends are not affected. No code is modified — only added.

To add a new operation — say, FullTextSearch — you define a new frozen dataclass with compile_* methods for whichever backends support full-text search:

```python
@dataclass(frozen=True, slots=True)
class FullTextSearch:
    query: str
    fields: tuple[str, ...]

    def compile_sa_query(self, ctx):
        # PostgreSQL tsvector full-text search
        tsvector = func.to_tsvector("english", *[getattr(ctx.model, f) for f in self.fields])
        return replace(ctx, stmt=ctx.stmt.where(tsvector.match(self.query)))

    def compile_http_api(self, ctx):
        ctx.params["q"] = self.query
        return ctx

    def compile_memory_query(self, ctx):
        # NOT a silent skip — an explicit, descriptive rejection
        raise NotImplementedError(
            f"FullTextSearch('{self.query}') requires full-text indexing. "
            f"In-memory backend cannot provide tsvector/trigram search. "
            f"Use SQLAlchemy with PostgreSQL or an HTTP API."
        )
```

Note the three-level choice for each backend: FullTextSearch IMPLEMENTS compile_sa_query (full support), IMPLEMENTS compile_http_api (full support), and IMPLEMENTS compile_memory_query with a raise (explicit rejection). A fourth option — simply not implementing compile_memory_query — would cause fold to skip silently, which would be wrong here: the user asked for full-text search, and the memory backend cannot provide it. Silence would hide a real problem. The explicit raise surfaces it.

This is the same three-option pattern from Section 1.1.6: implement (support), implement-with-raise (reject explicitly), or don't implement (skip as irrelevant). The programmer chooses per capability per backend.

This is the Expression Problem solved: new operations (FullTextSearch) and new backends (GraphDB) added without modifying existing code. AND the data is inspectable — unlike tagless final, where the data is opaque functions. AND incompatibilities are explicit — unlike silent degradation, where the system appears to work but produces wrong results.

---

## 2.5 Systems with Generic Operations

In the previous sections, we introduced protocol-directed compilation as a way to deal with multiple representations. The key idea is that data objects carry their own compilation methods, and fold dispatches based on protocol conformance.

In this section we will see how to use this idea to define operations that are generic over the *axis* of compilation — schema, surface, storage, query — not just the backend within an axis.

### 2.5.1 The Encoding is Fractal

Consider what we have seen so far:

| Domain | Items | Context | Protocol | What fold produces |
|--------|-------|---------|----------|--------------------|
| Schema | MaxLen, Unique, Identity | PydanticContext | PydanticCompilable | Field config |
| Query | Filter, OrderBy, Limit | MemoryQueryContext | MemoryQueryCompilable | Filtered data |
| Derive | CRUD, Paginated, SoftDelete | DeriveCtx | DeriveGeneratable | OpSpecs |
| Surface | Tag, Auth, RateLimit | FastAPIRouteContext | FastAPICompilable | Route config |
| Verify | Min, Max, MinLen, MaxLen | NumericVerifyCtx | NumericVerifyCompilable | Issues |
| Runtime | WorkStealing caps | WorkStealingContext | WorkStealingCompilable | Node traits |
| World | Computations | WorldContext | WorldCompilable | nodnod nodes |
| Algebra | Num, Add, Mul, Sin | PythonCtx | PythonCompilable | Python source |

Eight domains. One fold. The same six lines.

This is not a coincidence. It is a consequence of the encoding: frozen dataclass + compile_* methods + isinstance dispatch. Any domain where data can be represented as a sequence of frozen objects that know how to transform a target context can use fold. The domain provides the items and the context. fold provides the traversal and the dispatch. The algebraic laws — universality, fusion, banana split — hold regardless of domain.

### 2.5.2 Combining Domains

The power of the generic approach becomes evident when we combine operations from different domains. Consider a compilation that involves both schema and query:

```python
@derive(http_crud("/users", Users), Paginated(20), SoftDelete("deleted_at"))
@dataclass
class User:
    id: Annotated[int, Identity]
    name: str
    balance: Annotated[float, Min(0)]
    deleted_at: datetime | None = None
```

This single declaration involves:
- **Schema fold:** MaxLen, Min, Identity → PydanticContext, OpenAPIContext, SQLAlchemyContext
- **Derive fold:** CRUD → OpSpecs → Paginated modifies List → SoftDelete modifies Delete and adds filter to reads
- **Query fold:** SoftDelete attaches a filter `lambda u: u.deleted_at.is_null()` to the base query → Filter(IsNull(Field("deleted_at")))
- **Verification fold:** Min(0) → NumericVerifyCtx → check() → no issues
- **Surface fold:** error capabilities → FastAPIRouteContext → RFC 7807 error responses

Five fold operations. Five different contexts. Five different protocols. One declaration. The domains are orthogonal — each fold operates independently, producing its own result. The results combine at materialization into a single endpoint with correct validation, OpenAPI docs, soft-delete behavior, pagination, and error handling.

This is the generic system at work: not a single fold doing everything, but multiple independent folds, each specialized to its domain, composed at the architectural level through the wire Application and compilation targets.

### 2.5.3 Symbolic Algebra as Generic System

To close this chapter, we return to the symbolic algebra example — not as a demonstration of emergent's features, but as evidence that the encoding is genuinely generic.

The algebra system defines expression nodes as frozen dataclasses. Each node carries compile_python, compile_latex, compile_eval, compile_deriv. Four targets. Four contexts. Four protocols. One fold.

The algebra system has nothing to do with web APIs, databases, or HTTP routes. It is pure symbolic mathematics. And yet it uses the same fold. The same isinstance dispatch. The same pattern of frozen-dataclass-with-compile-methods.

This is the claim of the chapter: data abstraction, the closure property, symbolic data, multiple representations, and generic operations are not features of emergent. They are consequences of the encoding — frozen dataclass + compile_* + fold. The encoding is domain-independent. Any domain that can represent its operations as frozen data with compile methods can use it. The algebraic laws follow from the mathematics. The open-world dispatch follows from isinstance. The additivity follows from Protocol.

In Chapter 3, we will confront the one thing the encoding does not naturally handle: *time*. Capabilities are immutable. Contexts are frozen. Compilation is deterministic. But real systems change. Users create accounts. Workers die. Markets move. How do we model a changing world with immutable data? The answer — theworld's append-only Log — will introduce the third great idea of this book, after capabilities and data abstraction: the idea that state is not something you have, but something you observe.

---

## Exercises

**Exercise 2.1.** Implement a query expression `Between(field, low, high)` as a frozen dataclass that evaluates to `low <= getattr(obj, field) <= high`. Implement `compile_memory_query` (filter the data list) and `compile_sa_query` (produce a BETWEEN clause). Show that Between can be expressed as `And(Ge(Field(f), Const(low)), Le(Field(f), Const(high)))` — what is the advantage of having Between as a primitive rather than only as a derived form?

**Exercise 2.2.** The expr_to_dict function serializes an expression AST to a JSON-compatible dict. Design and implement expr_from_dict — the inverse. What information must be preserved in the dict for the round-trip to be lossless? Is the round-trip always lossless, or are there expressions for which `expr_from_dict(expr_to_dict(e)) != e`?

**Exercise 2.3.** The closure property says that combining data objects produces something that can itself be combined. For SchemaCompiler, `A + B` is a SchemaCompiler. But is `FASTAPI_SCHEMA + FASTAPI_SCHEMA` the same as `FASTAPI_SCHEMA`? (Hint: `+` is left-biased union, keyed by context_type.) What algebraic property does this demonstrate? Design a compiler composition where `A + B ≠ B + A` — what does this tell you about the `+` operation?

**Exercise 2.4.** The query proxy trick — `lambda u: u.balance > 100` producing `Gt(Field("balance"), Const(100))` — relies on `__gt__` returning a frozen AST node instead of a boolean. What happens if the user writes `lambda u: u.balance > u.credit_limit`? Both sides are FieldProxy objects. Trace through the proxy method calls and show what AST is produced. Is the result correct? What about `lambda u: 100 < u.balance`? (Hint: consider `__lt__` vs `__rlt__`.)

**Exercise 2.5.** The simplify_expr function applies boolean algebra optimizations: `And(x, True) → x`, `Or(x, False) → x`, `Not(Not(x)) → x`. Design three additional simplification rules that would be useful for query optimization. Implement them and show that they preserve the semantics (the simplified expression evaluates the same as the original on any input).

**Exercise 2.6.** Swierstra (2008) solves the Expression Problem using coproducts of functors: `Expr (Val :+: Add :+: Mul)`. emergent uses tuples: `(MaxLen(255), Unique, sql.Index())`. The coproduct approach supports recursive nesting (Add has Expr children). The tuple approach is flat. Construct a scenario in emergent where you NEED nesting — capabilities inside capabilities. How would you represent it? What breaks? Is there a way to achieve the effect without changing the encoding? (Hint: consider scoped().)

**Exercise 2.7.** The algebra example implements compile_deriv for Mul using the product rule. Extend the algebra system with a new expression type `Integral(expr, var)` that represents definite integration. You cannot implement compile_eval for Integral in closed form (integration is harder than differentiation). Design a compile_eval that uses numerical quadrature (e.g., Simpson's rule). Show that the same expression compiles to different things for different targets: compile_latex produces integral notation, compile_python produces a numerical integration function call, compile_eval produces a number.

**Exercise 2.8.** The multiple-representations pattern (2.4) shows Filter with four compile_* methods: compile_memory_query, compile_sa_query, compile_memory_api, compile_http_api. Design a fifth backend: compile_elasticsearch. What does the context look like? How does Filter.compile_elasticsearch translate `Gt(Field("balance"), Const(100))` to an Elasticsearch query DSL? What Lens ops would an Elasticsearch backend need to support?

**Exercise 2.9.** Data abstraction (2.1) separates "how data is used" from "how data is represented." The query expression AST is one representation. An alternative representation is a tuple-based encoding: `("gt", "balance", 100)` instead of `Gt(Field("balance"), Const(100))`. What are the trade-offs? Which representation is more amenable to serialization? To simplification? To backend compilation? To type checking? Design a translation between the two representations and show that the round-trip is faithful.

**Exercise 2.10.** In 2.5.1, we showed the "fractal encoding" table with eight domains all using fold. For each domain, identify the *dual* operation — the operation that PRODUCES items rather than consuming them. (Hint: for schema compilation, the "producer" is `Annotated` which assembles the capability tuple. For derivation, the "producer" is compile_derive_generate which produces OpSpecs.) Is there a pattern to the producers? Is there an emergent analog of Meijer's *anamorphism* (the dual of catamorphism)?

**Exercise 2.11.** The TargetCompiler algebra mirrors the SchemaCompiler algebra: `+`, `-`, `&`, `|`. But TargetCompiler is keyed by codec_type, not context_type. Design a "universal compiler" that composes SchemaCompiler and TargetCompiler into a single algebra. What is the natural identity key for the combined algebra? Is the combined algebra still a keyed set, or does it need a richer structure?

**Exercise 2.12.** SICP 2.3.2 implements symbolic differentiation of algebraic expressions. The emergent algebra example does the same. But SICP's differentiator uses a recursive function with cond dispatch on expression type. emergent's uses fold with isinstance dispatch. Compare the two approaches: (a) which is more extensible (adding a new expression type)? (b) which is more modular (adding a new compilation target)? (c) which gives better error messages when an expression type is unknown? (d) which is easier to trace/debug?