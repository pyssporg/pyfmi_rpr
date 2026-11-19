"""Projection of a model definition onto the RPR-derived vocabulary.

The projection is a pure function of the model interface and one
:class:`~pyfmi_rpr.manifest.AdapterManifest`.  It answers two questions for
every non-parameter signal:

* an ``OUTPUT`` publishes an FMU value to one RPR attribute;
* an ``INPUT`` subscribes from one incoming RPR attribute.

``Direction.PARAMETER`` signals are model configuration and are never
projected.  Identity never appears here: it lives on the manifest and is merely
carried by the plan so a caller can build the message without the model ever
holding it.

The canonical target strings are the protobuf paths, for example
``spatial.world_location.x`` or ``spatial.dead_reckoning.algorithm``.  The
manifest may use the shorter aliases listed in :data:`_TARGET_ALIASES`; the plan
always stores the canonical path.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pyfmi_interop.ir import DataType, Direction, ModelDefinition
from pyfmi_interop.schema import SCHEMA_FORMAT_VERSION, payload_message_name
from pyfmi_interop.wire import model_id

from .errors import BundleError, ProjectionPlanError
from .manifest import AdapterManifest, EntityIdentity, Frame, Origin

__all__ = [
    "ProjectionEntry",
    "ProjectionPlan",
    "SignalSpec",
    "plan_from_bundle",
    "projection_plan",
    "resolve_target",
]

# Canonical RPR attribute paths.  Aliases are folded onto these before a plan
# is built, so a caller can compare targets without knowing which spelling the
# manifest used.
_TARGET_ALIASES = {
    "position.x": "spatial.world_location.x",
    "position.y": "spatial.world_location.y",
    "position.z": "spatial.world_location.z",
    "world_location.x": "spatial.world_location.x",
    "world_location.y": "spatial.world_location.y",
    "world_location.z": "spatial.world_location.z",
    "spatial.world_location.x": "spatial.world_location.x",
    "spatial.world_location.y": "spatial.world_location.y",
    "spatial.world_location.z": "spatial.world_location.z",
    "orientation.psi": "spatial.orientation.psi",
    "orientation.theta": "spatial.orientation.theta",
    "orientation.phi": "spatial.orientation.phi",
    "orientation.yaw": "spatial.orientation.psi",
    "orientation.pitch": "spatial.orientation.theta",
    "orientation.roll": "spatial.orientation.phi",
    "attitude.psi": "spatial.orientation.psi",
    "attitude.theta": "spatial.orientation.theta",
    "attitude.phi": "spatial.orientation.phi",
    "attitude.yaw": "spatial.orientation.psi",
    "attitude.pitch": "spatial.orientation.theta",
    "attitude.roll": "spatial.orientation.phi",
    "spatial.orientation.psi": "spatial.orientation.psi",
    "spatial.orientation.theta": "spatial.orientation.theta",
    "spatial.orientation.phi": "spatial.orientation.phi",
    "velocity.x": "spatial.velocity.x",
    "velocity.y": "spatial.velocity.y",
    "velocity.z": "spatial.velocity.z",
    "spatial.velocity.x": "spatial.velocity.x",
    "spatial.velocity.y": "spatial.velocity.y",
    "spatial.velocity.z": "spatial.velocity.z",
    "acceleration.x": "spatial.acceleration.x",
    "acceleration.y": "spatial.acceleration.y",
    "acceleration.z": "spatial.acceleration.z",
    "spatial.acceleration.x": "spatial.acceleration.x",
    "spatial.acceleration.y": "spatial.acceleration.y",
    "spatial.acceleration.z": "spatial.acceleration.z",
    "angular_velocity.x": "spatial.angular_velocity.x",
    "angular_velocity.y": "spatial.angular_velocity.y",
    "angular_velocity.z": "spatial.angular_velocity.z",
    "spatial.angular_velocity.x": "spatial.angular_velocity.x",
    "spatial.angular_velocity.y": "spatial.angular_velocity.y",
    "spatial.angular_velocity.z": "spatial.angular_velocity.z",
    "dead_reckoning.algorithm": "spatial.dead_reckoning.algorithm",
    "dead_reckoning.parameters": "spatial.dead_reckoning.parameters",
    "dr.algorithm": "spatial.dead_reckoning.algorithm",
    "dr.parameters": "spatial.dead_reckoning.parameters",
    "spatial.dead_reckoning.algorithm": "spatial.dead_reckoning.algorithm",
    "spatial.dead_reckoning.parameters": "spatial.dead_reckoning.parameters",
    "is_frozen": "spatial.is_frozen",
    "spatial.is_frozen": "spatial.is_frozen",
    "marking": "marking.characters",
    "marking.characters": "marking.characters",
    "marking.character_set": "marking.character_set",
    "force": "force",
    "entity_type.kind": "entity_type.kind",
    "entity_type.domain": "entity_type.domain",
    "entity_type.country": "entity_type.country",
    "entity_type.category": "entity_type.category",
    "entity_type.subcategory": "entity_type.subcategory",
    "entity_type.specific": "entity_type.specific",
    "entity_type.extra": "entity_type.extra",
    "platform.kind": "platform.kind",
}

_REAL_TARGETS = {
    "spatial.world_location.x",
    "spatial.world_location.y",
    "spatial.world_location.z",
    "spatial.orientation.psi",
    "spatial.orientation.theta",
    "spatial.orientation.phi",
    "spatial.velocity.x",
    "spatial.velocity.y",
    "spatial.velocity.z",
    "spatial.acceleration.x",
    "spatial.acceleration.y",
    "spatial.acceleration.z",
    "spatial.angular_velocity.x",
    "spatial.angular_velocity.y",
    "spatial.angular_velocity.z",
}
_INTEGER_TARGETS = {
    "force",
    "marking.character_set",
    "entity_type.kind",
    "entity_type.domain",
    "entity_type.country",
    "entity_type.category",
    "entity_type.subcategory",
    "entity_type.specific",
    "entity_type.extra",
    "platform.kind",
    "spatial.dead_reckoning.algorithm",
}
_BOOLEAN_TARGETS = {"spatial.is_frozen"}
_STRING_TARGETS = {"marking.characters", "spatial.dead_reckoning.parameters"}

_TARGET_DATA_TYPES: dict[str, set[DataType]] = {
    **{target: {DataType.REAL} for target in _REAL_TARGETS},
    **{target: {DataType.INTEGER} for target in _INTEGER_TARGETS},
    **{target: {DataType.BOOLEAN} for target in _BOOLEAN_TARGETS},
    **{target: {DataType.STRING} for target in _STRING_TARGETS},
}

_FIELD_RE = re.compile(r"^\s*Value\s+(\w+)\s*=\s*(\d+)\s*;\s*$", re.MULTILINE)


@dataclass(frozen=True)
class SignalSpec:
    """One model signal as it appears in the packaged generic wire."""

    name: str
    value_reference: int
    data_type: DataType
    direction: Direction
    capacity: int = 0


@dataclass(frozen=True)
class ProjectionEntry:
    """One IR signal and the canonical RPR attribute it is projected onto."""

    signal_name: str
    value_reference: int
    direction: Direction
    data_type: DataType
    target: str


@dataclass(frozen=True)
class ProjectionPlan:
    """The publish and subscribe entries for one FMU instance.

    The plan is a frozen value.  ``signals`` carries every model signal so the
    generic wire helper can rebuild the payload message even for parameters the
    plan does not project.
    """

    model_name: str
    model_id: str
    payload_message: str
    guid: str
    step_size_s: float
    identity: EntityIdentity
    origin: Origin
    frame: Frame
    entity_type: tuple[int, ...]
    platform_kind: int
    message_type: str
    dead_reckoning_algorithm: int | None
    dead_reckoning_parameters: bytes
    is_frozen: bool
    signals: tuple[SignalSpec, ...]
    publish: tuple[ProjectionEntry, ...]
    subscribe: tuple[ProjectionEntry, ...]

    @property
    def entity_id(self) -> str:
        """Return the opaque federation identity of the plan."""

        return self.identity.entity_id

    @property
    def entries(self) -> tuple[ProjectionEntry, ...]:
        """Return publish then subscribe entries."""

        return self.publish + self.subscribe


@dataclass(frozen=True)
class _ModelView:
    name: str
    model_id: str
    payload_message: str
    guid: str
    step_size_s: float
    signals: tuple[SignalSpec, ...]


def resolve_target(raw: str, *, signal_name: str) -> str:
    """Resolve one manifest attribute spelling to its canonical RPR path."""

    if not isinstance(raw, str) or not raw.strip():
        raise ProjectionPlanError(f"signal {signal_name!r}: target must be a non-empty string")
    key = raw.strip().lower()
    if key.startswith("entity_identifier") or key.startswith("identity") or key == "exercise":
        raise ProjectionPlanError(
            f"signal {signal_name!r}: {raw!r} is manifest-owned identity and cannot be mapped"
        )
    try:
        return _TARGET_ALIASES[key]
    except KeyError as exc:
        raise ProjectionPlanError(
            f"signal {signal_name!r}: unknown RPR attribute {raw!r}"
        ) from exc


def projection_plan(
    source: ModelDefinition | Mapping[str, Any] | str | Path,
    manifest: AdapterManifest,
) -> ProjectionPlan:
    """Resolve every model signal to an RPR attribute under ``manifest``.

    ``source`` is a :class:`~pyfmi_interop.ir.ModelDefinition` or the decoded
    ``wire.json`` mapping.  A path to ``wire.json`` is accepted for
    convenience.  Unknown, duplicate, unmappable or type-incompatible mappings
    raise :class:`~pyfmi_rpr.errors.ProjectionPlanError` naming the signal.
    """

    if not isinstance(manifest, AdapterManifest):
        raise TypeError("manifest must be an AdapterManifest")
    view = _model_view(source)
    by_name = {signal.name: signal for signal in view.signals}
    resolved: dict[str, str] = {}

    for signal_name, raw_target in manifest.mapping.items():
        signal = by_name.get(signal_name)
        if signal is None:
            raise ProjectionPlanError(
                f"mapping names unknown model signal {signal_name!r}"
            )
        if signal.direction is Direction.PARAMETER:
            raise ProjectionPlanError(
                f"signal {signal_name!r}: parameter signals are configuration and are not projected"
            )
        target = resolve_target(raw_target, signal_name=signal_name)
        _check_type(signal, target)
        if target == "platform.kind" and manifest.message_type == "PhysicalEntity":
            raise ProjectionPlanError(
                f"signal {signal_name!r}: platform.kind requires message_type "
                "Platform or Aircraft"
            )
        resolved[signal_name] = target

    publish: list[ProjectionEntry] = []
    subscribe: list[ProjectionEntry] = []
    for signal in view.signals:
        if signal.direction is Direction.PARAMETER:
            continue
        target = resolved.get(signal.name)
        if target is None:
            raise ProjectionPlanError(
                f"signal {signal.name!r}: no RPR mapping in the manifest"
            )
        entry = ProjectionEntry(
            signal_name=signal.name,
            value_reference=signal.value_reference,
            direction=signal.direction,
            data_type=signal.data_type,
            target=target,
        )
        if signal.direction is Direction.OUTPUT:
            publish.append(entry)
        else:
            subscribe.append(entry)

    _reject_duplicates(publish, "publish")
    _reject_duplicates(subscribe, "subscribe")

    return ProjectionPlan(
        model_name=view.name,
        model_id=view.model_id,
        payload_message=view.payload_message,
        guid=view.guid,
        step_size_s=view.step_size_s,
        identity=manifest.identity,
        origin=manifest.origin,
        frame=manifest.frame,
        entity_type=manifest.entity_type,
        platform_kind=manifest.platform_kind,
        message_type=manifest.message_type,
        dead_reckoning_algorithm=manifest.dead_reckoning_algorithm,
        dead_reckoning_parameters=manifest.dead_reckoning_parameters,
        is_frozen=manifest.is_frozen,
        signals=view.signals,
        publish=tuple(sorted(publish, key=lambda item: (item.value_reference, item.signal_name))),
        subscribe=tuple(
            sorted(subscribe, key=lambda item: (item.value_reference, item.signal_name))
        ),
    )


def plan_from_bundle(
    directory: str | Path,
    manifest: AdapterManifest,
) -> ProjectionPlan:
    """Build a plan from a packaged directory containing ``wire.json`` and proto.

    Both artifacts are required and are cross-checked: the ``<Model>.proto``
    must declare exactly the payload message and ``Value`` fields the
    ``wire.json`` descriptor names.  An extracted ``.fmu`` directory with the
    artifacts under ``binaries/<platform>/`` works too.
    """

    root = Path(directory)
    wire_path = _find_one(root, "wire.json")
    try:
        wire_data = json.loads(wire_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"cannot read {wire_path}: {exc}") from exc
    if not isinstance(wire_data, Mapping):
        raise BundleError(f"{wire_path} does not contain a JSON object")
    model_name = wire_data.get("model")
    if not isinstance(model_name, str) or not model_name:
        raise BundleError(f"{wire_path} does not name a model")
    proto_path = _find_one(root, f"{model_name}.proto")
    _check_proto(proto_path, wire_data)
    return projection_plan(wire_data, manifest)


def _model_view(source: ModelDefinition | Mapping[str, Any] | str | Path) -> _ModelView:
    if isinstance(source, ModelDefinition):
        return _view_from_definition(source)
    if isinstance(source, (str, Path)):
        path = Path(source)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectionPlanError(f"cannot read model descriptor {path}: {exc}") from exc
        return _view_from_wire(data)
    if isinstance(source, Mapping):
        return _view_from_wire(source)
    raise TypeError("source must be a ModelDefinition, wire.json mapping or path")


def _view_from_definition(definition: ModelDefinition) -> _ModelView:
    definition.validate()
    signals = tuple(
        SignalSpec(
            name=signal.name,
            value_reference=signal.value_reference,
            data_type=signal.data_type,
            direction=signal.direction,
            capacity=signal.wire_capacity,
        )
        for signal in sorted(definition.signals, key=lambda item: (item.value_reference, item.name))
    )
    return _ModelView(
        name=definition.name,
        model_id=model_id(definition).hex(),
        payload_message=payload_message_name(definition),
        guid=definition.guid,
        step_size_s=definition.step_size_s,
        signals=signals,
    )


def _view_from_wire(data: Mapping[str, Any]) -> _ModelView:
    if not isinstance(data, Mapping):
        raise ProjectionPlanError("wire.json must contain a JSON object")
    format_version = data.get("format_version")
    if format_version != SCHEMA_FORMAT_VERSION:
        raise ProjectionPlanError(
            f"unsupported wire.json format_version {format_version!r}; "
            f"expected {SCHEMA_FORMAT_VERSION}"
        )
    try:
        name = str(data["model"])
        guid = str(data["guid"])
        step_size_s = float(data["step_size_s"])
        encoded_model_id = str(data["model_id"])
        payload_message = str(data["payload_message"])
        raw_signals = data["signals"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectionPlanError(f"wire.json is missing a required field: {exc}") from exc
    if not name or not guid or not payload_message:
        raise ProjectionPlanError("wire.json model, guid and payload_message must be non-empty")
    if not step_size_s > 0:
        raise ProjectionPlanError("wire.json step_size_s must be > 0")
    try:
        bytes.fromhex(encoded_model_id)
    except ValueError as exc:
        raise ProjectionPlanError("wire.json model_id must be hexadecimal") from exc
    if len(bytes.fromhex(encoded_model_id)) != 8:
        raise ProjectionPlanError("wire.json model_id must be 8 bytes (16 hex digits)")
    if not isinstance(raw_signals, list):
        raise ProjectionPlanError("wire.json signals must be a list")

    signals: list[SignalSpec] = []
    for item in raw_signals:
        if not isinstance(item, Mapping):
            raise ProjectionPlanError("wire.json signal entries must be objects")
        try:
            signal = SignalSpec(
                name=str(item["name"]),
                value_reference=int(item["id"]),
                data_type=DataType(item["data_type"]),
                direction=Direction(item["direction"]),
                capacity=int(item.get("capacity", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectionPlanError(f"invalid wire.json signal: {exc}") from exc
        if not signal.name or signal.value_reference <= 0:
            raise ProjectionPlanError("wire.json signal name and id must be positive")
        if signal.capacity < 0:
            raise ProjectionPlanError(f"signal {signal.name!r}: capacity must be >= 0")
        signals.append(signal)

    names = [signal.name for signal in signals]
    ids = [signal.value_reference for signal in signals]
    if len(names) != len(set(names)):
        raise ProjectionPlanError("wire.json contains duplicate signal names")
    if len(ids) != len(set(ids)):
        raise ProjectionPlanError("wire.json contains duplicate value references")

    return _ModelView(
        name=name,
        model_id=encoded_model_id.lower(),
        payload_message=payload_message,
        guid=guid,
        step_size_s=step_size_s,
        signals=tuple(sorted(signals, key=lambda item: (item.value_reference, item.name))),
    )


def _check_type(signal: SignalSpec, target: str) -> None:
    allowed = _TARGET_DATA_TYPES[target]
    if signal.data_type not in allowed:
        expected = ", ".join(sorted(item.value for item in allowed))
        raise ProjectionPlanError(
            f"signal {signal.name!r}: RPR attribute {target!r} expects {expected}, "
            f"not {signal.data_type.value}"
        )


def _reject_duplicates(entries: list[ProjectionEntry], direction: str) -> None:
    seen: dict[str, str] = {}
    for entry in entries:
        previous = seen.get(entry.target)
        if previous is not None:
            raise ProjectionPlanError(
                f"signal {entry.signal_name!r}: duplicate {direction} target "
                f"{entry.target!r} (also mapped from {previous!r})"
            )
        seen[entry.target] = entry.signal_name


def _find_one(root: Path, name: str) -> Path:
    if not root.exists():
        raise BundleError(f"bundle directory does not exist: {root}")
    if root.is_file() and zipfile.is_zipfile(root):
        raise BundleError("pass an extracted FMU directory, not the .fmu archive")
    if not root.is_dir():
        raise BundleError(f"bundle path is not a directory: {root}")
    matches = sorted(path for path in root.rglob(name) if path.is_file())
    if not matches:
        raise BundleError(f"{name} not found under {root}")
    if len(matches) > 1:
        raise BundleError(f"multiple {name} files under {root}: {matches}")
    return matches[0]


def _check_proto(path: Path, wire_data: Mapping[str, Any]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BundleError(f"cannot read {path}: {exc}") from exc
    payload_message = wire_data.get("payload_message")
    if not isinstance(payload_message, str) or f"message {payload_message} {{" not in text:
        raise BundleError(f"{path} does not declare message {payload_message!r}")
    fields = {name: int(identifier) for name, identifier in _FIELD_RE.findall(text)}
    expected = {
        str(item["name"]): int(item["id"])
        for item in wire_data.get("signals", ())
        if isinstance(item, Mapping) and "name" in item and "id" in item
    }
    if fields != expected:
        missing = sorted(set(expected) - set(fields))
        extra = sorted(set(fields) - set(expected))
        mismatched = sorted(
            name for name in set(fields) & set(expected) if fields[name] != expected[name]
        )
        detail = ", ".join(
            part
            for part in (
                f"missing={missing}" if missing else "",
                f"extra={extra}" if extra else "",
                f"id-mismatch={mismatched}" if mismatched else "",
            )
            if part
        )
        raise BundleError(f"{path} Value fields do not match wire.json ({detail})")
