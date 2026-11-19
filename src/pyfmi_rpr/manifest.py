"""The adapter's own input model: identity, origin, frames and mapping.

A federation manifest describes one *instance*, never the model.  The model
definition is reusable and carries no entity; this manifest supplies the RPR
identity triple ``(site, application, entity)``, the marking, the force and the
exercise, plus the WGS84 origin of the local frame and the signal-to-RPR
mapping.  Identity is therefore data the launcher owns, not something the model
interface can leak into the wire.

The origin is explicit and required.  There is deliberately no global or
process-wide origin: two instances in one process may use different local
frames, and a hidden default would make a frame difference undebuggable.

``frame`` declares how the model's position, linear velocity and linear
acceleration are expressed: ``enu`` (metres relative to ``origin``) or ``ecef``
(geocentric metres).  RPR itself is always ECEF position plus body-frame
velocity, acceleration and angular velocity; :mod:`pyfmi_rpr.codec` performs the
conversion at the wire boundary.

The mapping is a JSON object of ``signal name -> RPR attribute``.  Aliases such
as ``position.x``, ``velocity.y``, ``orientation.yaw``, ``angular_velocity.z``,
``acceleration.x``, ``marking``, ``force``, ``dr.algorithm`` and
``platform.kind`` are accepted and canonicalised by
:mod:`pyfmi_rpr.projection`.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .errors import ManifestError

__all__ = [
    "AdapterManifest",
    "EntityIdentity",
    "Frame",
    "Origin",
    "load_manifest",
    "manifest_from_mapping",
]

_FORCE_NAMES = {
    "force_other": 0,
    "force_friendly": 1,
    "force_opposing": 2,
    "force_neutral": 3,
    "other": 0,
    "friendly": 1,
    "opposing": 2,
    "neutral": 3,
}

_PLATFORM_NAMES = {
    "platform_kind_unknown": 0,
    "platform_fixed_wing": 1,
    "platform_rotary_wing": 2,
    "platform_unmanned_aircraft": 3,
    "platform_spacecraft": 4,
    "platform_surface_vessel": 5,
    "platform_submersible": 6,
    "platform_ground_vehicle": 7,
    "unknown": 0,
    "fixed_wing": 1,
    "rotary_wing": 2,
    "unmanned_aircraft": 3,
    "spacecraft": 4,
    "surface_vessel": 5,
    "submersible": 6,
    "ground_vehicle": 7,
}

_ALGORITHM_NAMES = {
    "dr_algorithm_other": 0,
    "dr_algorithm_static": 1,
    "dr_algorithm_fpw": 2,
    "dr_algorithm_fvw": 3,
    "dr_algorithm_fpb": 4,
    "dr_algorithm_fvb": 5,
    "dr_algorithm_rpw": 6,
    "dr_algorithm_rvw": 7,
    "dr_algorithm_rpb": 8,
    "dr_algorithm_rvb": 9,
    "other": 0,
    "static": 1,
    "fpw": 2,
    "fvw": 3,
    "fpb": 4,
    "fvb": 5,
    "rpw": 6,
    "rvw": 7,
    "rpb": 8,
    "rvb": 9,
}

_MESSAGE_TYPES = {
    "physicalentity": "PhysicalEntity",
    "platform": "Platform",
    "aircraft": "Aircraft",
}

_MANIFEST_KEYS = {
    "identity",
    "origin",
    "frame",
    "mapping",
    "entity_type",
    "platform_kind",
    "message_type",
    "dead_reckoning_algorithm",
    "dead_reckoning_parameters",
    "is_frozen",
}

_IDENTITY_KEYS = {"site", "application", "entity", "marking", "force", "exercise", "character_set"}
_ORIGIN_KEYS = {"latitude_deg", "longitude_deg", "altitude_m"}


class Frame(str, Enum):
    """Frame the model uses for position and linear kinematics."""

    ENU = "enu"
    ECEF = "ecef"


@dataclass(frozen=True)
class Origin:
    """WGS84 geodetic origin of the local east-north-up frame."""

    latitude_deg: float
    longitude_deg: float
    altitude_m: float

    def __post_init__(self) -> None:
        _require_finite(self.latitude_deg, "origin.latitude_deg")
        _require_finite(self.longitude_deg, "origin.longitude_deg")
        _require_finite(self.altitude_m, "origin.altitude_m")
        if not -90.0 <= self.latitude_deg <= 90.0:
            raise ManifestError("origin.latitude_deg must be between -90 and 90")
        if not -180.0 <= self.longitude_deg <= 180.0:
            raise ManifestError("origin.longitude_deg must be between -180 and 180")


@dataclass(frozen=True)
class EntityIdentity:
    """The RPR identity and attributes of one launched instance.

    ``exercise`` is carried for federation bookkeeping.  ``pysos_rpr`` 0.1.0 has
    no exercise field, so it is not encoded into RPR messages; this is the same
    drop documented by ``pysos_interop.rpr``.
    """

    site: int
    application: int
    entity: int
    marking: str = ""
    force: int = 1
    exercise: int = 1
    character_set: int = 1

    def __post_init__(self) -> None:
        _require_int(self.site, "identity.site", 0, 65535)
        _require_int(self.application, "identity.application", 0, 65535)
        _require_int(self.entity, "identity.entity", 0, 65535)
        _require_int(self.exercise, "identity.exercise", 0, 255)
        _require_int(self.character_set, "identity.character_set", 0, 255)
        if not isinstance(self.marking, str):
            raise ManifestError("identity.marking must be a string")
        if not self.marking.isprintable():
            raise ManifestError("identity.marking must be printable text")
        if len(self.marking.encode("utf-8")) > 11:
            raise ManifestError("identity.marking must be at most 11 UTF-8 octets")
        object.__setattr__(self, "force", _force_value(self.force))

    @property
    def entity_id(self) -> str:
        """Return the opaque ``site:application:entity`` identity string."""

        return f"{self.site}:{self.application}:{self.entity}"


@dataclass(frozen=True)
class AdapterManifest:
    """Input model of one adapter instance: identity, origin, frame, mapping."""

    identity: EntityIdentity
    origin: Origin
    mapping: Mapping[str, str] = field(default_factory=dict)
    frame: Frame = Frame.ENU
    entity_type: tuple[int, ...] = (1, 2, 0, 0, 0, 0, 0)
    platform_kind: int = 0
    message_type: str = "PhysicalEntity"
    dead_reckoning_algorithm: int | None = None
    dead_reckoning_parameters: bytes = b""
    is_frozen: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.identity, EntityIdentity):
            raise ManifestError("identity must be an EntityIdentity")
        if not isinstance(self.origin, Origin):
            raise ManifestError("origin must be an Origin")
        if not isinstance(self.frame, Frame):
            try:
                frame = Frame(self.frame)
            except (TypeError, ValueError) as exc:
                raise ManifestError("frame must be 'enu' or 'ecef'") from exc
            object.__setattr__(self, "frame", frame)

        if not isinstance(self.mapping, Mapping):
            raise ManifestError("mapping must be a string-to-string object")
        normalized: dict[str, str] = {}
        for key, value in self.mapping.items():
            if not isinstance(key, str) or not key:
                raise ManifestError("mapping keys must be non-empty signal names")
            if not isinstance(value, str) or not value:
                raise ManifestError(f"mapping for signal {key!r} must be a non-empty string")
            normalized[key] = value
        object.__setattr__(self, "mapping", MappingProxyType(normalized))

        object.__setattr__(self, "entity_type", _entity_type(self.entity_type))
        object.__setattr__(self, "platform_kind", _platform_value(self.platform_kind))
        object.__setattr__(self, "message_type", _message_type(self.message_type))
        object.__setattr__(
            self,
            "dead_reckoning_algorithm",
            _algorithm_value(self.dead_reckoning_algorithm),
        )
        object.__setattr__(
            self,
            "dead_reckoning_parameters",
            _parameters(self.dead_reckoning_parameters),
        )
        if not isinstance(self.is_frozen, bool):
            raise ManifestError("is_frozen must be a bool")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AdapterManifest":
        """Build a manifest from its strict JSON-shaped mapping."""

        return manifest_from_mapping(data)


def manifest_from_mapping(data: Mapping[str, Any]) -> AdapterManifest:
    """Validate a JSON-shaped manifest and return the typed value.

    Unknown keys are rejected: a silently ignored field is a configuration
    mistake that would surface as a wire difference later.
    """

    if not isinstance(data, Mapping):
        raise ManifestError("manifest must be a JSON object")
    unknown = sorted(set(data) - _MANIFEST_KEYS)
    if unknown:
        raise ManifestError(f"unknown manifest keys: {', '.join(unknown)}")

    identity_data = data.get("identity")
    origin_data = data.get("origin")
    if not isinstance(identity_data, Mapping):
        raise ManifestError("manifest.identity must be an object")
    if not isinstance(origin_data, Mapping):
        raise ManifestError("manifest.origin must be an object")

    identity_unknown = sorted(set(identity_data) - _IDENTITY_KEYS)
    if identity_unknown:
        raise ManifestError(f"unknown identity keys: {', '.join(identity_unknown)}")
    origin_unknown = sorted(set(origin_data) - _ORIGIN_KEYS)
    if origin_unknown:
        raise ManifestError(f"unknown origin keys: {', '.join(origin_unknown)}")
    for key in ("site", "application", "entity"):
        if key not in identity_data:
            raise ManifestError(f"manifest.identity.{key} is required")
    for key in ("latitude_deg", "longitude_deg", "altitude_m"):
        if key not in origin_data:
            raise ManifestError(f"manifest.origin.{key} is required")

    identity = EntityIdentity(
        site=identity_data["site"],
        application=identity_data["application"],
        entity=identity_data["entity"],
        marking=identity_data.get("marking", ""),
        force=identity_data.get("force", 1),
        exercise=identity_data.get("exercise", 1),
        character_set=identity_data.get("character_set", 1),
    )
    origin = Origin(
        latitude_deg=origin_data["latitude_deg"],
        longitude_deg=origin_data["longitude_deg"],
        altitude_m=origin_data["altitude_m"],
    )
    mapping = data.get("mapping", {})
    if not isinstance(mapping, Mapping):
        raise ManifestError("manifest.mapping must be an object")
    entity_type = data.get("entity_type", (1, 2, 0, 0, 0, 0, 0))
    if entity_type is None:
        entity_type = (1, 2, 0, 0, 0, 0, 0)
    return AdapterManifest(
        identity=identity,
        origin=origin,
        mapping=mapping,
        frame=data.get("frame", Frame.ENU),
        entity_type=tuple(entity_type),
        platform_kind=data.get("platform_kind", 0),
        message_type=data.get("message_type", "PhysicalEntity"),
        dead_reckoning_algorithm=data.get("dead_reckoning_algorithm"),
        dead_reckoning_parameters=data.get("dead_reckoning_parameters", b""),
        is_frozen=data.get("is_frozen", False),
    )


def load_manifest(path: str | Path) -> AdapterManifest:
    """Load a manifest from a JSON file."""

    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {source}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest {source} is not valid JSON: {exc}") from exc
    return manifest_from_mapping(data)


def _require_int(value: Any, name: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ManifestError(f"{name} must be between {minimum} and {maximum}")


def _require_finite(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{name} must be a number")
    if not math.isfinite(float(value)):
        raise ManifestError(f"{name} must be finite")


def _force_value(value: Any) -> int:
    if isinstance(value, str):
        key = value.strip().lower()
        if key not in _FORCE_NAMES:
            raise ManifestError(f"identity.force: unknown force name {value!r}")
        return _FORCE_NAMES[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError("identity.force must be an integer or a force name")
    if not 0 <= value <= 3:
        raise ManifestError("identity.force must be between 0 and 3")
    return value


def _platform_value(value: Any) -> int:
    if isinstance(value, str):
        key = value.strip().lower()
        if key not in _PLATFORM_NAMES:
            raise ManifestError(f"platform_kind: unknown platform kind {value!r}")
        return _PLATFORM_NAMES[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError("platform_kind must be an integer or a platform kind name")
    if not 0 <= value <= 7:
        raise ManifestError("platform_kind must be between 0 and 7")
    return value


def _algorithm_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        key = value.strip().lower()
        if key not in _ALGORITHM_NAMES:
            raise ManifestError(f"dead_reckoning_algorithm: unknown name {value!r}")
        return _ALGORITHM_NAMES[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError("dead_reckoning_algorithm must be an integer or a name")
    if not 0 <= value <= 9:
        raise ManifestError("dead_reckoning_algorithm must be between 0 and 9")
    return value


def _parameters(value: Any) -> bytes:
    if isinstance(value, str):
        encoded = value.encode("utf-8")
    elif isinstance(value, (bytes, bytearray, memoryview)):
        encoded = bytes(value)
    else:
        raise ManifestError("dead_reckoning_parameters must be a string or bytes")
    if encoded and len(encoded) != 15:
        raise ManifestError("dead_reckoning_parameters must be empty or exactly 15 octets")
    return encoded


def _entity_type(value: Any) -> tuple[int, ...]:
    if isinstance(value, str) or not isinstance(value, (tuple, list)):
        raise ManifestError("entity_type must be a seven-element sequence")
    if len(value) != 7:
        raise ManifestError("entity_type must have exactly seven octets")
    result = tuple(value)
    for index, item in enumerate(result):
        maximum = 65535 if index == 2 else 255
        _require_int(item, f"entity_type[{index}]", 0, maximum)
    return result


def _message_type(value: Any) -> str:
    if not isinstance(value, str):
        raise ManifestError("message_type must be PhysicalEntity, Platform or Aircraft")
    try:
        return _MESSAGE_TYPES[value.strip().lower()]
    except KeyError as exc:
        raise ManifestError(
            "message_type must be PhysicalEntity, Platform or Aircraft"
        ) from exc
