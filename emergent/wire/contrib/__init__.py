"""
Contrib — compilers that translate wire primitives into framework artifacts.

    from emergent.wire.contrib import fastapi
    from emergent.wire.contrib import cli


What is a compiler?
-------------------

A compiler interprets wire's declarative primitives (Application, AppStack)
and produces a native framework artifact — an argparse parser, a FastAPI app,
a gRPC server, an OpenAPI spec, a cron scheduler, etc.

Wire programs declare topology::

    app = application().mount(
        endpoint(runner)
            .expose(CLITrigger("scan", "..."), RequestResponseCodec(Req, Resp))
            .expose(HTTPRouteTrigger("GET", "/scan"), RequestResponseCodec(Req, Resp)),
    )

A single endpoint can carry multiple exposures. Each exposure is a point
in the **Trigger x Codec** product space — the trigger says WHERE to listen,
the codec says HOW to translate between wire and domain. Compilers claim
a region of that space and interpret the matching exposures.


Abstractions
------------

``Trigger``
    Describes where to listen: an HTTP route, a CLI subcommand, a cron
    schedule, an event topic. Each trigger type is a frozen dataclass.

``Codec``
    Describes how to translate between wire and domain AND defines the
    execution semantics. ``RequestResponseCodec`` means single-request,
    single-response. A hypothetical ``StreamingCodec`` would mean
    single-request, stream-of-responses. Each codec module co-locates
    its dataclass with an ``execute`` function::

        from emergent.wire.codecs import rrc
        response = await rrc.execute(handler, request)

    The execute function's signature is determined by the codec type —
    ``rrc.execute`` returns ``FromDomain[Result]``, a streaming codec
    would return ``AsyncIterator``, an event codec would return ``None``.

``Handler[C]``
    Compiled bundle of ``(codec: C, runner: Runner)``. Generic over the
    codec type so the compiler knows what it's working with. Handler
    carries no behavior — it's the typed unit that travels between
    ``scan`` and the compiler's framework bridge.

``scan(app, TriggerType, CodecType?)``
    Extracts ``list[tuple[T, Handler]]`` from an Application. Filters
    the Trigger x Codec product space. Pass both types to claim a
    specific region, or just trigger to get all codecs.

``scan_endpoint(endp, TriggerType, CodecType?)``
    Same as ``scan`` but for a single Endpoint.

``scan_stack(stack, TriggerType, CodecType?)``
    Walks an AppStack recursively, returns a ``StackView[T]`` tree
    of ``(trigger, handler)`` pairs. Eliminates the need to write
    recursive traversal in every compiler.

``StackView[T]``
    Tree of scanned results::

        view.root:   list[tuple[T, Handler]]
        view.mounts: dict[str, StackView[T] | list[tuple[T, Handler]]]


Writing a compiler
------------------

A compiler is a module. No base class, no protocol — just functions
that call ``scan`` and bridge to the target framework.

Step 1: scan for your trigger (and codec) type::

    from emergent.wire._scan import scan
    from emergent.wire.codecs.rrc import RequestResponseCodec

    pairs = scan(app, MyTrigger, RequestResponseCodec)

Step 2: for each (trigger, handler), build a framework-native handler.
Import the codec's execute for the domain pipeline, write the bridge
for framework input/output::

    from emergent.wire.codecs import rrc

    def _wrap(trigger: MyTrigger, handler: Handler[RequestResponseCodec]):
        async def _handle(framework_input):
            request = adapt_input(handler.codec.request, framework_input)
            response = await rrc.execute(handler, request)
            return adapt_output(response)
        return _handle

Step 3: assemble into the framework artifact::

    def from_application(app: Application) -> MyFrameworkApp:
        native = MyFrameworkApp()
        for trigger, handler in scan(app, MyTrigger, RequestResponseCodec):
            native.register(trigger.route, _wrap(trigger, handler))
        return native

For AppStack support, use ``scan_stack`` and recurse over ``StackView``::

    from emergent.wire._scan import scan_stack, StackView

    def from_app_stack(stack: AppStack) -> MyFrameworkApp:
        view = scan_stack(stack, MyTrigger, RequestResponseCodec)
        native = MyFrameworkApp()
        _build(native, view)
        return native

    def _build(native, view: StackView[MyTrigger]):
        for trigger, handler in view.root:
            native.register(trigger.route, _wrap(trigger, handler))
        for prefix, child in view.mounts.items():
            group = native.group(prefix)
            if isinstance(child, StackView):
                _build(group, child)
            else:
                for trigger, handler in child:
                    group.register(trigger.route, _wrap(trigger, handler))

That's it. See ``_cli.py`` and ``_fastapi.py`` for real implementations.
"""

from . import fastapi, cli, telegrinder

__all__ = ("fastapi", "cli", "telegrinder")
