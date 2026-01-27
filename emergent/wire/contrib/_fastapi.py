from typing import Annotated, Any, TypeGuard
import fastapi
from kungfu import Result

from emergent.ops._graph import Runner
from emergent.wire._app import Application
from emergent.wire._endpoint import Endpoint
from emergent.wire._types import Codec, Trigger
from emergent.wire.codecs.rrc import RequestResponseCodec
from emergent.wire.triggers.http import HTTPRouteTrigger, Path


def is_target(tc: tuple[Trigger, Codec]) -> TypeGuard[tuple[Trigger, Codec]]:
    return not (
        isinstance(tc[0], HTTPRouteTrigger) or isinstance(tc[1], RequestResponseCodec)
    )


def compile_to_fastapi_route(
    endp: Endpoint,
) -> list[tuple[str, Path, Any]]:  # (method, path, route_func)
    routes: list[tuple[str, str, Any]] = []

    for exposure in endp.exposures:
        trigger, codec = exposure

        if is_target(exposure):
            continue

        http_trigger = trigger
        req_resp_codec = codec

        req_type = req_resp_codec.request
        resp_type = req_resp_codec.response

        def make_handler(
            req_cls: type[Any],
            resp_cls: type[Any],
            runner: Runner,
        ) -> Any:
            async def _route_handler(req: Any) -> Any:
                domain_op: Op[Any, Any] = req.to_domain()  # type: ignore[attr-defined]
                result: Result[Any, Any] = await runner.run(domain_op)  # type: ignore
                return resp_cls.from_domain(result)  # type: ignore[attr-defined,no-any-return]

            # TODO: improve compiler. that's the simplest edge-case
            if http_trigger.method == "GET":
                req_cls = Annotated[req_cls, fastapi.Query()]  # type: ignore

            _route_handler.__annotations__ = {
                "req": req_cls,
                "return": resp_cls,
            }

            return _route_handler

        handler = make_handler(req_type, resp_type, endp.runner)

        routes.append((http_trigger.method.upper(), http_trigger.path, handler))

    return routes


def add_endpoint_to_app(
    app: fastapi.FastAPI,
    endp: Endpoint,
) -> None:
    for method, path, handler in compile_to_fastapi_route(endp):
        route_method = getattr(app, method.lower(), None)
        if route_method is None:
            raise ValueError(f"Unsupported HTTP method: {method}")

        route_method(path)(handler)


def from_application(app: Application) -> fastapi.FastAPI:
    f_app = fastapi.FastAPI()

    for endp in app.endpoints:
        add_endpoint_to_app(f_app, endp)

    return f_app
