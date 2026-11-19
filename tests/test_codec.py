"""RPR codec: round trip, determinism and frame parity."""

from __future__ import annotations

import math

import pytest

pytest.importorskip("pysos_rpr")

from pyfmi_interop.ir import (  # noqa: E402
    DataType,
    Direction,
    ModelDefinition,
    Signal,
    deterministic_guid,
)

from pyfmi_rpr import frames  # noqa: E402
from pyfmi_rpr.codec import from_rpr, to_rpr  # noqa: E402
from pyfmi_rpr.errors import CodecError  # noqa: E402
from pyfmi_rpr.manifest import AdapterManifest, EntityIdentity, Frame, Origin  # noqa: E402
from pyfmi_rpr.projection import projection_plan  # noqa: E402

_MAPPING = {
    "px": "position.x",
    "py": "position.y",
    "pz": "position.z",
    "roll": "orientation.roll",
    "pitch": "orientation.pitch",
    "yaw": "orientation.yaw",
    "vx": "velocity.x",
    "vy": "velocity.y",
    "vz": "velocity.z",
    "ax": "acceleration.x",
    "ay": "acceleration.y",
    "az": "acceleration.z",
    "wx": "angular_velocity.x",
    "wy": "angular_velocity.y",
    "wz": "angular_velocity.z",
    "label": "marking",
    "force": "force",
    "kind": "entity_type.kind",
    "dr_alg": "dr.algorithm",
    "dr_params": "dr.parameters",
    "frozen": "is_frozen",
    "platform": "platform.kind",
    "set_vx": "velocity.x",
}


def make_model() -> ModelDefinition:
    real_outputs = (
        "px",
        "py",
        "pz",
        "roll",
        "pitch",
        "yaw",
        "vx",
        "vy",
        "vz",
        "ax",
        "ay",
        "az",
        "wx",
        "wy",
        "wz",
    )
    signals = [
        Signal(name, index, DataType.REAL, Direction.OUTPUT)
        for index, name in enumerate(real_outputs, start=1)
    ]
    signals.extend(
        [
            Signal("label", 16, DataType.STRING, Direction.OUTPUT, capacity=11),
            Signal("force", 17, DataType.INTEGER, Direction.OUTPUT),
            Signal("kind", 18, DataType.INTEGER, Direction.OUTPUT),
            Signal("dr_alg", 19, DataType.INTEGER, Direction.OUTPUT),
            Signal("dr_params", 20, DataType.STRING, Direction.OUTPUT, capacity=15),
            Signal("frozen", 21, DataType.BOOLEAN, Direction.OUTPUT),
            Signal("platform", 22, DataType.INTEGER, Direction.OUTPUT),
            Signal("set_vx", 23, DataType.REAL, Direction.INPUT),
        ]
    )
    return ModelDefinition(
        name="codec_model",
        guid=deterministic_guid("codec_model"),
        step_size_s=0.01,
        signals=tuple(signals),
    )


def make_manifest(**overrides) -> AdapterManifest:
    values = {
        "identity": EntityIdentity(site=1, application=2, entity=3, marking="ALPHA"),
        "origin": Origin(57.7, 12.9, 100.0),
        "mapping": dict(_MAPPING),
        "message_type": "Aircraft",
        "platform_kind": 1,
        "dead_reckoning_algorithm": 4,
        "dead_reckoning_parameters": b"abcdefghijklmno",
    }
    values.update(overrides)
    return AdapterManifest(**values)


def make_values() -> dict:
    return {
        "px": 100.0,
        "py": -250.0,
        "pz": 400.0,
        "roll": 0.1,
        "pitch": -0.2,
        "yaw": 0.7,
        "vx": 30.0,
        "vy": -12.0,
        "vz": 2.5,
        "ax": 0.5,
        "ay": -0.1,
        "az": 0.2,
        "wx": 0.01,
        "wy": -0.02,
        "wz": 0.03,
        "label": "ALPHA",
        "force": 2,
        "kind": 1,
        "dr_alg": 4,
        "dr_params": "abcdefghijklmno",
        "frozen": True,
        "platform": 1,
    }


def test_full_projection_round_trip() -> None:
    plan = projection_plan(make_model(), make_manifest())
    values = make_values()

    decoded = from_rpr(plan, to_rpr(plan, values, 0.0))

    for name in (
        "roll",
        "pitch",
        "yaw",
        "vx",
        "vy",
        "vz",
        "ax",
        "ay",
        "az",
        "wx",
        "wy",
        "wz",
    ):
        assert decoded[name] == pytest.approx(values[name], abs=1e-4)
    for name in ("px", "py", "pz"):
        assert decoded[name] == pytest.approx(values[name], abs=1e-6)
    for name in ("label", "force", "kind", "dr_alg", "dr_params", "frozen", "platform"):
        assert decoded[name] == values[name]
    assert decoded["set_vx"] == pytest.approx(values["vx"], abs=1e-4)


def test_codec_is_deterministic_and_ignores_the_timestamp() -> None:
    plan = projection_plan(make_model(), make_manifest())
    values = make_values()

    first = to_rpr(plan, values, 0.0)
    second = to_rpr(plan, values, 1234.5)

    assert first == second


def test_ecef_frame_round_trip() -> None:
    origin = Origin(57.7, 12.9, 100.0)
    plan = projection_plan(make_model(), make_manifest(frame=Frame.ECEF, origin=origin))
    ecef = frames.enu_to_ecef((100.0, -250.0, 400.0), origin)
    values = {**make_values(), "px": ecef[0], "py": ecef[1], "pz": ecef[2]}

    decoded = from_rpr(plan, to_rpr(plan, values, 0.0))

    assert decoded["px"] == pytest.approx(ecef[0], abs=1e-6)
    assert decoded["py"] == pytest.approx(ecef[1], abs=1e-6)
    assert decoded["pz"] == pytest.approx(ecef[2], abs=1e-6)
    assert decoded["vx"] == pytest.approx(values["vx"], abs=1e-4)


def test_invalid_marking_is_rejected_naming_the_signal() -> None:
    plan = projection_plan(make_model(), make_manifest())
    values = {**make_values(), "label": "x" * 12}

    with pytest.raises(CodecError, match="marking"):
        to_rpr(plan, values, 0.0)


@pytest.mark.parametrize(
    "origin",
    [
        Origin(0.0, 0.0, 0.0),
        Origin(57.7, 12.9, 100.0),
        Origin(-33.9, 151.2, 20.0),
        Origin(89.0, -179.0, 2500.0),
    ],
)
def test_frame_parity_with_pysos_interop_geo(origin) -> None:
    geo = pytest.importorskip("pysos_interop.geo")
    reference = geo.GeoOrigin(origin.latitude_deg, origin.longitude_deg, origin.altitude_m)
    enu = (123.4, -567.8, 90.1)

    local_ecef = frames.enu_to_ecef(enu, origin)
    interop_ecef = geo.enu_to_ecef(enu, reference)
    assert math.dist(local_ecef, interop_ecef) < 1e-6

    back = frames.ecef_to_enu(local_ecef, origin)
    interop_back = geo.ecef_to_enu(interop_ecef, reference)
    assert math.dist(back, interop_back) < 1e-6

    local_geodetic = frames.geodetic_to_ecef(
        origin.latitude_deg, origin.longitude_deg, origin.altitude_m
    )
    interop_geodetic = geo.geodetic_to_ecef(
        origin.latitude_deg, origin.longitude_deg, origin.altitude_m
    )
    assert math.dist(local_geodetic, interop_geodetic) < 1e-6

    velocity = (30.0, -12.0, 2.5)
    local_velocity = frames.enu_vector_to_ecef(velocity, origin)
    interop_velocity = geo.enu_velocity_to_ecef(velocity, reference)
    assert math.dist(local_velocity, interop_velocity) < 1e-6


def test_entity_type_and_marking_character_set_round_trip() -> None:
    fields = ("kind", "domain", "country", "category", "subcategory", "specific", "extra")
    signals = [
        Signal(name, index, DataType.INTEGER, Direction.OUTPUT)
        for index, name in enumerate(fields, start=1)
    ]
    signals.extend(
        [
            Signal("charset", 8, DataType.INTEGER, Direction.OUTPUT),
            Signal("label", 9, DataType.STRING, Direction.OUTPUT, capacity=11),
        ]
    )
    model = ModelDefinition(
        name="entity_type_model",
        guid=deterministic_guid("entity_type_model"),
        step_size_s=0.01,
        signals=tuple(signals),
    )
    mapping = {name: f"entity_type.{name}" for name in fields}
    mapping.update({"charset": "marking.character_set", "label": "marking"})
    manifest = AdapterManifest(
        identity=EntityIdentity(site=1, application=2, entity=3),
        origin=Origin(0.0, 0.0, 0.0),
        mapping=mapping,
    )
    values = {name: index for index, name in enumerate(fields, start=1)}
    values.update({"charset": 2, "label": "TYPE"})
    values["country"] = 752
    plan = projection_plan(model, manifest)

    decoded = from_rpr(plan, to_rpr(plan, values, 0.0))

    assert decoded == values
