"""RPR codec at the wire boundary.

Translation happens here, not in generated model code.  The generic wire
carries model-specific ``Value`` fields; this module projects those values onto
the RPR-derived vocabulary and back.

Conventions (identical to ``pysos_interop.EntityState`` and
``rpr/v2/spatial.proto``):

* ``Spatial.world_location`` is geocentric ECEF metres.  When the manifest
  declares ``frame = "enu"``, position is local ENU metres relative to the
  manifest origin and is converted here.
* ``Spatial.velocity`` and ``Spatial.acceleration`` are body-frame m/s and
  m/s².  The manifest frame applies to the model side: ENU or ECEF vectors are
  rotated into the body frame using the Euler attitude.
* ``Spatial.orientation`` is Euler ``(psi, theta, phi)`` = ``(yaw, pitch,
  roll)`` radians, Z-Y-X.  ``pysos_interop.EntityState.orientation_rps`` stores
  the same attitude as ``(roll, pitch, yaw)``, so ``phi = roll``,
  ``theta = pitch`` and ``psi = yaw``.
* ``Spatial.angular_velocity`` is body-frame radians per second; the manifest
  frame does not rotate it.

The timestamp ``t`` is a step-boundary argument and is deliberately not encoded:
the RPR vocabulary has no time field.  This module never reads a clock, so
equal values produce equal bytes.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from pysos_rpr import messages as rpr

from .errors import CodecError
from .frames import (
    body_vector_to_enu,
    ecef_to_enu,
    ecef_vector_to_enu,
    enu_to_ecef,
    enu_vector_to_body,
    enu_vector_to_ecef,
)
from .manifest import Frame
from .projection import ProjectionEntry, ProjectionPlan

__all__ = ["from_rpr", "to_rpr"]

_ENTITY_TYPE_FIELDS = (
    "kind",
    "domain",
    "country",
    "category",
    "subcategory",
    "specific",
    "extra",
)


def to_rpr(plan: ProjectionPlan, values: Mapping[str, Any], t: float) -> bytes:
    """Project model ``values`` onto one deterministic RPR payload.

    ``values`` is keyed by signal name.  Every publish entry must carry a value;
    extra keys (parameters, signals this plan does not publish) are ignored.
    ``t`` is accepted at the step boundary and is not encoded.
    """

    del t  # RPR has no time field; accepting t keeps the A3 call shape honest.
    targets = _mapped_values(plan, values)
    message = _message(plan, targets)
    violations = rpr.validate(message)
    if violations:
        raise CodecError("RPR message is not valid: " + "; ".join(violations))
    return rpr.encode(message)


def from_rpr(plan: ProjectionPlan, payload: bytes) -> dict[str, Any]:
    """Decode one RPR payload and return the model values of every plan entry.

    Both publish and subscribe entries are read, so a publish-only plan
    round-trips ``values -> RPR -> values``.  An absent optional RPR component
    yields the documented zero/default rather than an error.
    """

    message_class = _message_class(plan)
    try:
        message = rpr.decode(message_class, payload, strict=True)
    except rpr.RprDecodeError as exc:
        raise CodecError(f"cannot decode {message_class.__name__}: {exc}") from exc
    targets = _target_values(plan, message)
    values: dict[str, Any] = {}
    for entry in plan.entries:
        values[entry.signal_name] = _entry_value(entry, targets[entry.target])
    return values


def _mapped_values(plan: ProjectionPlan, values: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        raise CodecError("values must be a mapping of signal name to value")
    targets: dict[str, Any] = {}
    for entry in plan.publish:
        if entry.signal_name not in values:
            raise CodecError(f"signal {entry.signal_name!r}: missing value")
        targets[entry.target] = _coerce_publish(entry, values[entry.signal_name])
    return targets


def _message(plan: ProjectionPlan, targets: Mapping[str, Any]) -> Any:
    identity = plan.identity
    marking = _marking(targets.get("marking.characters", identity.marking))
    character_set = int(targets.get("marking.character_set", identity.character_set))
    force = int(targets.get("force", identity.force))

    entity_type = list(plan.entity_type)
    for index, field in enumerate(_ENTITY_TYPE_FIELDS):
        entity_type[index] = int(targets.get(f"entity_type.{field}", entity_type[index]))

    base = rpr.base_entity(
        entity_identifier=rpr.entity_identifier(
            site=identity.site,
            application=identity.application,
            entity=identity.entity,
        ),
        entity_type=rpr.entity_type(
            kind=entity_type[0],
            domain=entity_type[1],
            country=entity_type[2],
            category=entity_type[3],
            subcategory=entity_type[4],
            specific=entity_type[5],
            extra=entity_type[6],
        ),
        force=force,
        marking=rpr.marking(marking, character_set=character_set),
    )
    physical = rpr.physical_entity(base=base, spatial=_spatial(plan, targets))
    if plan.message_type == "PhysicalEntity":
        return physical
    platform = rpr.platform(
        physical=physical,
        kind=int(targets.get("platform.kind", plan.platform_kind)),
    )
    if plan.message_type == "Platform":
        return platform
    return rpr.aircraft(platform=platform)


def _spatial(plan: ProjectionPlan, targets: Mapping[str, Any]) -> Any:
    position = (
        _real(targets.get("spatial.world_location.x", 0.0)),
        _real(targets.get("spatial.world_location.y", 0.0)),
        _real(targets.get("spatial.world_location.z", 0.0)),
    )
    if plan.frame is Frame.ENU:
        location = enu_to_ecef(position, plan.origin)
    else:
        location = position

    phi = _real(targets.get("spatial.orientation.phi", 0.0))
    theta = _real(targets.get("spatial.orientation.theta", 0.0))
    psi = _real(targets.get("spatial.orientation.psi", 0.0))
    orientation = (phi, theta, psi)

    velocity = _model_vector(targets, "spatial.velocity")
    acceleration = _model_vector(targets, "spatial.acceleration")
    angular = _model_vector(targets, "spatial.angular_velocity")

    velocity_body = _to_body(velocity, orientation, plan)
    acceleration_body = _to_body(acceleration, orientation, plan)

    algorithm = targets.get(
        "spatial.dead_reckoning.algorithm", plan.dead_reckoning_algorithm
    )
    parameters = targets.get(
        "spatial.dead_reckoning.parameters", plan.dead_reckoning_parameters
    )
    if isinstance(parameters, str):
        parameters = parameters.encode("utf-8")
    dead_reckoning = None
    if algorithm is not None or parameters:
        dead_reckoning = rpr.dead_reckoning(
            algorithm=0 if algorithm is None else int(algorithm),
            parameters=bytes(parameters),
        )

    return rpr.spatial(
        world_location=rpr.world_location(x=location[0], y=location[1], z=location[2]),
        orientation=rpr.orientation(psi=psi, theta=theta, phi=phi),
        velocity=rpr.velocity(x=velocity_body[0], y=velocity_body[1], z=velocity_body[2]),
        acceleration=rpr.acceleration(
            x=acceleration_body[0], y=acceleration_body[1], z=acceleration_body[2]
        ),
        angular_velocity=rpr.angular_velocity(x=angular[0], y=angular[1], z=angular[2]),
        dead_reckoning=dead_reckoning,
        is_frozen=bool(targets.get("spatial.is_frozen", plan.is_frozen)),
    )


def _target_values(plan: ProjectionPlan, message: Any) -> dict[str, Any]:
    physical, platform_kind = _unwrap(plan, message)
    if not physical.HasField("base"):
        raise CodecError("RPR PhysicalEntity is missing base")
    base = physical.base
    spatial = physical.spatial

    if spatial.HasField("world_location"):
        location = spatial.world_location
        ecef = (float(location.x), float(location.y), float(location.z))
        if plan.frame is Frame.ENU:
            position = ecef_to_enu(ecef, plan.origin)
        else:
            position = ecef
    else:
        origin_ecef = enu_to_ecef((0.0, 0.0, 0.0), plan.origin)
        position = (0.0, 0.0, 0.0) if plan.frame is Frame.ENU else origin_ecef

    if spatial.HasField("orientation"):
        phi = float(spatial.orientation.phi)
        theta = float(spatial.orientation.theta)
        psi = float(spatial.orientation.psi)
    else:
        phi = theta = psi = 0.0
    orientation = (phi, theta, psi)

    velocity_body = _component(spatial, "velocity")
    acceleration_body = _component(spatial, "acceleration")
    angular = _component(spatial, "angular_velocity")

    velocity = _from_body(velocity_body, orientation, plan)
    acceleration = _from_body(acceleration_body, orientation, plan)

    algorithm = plan.dead_reckoning_algorithm
    parameters = plan.dead_reckoning_parameters
    if spatial.HasField("dead_reckoning"):
        algorithm = int(spatial.dead_reckoning.algorithm)
        parameters = bytes(spatial.dead_reckoning.parameters)

    if base.HasField("marking"):
        marking = str(base.marking.characters)
        character_set = int(base.marking.character_set)
    else:
        marking = plan.identity.marking
        character_set = plan.identity.character_set

    entity_type = list(plan.entity_type)
    if base.HasField("entity_type"):
        record = base.entity_type
        entity_type = [
            int(record.kind),
            int(record.domain),
            int(record.country),
            int(record.category),
            int(record.subcategory),
            int(record.specific),
            int(record.extra),
        ]

    targets: dict[str, Any] = {
        "spatial.world_location.x": position[0],
        "spatial.world_location.y": position[1],
        "spatial.world_location.z": position[2],
        "spatial.orientation.psi": psi,
        "spatial.orientation.theta": theta,
        "spatial.orientation.phi": phi,
        "spatial.velocity.x": velocity[0],
        "spatial.velocity.y": velocity[1],
        "spatial.velocity.z": velocity[2],
        "spatial.acceleration.x": acceleration[0],
        "spatial.acceleration.y": acceleration[1],
        "spatial.acceleration.z": acceleration[2],
        "spatial.angular_velocity.x": angular[0],
        "spatial.angular_velocity.y": angular[1],
        "spatial.angular_velocity.z": angular[2],
        "spatial.dead_reckoning.algorithm": algorithm,
        "spatial.dead_reckoning.parameters": parameters,
        "spatial.is_frozen": bool(spatial.is_frozen),
        "marking.characters": marking,
        "marking.character_set": character_set,
        "force": int(base.force),
        "platform.kind": platform_kind,
    }
    for index, field in enumerate(_ENTITY_TYPE_FIELDS):
        targets[f"entity_type.{field}"] = entity_type[index]
    return targets


def _unwrap(plan: ProjectionPlan, message: Any) -> tuple[Any, int]:
    if plan.message_type == "Aircraft":
        if not message.HasField("platform") or not message.platform.HasField("physical"):
            raise CodecError("RPR Aircraft is missing platform.physical")
        return message.platform.physical, int(message.platform.kind)
    if plan.message_type == "Platform":
        if not message.HasField("physical"):
            raise CodecError("RPR Platform is missing physical")
        return message.physical, int(message.kind)
    return message, plan.platform_kind


def _component(spatial: Any, name: str) -> tuple[float, float, float]:
    if not spatial.HasField(name):
        return (0.0, 0.0, 0.0)
    component = getattr(spatial, name)
    return (float(component.x), float(component.y), float(component.z))


def _model_vector(targets: Mapping[str, Any], prefix: str) -> tuple[float, float, float]:
    return (
        _real(targets.get(f"{prefix}.x", 0.0)),
        _real(targets.get(f"{prefix}.y", 0.0)),
        _real(targets.get(f"{prefix}.z", 0.0)),
    )


def _to_body(
    vector: tuple[float, float, float],
    orientation: tuple[float, float, float],
    plan: ProjectionPlan,
) -> tuple[float, float, float]:
    if plan.frame is Frame.ENU:
        return enu_vector_to_body(vector, orientation)
    enu = ecef_vector_to_enu(vector, plan.origin)
    return enu_vector_to_body(enu, orientation)


def _from_body(
    vector: tuple[float, float, float],
    orientation: tuple[float, float, float],
    plan: ProjectionPlan,
) -> tuple[float, float, float]:
    enu = body_vector_to_enu(vector, orientation)
    if plan.frame is Frame.ENU:
        return enu
    return enu_vector_to_ecef(enu, plan.origin)


def _coerce_publish(entry: ProjectionEntry, value: Any) -> Any:
    if entry.data_type.value == "real":
        number = _real(value, signal_name=entry.signal_name)
        _check_real_target(entry, number)
        return number
    if entry.data_type.value == "integer":
        number = _integer(value, entry.signal_name)
        _check_integer_target(entry, number)
        return number
    if entry.data_type.value == "boolean":
        if not isinstance(value, bool):
            raise CodecError(f"signal {entry.signal_name!r}: value must be a bool")
        return value
    if not isinstance(value, str):
        raise CodecError(f"signal {entry.signal_name!r}: value must be a string")
    _check_string_target(entry, value)
    return value


def _entry_value(entry: ProjectionEntry, value: Any) -> Any:
    if entry.data_type.value == "real":
        return float(value)
    if entry.data_type.value == "integer":
        return int(value)
    if entry.data_type.value == "boolean":
        return bool(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CodecError(
                f"signal {entry.signal_name!r}: RPR bytes are not UTF-8 text"
            ) from exc
    return str(value)


def _message_class(plan: ProjectionPlan) -> Any:
    return {
        "PhysicalEntity": rpr.PhysicalEntity,
        "Platform": rpr.Platform,
        "Aircraft": rpr.Aircraft,
    }[plan.message_type]


def _real(value: Any, *, signal_name: str | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CodecError(f"signal {signal_name!r}: value must be a real number")
    number = float(value)
    if not math.isfinite(number):
        raise CodecError(f"signal {signal_name!r}: value must be finite")
    return number


def _integer(value: Any, signal_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CodecError(f"signal {signal_name!r}: value must be an integer")
    return value


def _marking(value: Any) -> str:
    if not isinstance(value, str):
        raise CodecError("marking value must be a string")
    if not value.isprintable():
        raise CodecError("marking value must be printable text")
    if len(value.encode("utf-8")) > 11:
        raise CodecError("marking value must be at most 11 UTF-8 octets")
    return value


def _check_real_target(entry: ProjectionEntry, value: float) -> None:
    if not math.isfinite(value):
        raise CodecError(f"signal {entry.signal_name!r}: value must be finite")


def _check_integer_target(entry: ProjectionEntry, value: int) -> None:
    target = entry.target
    if target == "force" and not 0 <= value <= 3:
        raise CodecError(f"signal {entry.signal_name!r}: force must be between 0 and 3")
    if target == "platform.kind" and not 0 <= value <= 7:
        raise CodecError(f"signal {entry.signal_name!r}: platform kind must be 0..7")
    if target == "spatial.dead_reckoning.algorithm" and not 0 <= value <= 9:
        raise CodecError(
            f"signal {entry.signal_name!r}: dead-reckoning algorithm must be 0..9"
        )
    if target == "marking.character_set" and not 0 <= value <= 255:
        raise CodecError(
            f"signal {entry.signal_name!r}: marking character set must be 0..255"
        )
    if target.startswith("entity_type.") and target != "entity_type.country":
        if not 0 <= value <= 255:
            raise CodecError(f"signal {entry.signal_name!r}: entity type octet must be 0..255")
    if target == "entity_type.country" and not 0 <= value <= 65535:
        raise CodecError(f"signal {entry.signal_name!r}: entity type country must be 0..65535")


def _check_string_target(entry: ProjectionEntry, value: str) -> None:
    encoded = value.encode("utf-8")
    if entry.target == "marking.characters":
        _marking(value)
    elif entry.target == "spatial.dead_reckoning.parameters":
        if encoded and len(encoded) != 15:
            raise CodecError(
                f"signal {entry.signal_name!r}: dead-reckoning parameters must be "
                "empty or exactly 15 UTF-8 octets"
            )
