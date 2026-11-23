"""End to end: schema bundle -> generic wire frame -> RPR entity state."""

from __future__ import annotations

import pytest

pytest.importorskip("pysos_rpr")

from pyfmi_interop.ir import (  # noqa: E402
    DataType,
    Direction,
    ModelDefinition,
    Signal,
    deterministic_guid,
)
from pyfmi_interop.schema import write_schema  # noqa: E402

from pyfmi_rpr import frames  # noqa: E402
from pyfmi_rpr.bundle import plan_from_bundle  # noqa: E402
from pyfmi_rpr.codec import to_rpr  # noqa: E402
from pyfmi_rpr.generic import decode_generic, encode_generic_frame  # noqa: E402
from pyfmi_rpr.manifest import AdapterManifest, EntityIdentity, Origin  # noqa: E402

_MAPPING = {
    "p_e": "position.x",
    "p_n": "position.y",
    "p_u": "position.z",
    "v_e": "velocity.x",
    "v_n": "velocity.y",
    "v_u": "velocity.z",
    "roll": "orientation.roll",
    "pitch": "orientation.pitch",
    "yaw": "orientation.yaw",
    "w_x": "angular_velocity.x",
    "w_y": "angular_velocity.y",
    "w_z": "angular_velocity.z",
    "label": "marking",
    "force": "force",
}

_VALUES = {
    "p_e": 1000.0,
    "p_n": -2000.0,
    "p_u": 300.0,
    "v_e": 120.0,
    "v_n": -30.0,
    "v_u": 5.0,
    "roll": 0.1,
    "pitch": -0.15,
    "yaw": 0.8,
    "w_x": 0.01,
    "w_y": 0.02,
    "w_z": -0.03,
    "label": "FALCON",
    "force": 2,
}


def make_model() -> ModelDefinition:
    names = ("p_e", "p_n", "p_u", "roll", "pitch", "yaw", "v_e", "v_n", "v_u")
    signals = [
        Signal(name, index, DataType.REAL, Direction.OUTPUT)
        for index, name in enumerate(names, start=1)
    ]
    signals.extend(
        [
            Signal("w_x", 10, DataType.REAL, Direction.OUTPUT),
            Signal("w_y", 11, DataType.REAL, Direction.OUTPUT),
            Signal("w_z", 12, DataType.REAL, Direction.OUTPUT),
            Signal("label", 13, DataType.STRING, Direction.OUTPUT, capacity=11),
            Signal("force", 14, DataType.INTEGER, Direction.OUTPUT),
        ]
    )
    return ModelDefinition(
        name="fixture_aircraft",
        guid=deterministic_guid("fixture_aircraft"),
        step_size_s=0.02,
        signals=tuple(signals),
    )


def make_manifest() -> AdapterManifest:
    return AdapterManifest(
        identity=EntityIdentity(
            site=10, application=20, entity=30, marking="FALCON", force=1, exercise=3
        ),
        origin=Origin(57.7, 12.9, 100.0),
        mapping=_MAPPING,
        message_type="PhysicalEntity",
    )


def test_generic_frame_projects_to_rpr_entity_state(tmp_path) -> None:
    from pysos_rpr import messages

    write_schema(make_model(), tmp_path)
    plan = plan_from_bundle(tmp_path, make_manifest())

    frame = encode_generic_frame(
        plan,
        _VALUES,
        instance=7,
        sequence=42,
        timestamp_ns=1_700_000_000_000_000_000,
    )
    decoded = decode_generic(plan, frame)
    payload = to_rpr(plan, decoded.values, decoded.header.timestamp_ns / 1e9)
    message = messages.decode(messages.PhysicalEntity, payload, strict=True)

    assert message.base.entity_identifier.site == 10
    assert message.base.entity_identifier.application == 20
    assert message.base.entity_identifier.entity == 30
    assert message.base.marking.characters == "FALCON"
    assert message.base.force == 2
    ecef = frames.enu_to_ecef((_VALUES["p_e"], _VALUES["p_n"], _VALUES["p_u"]), plan.origin)
    assert message.spatial.world_location.x == pytest.approx(ecef[0], abs=1e-6)
    assert message.spatial.world_location.y == pytest.approx(ecef[1], abs=1e-6)
    assert message.spatial.world_location.z == pytest.approx(ecef[2], abs=1e-6)
    assert message.spatial.orientation.psi == pytest.approx(0.8, abs=1e-6)
    assert messages.validate(message) == []

    rpr_interop = pytest.importorskip("pysos_interop.rpr")
    state = rpr_interop.decode_entity_state(
        payload,
        origin=rpr_interop.RprOrigin(57.7, 12.9, 100.0),
        message_type=messages.PhysicalEntity,
    )

    assert (state.key.site, state.key.application, state.key.entity) == (10, 20, 30)
    assert state.position_enu_m == pytest.approx(
        (_VALUES["p_e"], _VALUES["p_n"], _VALUES["p_u"]), abs=1e-6
    )
    assert state.velocity_enu_mps == pytest.approx(
        (_VALUES["v_e"], _VALUES["v_n"], _VALUES["v_u"]), abs=1e-4
    )
    assert state.orientation_rps == pytest.approx((0.1, -0.15, 0.8), abs=1e-6)
    assert state.angular_velocity_rps == pytest.approx((0.01, 0.02, -0.03), abs=1e-6)
    assert state.marking == "FALCON"
    assert state.force_id == 2
