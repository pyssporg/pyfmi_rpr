"""Generic ``pyfmi_interop`` wire payload bridge.

The generated model speaks a generic wire: a 48-byte envelope from
:mod:`pyfmi_interop.wire` around a ``<Model>Payload`` protobuf whose fields are
``Value`` oneofs, described by the packaged ``wire.json``.  This module
reconstructs that payload message dynamically from the plan (no ``protoc`` at
runtime), so the adapter can decode a real model frame, project it, and encode
the model's inputs again without changing generated code.

Encoding is deterministic.  ``instance``, ``sequence`` and ``timestamp_ns`` are
caller-supplied; this module never reads a clock.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import DecodeError
from pyfmi_interop import wire
from pyfmi_interop.ir import DataType, ModelDefinition, Signal

from .codec import from_rpr
from .errors import GenericWireError
from .projection import ProjectionPlan, SignalSpec

__all__ = [
    "GenericFrame",
    "decode_generic",
    "decode_generic_frame",
    "encode_generic_frame",
    "encode_generic_inputs",
]

_PROTO_PACKAGE = "pyfmi_interop.wire"
_FIELD = descriptor_pb2.FieldDescriptorProto

_VALUE_FIELDS = (
    ("real", 1, _FIELD.TYPE_DOUBLE),
    ("integer", 2, _FIELD.TYPE_SINT64),
    ("boolean", 3, _FIELD.TYPE_BOOL),
    ("string", 4, _FIELD.TYPE_BYTES),
)
_KIND_BY_TYPE = {
    DataType.REAL: "real",
    DataType.INTEGER: "integer",
    DataType.BOOLEAN: "boolean",
    DataType.STRING: "string",
}


@dataclass(frozen=True)
class GenericFrame:
    """A decoded generic frame: validation header plus signal values."""

    header: Any
    values: Mapping[str, Any]


def encode_generic_frame(
    plan: ProjectionPlan,
    values: Mapping[str, Any],
    *,
    instance: int,
    sequence: int,
    timestamp_ns: int,
) -> bytes:
    """Encode ``values`` as one generic wire frame for ``plan``.

    Every key in ``values`` must be a model signal.  Missing signals are left at
    their protobuf default, so an input-only frame carries only what it sets.
    """

    if not isinstance(values, Mapping):
        raise GenericWireError("values must be a mapping of signal name to value")
    known = {signal.name: signal for signal in plan.signals}
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise GenericWireError(f"values name unknown model signals: {', '.join(unknown)}")

    message = _message_class(plan)()
    for name, value in values.items():
        signal = known[name]
        _set_value(message, signal, value)

    model = _model_definition(plan)
    return wire.encode(
        model,
        message.SerializeToString(deterministic=True),
        instance=instance,
        sequence=sequence,
        timestamp_ns=timestamp_ns,
    )


def decode_generic(plan: ProjectionPlan, frame: bytes | bytearray | memoryview) -> GenericFrame:
    """Decode and validate one generic wire frame against ``plan``."""

    decoded = wire.decode(frame)
    if decoded.header.model_id != bytes.fromhex(plan.model_id):
        raise GenericWireError(
            f"frame model id {decoded.header.model_id.hex()} does not match "
            f"plan model id {plan.model_id}"
        )
    message = _message_class(plan)()
    try:
        message.ParseFromString(decoded.payload)
    except DecodeError as exc:
        raise GenericWireError(f"cannot decode {plan.payload_message}: {exc}") from exc

    values: dict[str, Any] = {}
    for signal in plan.signals:
        values[signal.name] = _get_value(message, signal)
    return GenericFrame(header=decoded.header, values=MappingProxyType(values))


def decode_generic_frame(
    plan: ProjectionPlan, frame: bytes | bytearray | memoryview
) -> dict[str, Any]:
    """Decode one generic frame and return its signal values as a plain dict."""

    return dict(decode_generic(plan, frame).values)


def encode_generic_inputs(
    plan: ProjectionPlan,
    payload: bytes,
    *,
    instance: int,
    sequence: int,
    timestamp_ns: int,
) -> bytes:
    """Decode an RPR payload and re-encode the model's inputs generically.

    This is the converse seam the bridge drives from the model step loop: RPR
    subscribe values go back into the generic payload for the FMU's inputs.
    """

    decoded = from_rpr(plan, payload)
    inputs = {entry.signal_name: decoded[entry.signal_name] for entry in plan.subscribe}
    return encode_generic_frame(
        plan,
        inputs,
        instance=instance,
        sequence=sequence,
        timestamp_ns=timestamp_ns,
    )


def _model_definition(plan: ProjectionPlan) -> ModelDefinition:
    signals = tuple(
        Signal(
            name=signal.name,
            value_reference=signal.value_reference,
            data_type=signal.data_type,
            direction=signal.direction,
            capacity=signal.capacity,
        )
        for signal in plan.signals
    )
    model = ModelDefinition(
        name=plan.model_name,
        guid=plan.guid,
        step_size_s=plan.step_size_s,
        signals=signals,
    )
    derived = wire.model_id(model).hex()
    if derived != plan.model_id:
        raise GenericWireError(
            f"plan model id {plan.model_id} does not match its signals ({derived})"
        )
    return model


def _message_class(plan: ProjectionPlan) -> Any:
    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = _file_name(plan)
    file_proto.package = _PROTO_PACKAGE
    file_proto.syntax = "proto3"

    value_message = file_proto.message_type.add()
    value_message.name = "Value"
    value_message.oneof_decl.add().name = "kind"
    for name, number, field_type in _VALUE_FIELDS:
        field = value_message.field.add()
        field.name = name
        field.number = number
        field.type = field_type
        field.label = _FIELD.LABEL_OPTIONAL
        field.oneof_index = 0

    payload = file_proto.message_type.add()
    payload.name = plan.payload_message
    for signal in plan.signals:
        field = payload.field.add()
        field.name = signal.name
        field.number = signal.value_reference
        field.type = _FIELD.TYPE_MESSAGE
        field.type_name = f".{_PROTO_PACKAGE}.Value"
        field.label = _FIELD.LABEL_OPTIONAL

    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    descriptor = pool.FindMessageTypeByName(f"{_PROTO_PACKAGE}.{plan.payload_message}")
    return message_factory.GetMessageClass(descriptor)


def _file_name(plan: ProjectionPlan) -> str:
    payload = [
        (signal.name, signal.value_reference, signal.data_type.value)
        for signal in plan.signals
    ]
    digest = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"pyfmi_rpr/{plan.model_name}_{digest}.proto"


def _set_value(message: Any, signal: SignalSpec, value: Any) -> None:
    target = getattr(message, signal.name)
    if signal.data_type is DataType.REAL:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GenericWireError(f"signal {signal.name!r}: value must be a real number")
        number = float(value)
        if not math.isfinite(number):
            raise GenericWireError(f"signal {signal.name!r}: value must be finite")
        target.real = number
    elif signal.data_type is DataType.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise GenericWireError(f"signal {signal.name!r}: value must be an integer")
        target.integer = value
    elif signal.data_type is DataType.BOOLEAN:
        if not isinstance(value, bool):
            raise GenericWireError(f"signal {signal.name!r}: value must be a bool")
        target.boolean = value
    else:
        if not isinstance(value, str):
            raise GenericWireError(f"signal {signal.name!r}: value must be a string")
        encoded = value.encode("utf-8")
        if signal.capacity and len(encoded) > signal.capacity:
            raise GenericWireError(
                f"signal {signal.name!r}: string is {len(encoded)} bytes, "
                f"exceeding capacity {signal.capacity}"
            )
        target.string = encoded


def _get_value(message: Any, signal: SignalSpec) -> Any:
    target = getattr(message, signal.name)
    kind = target.WhichOneof("kind")
    if kind is None:
        return _default(signal)
    expected = _KIND_BY_TYPE[signal.data_type]
    if kind != expected:
        raise GenericWireError(
            f"signal {signal.name!r}: frame carries {kind!r}, expected {expected!r}"
        )
    if signal.data_type is DataType.REAL:
        value = float(target.real)
        if not math.isfinite(value):
            raise GenericWireError(f"signal {signal.name!r}: value must be finite")
        return value
    if signal.data_type is DataType.INTEGER:
        return int(target.integer)
    if signal.data_type is DataType.BOOLEAN:
        return bool(target.boolean)
    try:
        return bytes(target.string).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GenericWireError(
            f"signal {signal.name!r}: string field is not UTF-8"
        ) from exc


def _default(signal: SignalSpec) -> Any:
    if signal.data_type is DataType.REAL:
        return 0.0
    if signal.data_type is DataType.INTEGER:
        return 0
    if signal.data_type is DataType.BOOLEAN:
        return False
    return ""

