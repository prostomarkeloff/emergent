"""Transform capabilities — compile-time and runtime transforms.

    from emergent.wire.axis.surface import transforms

    endpoint(runner).expose(
        trigger,
        rrc(Request, Response),
        transforms.Prefix.of("api", "v1"),
        transforms.AsDict(),
    )
"""

from emergent.wire.axis.surface.transforms._base import (
    TriggerTransform,
    HandlerTransform,
    ResponseTransform,
)

from emergent.wire.axis.surface.transforms._trigger import (
    URLPath,
    Prefix,
    StripPrefix,
)

from emergent.wire.axis.surface.transforms._handler import (
    Timeout,
)

from emergent.wire.axis.surface.transforms._response import (
    # Protocols
    HasToDict,
    HasAsDict,
    HasModelDump,
    HasDict,
    DataclassInstance,
    DictConvertible,
    # Functions
    to_dict_from_protocol,
    try_convert_to_dict,
    is_dict_convertible,
    convert_dataclass_to_dict,
    # Capabilities
    AsDict,
    AsStr,
    Transform,
    TransformAsync,
)


__all__ = (
    # Protocols
    "TriggerTransform",
    "HandlerTransform",
    "ResponseTransform",
    # Trigger transforms
    "URLPath",
    "Prefix",
    "StripPrefix",
    # Handler transforms
    "Timeout",
    # Response protocols
    "HasToDict",
    "HasAsDict",
    "HasModelDump",
    "HasDict",
    "DataclassInstance",
    "DictConvertible",
    # Response functions
    "to_dict_from_protocol",
    "try_convert_to_dict",
    "is_dict_convertible",
    "convert_dataclass_to_dict",
    # Response transforms
    "AsDict",
    "AsStr",
    "Transform",
    "TransformAsync",
)
