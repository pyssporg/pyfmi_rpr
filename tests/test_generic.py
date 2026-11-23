"""Generic wire payload encode/decode through the packaged schema bundle."""

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
from pyfmi_interop.wire import decode as wire_decode  # noqa: E402

from pyfmi_rpr.bundle import plan_from_bundle  # noqa: E402
from pyfmi_rpr.codec import to_rpr  # noqa: E402
from pyfmi_rpr.errors import GenericWireError  # noqa: E402
from pyfmi_rpr.generic import (  # noqa: E402
    decode_generic,
    decode_generic_frame,
    encode_generic_frame,
    encode_generic_inputs,
)
from pyfmi_rpr.manifest import AdapterManifest, EntityIdentity, Origin  # noqa: E402

_MAPPING = {
    "px": "position.x",
    "py": "position.y",
    "pz": "position.z",
    "vx": "velocity.x",
    "label": "marking",
    "force": "force",
    "set_vx": "velocity.x",
}


def make_model(name: str = "generic_model") -> ModelDefinition:
    signals = (
        Signal("px", 1, DataType.REAL, Direction.OUTPUT),
        Signal("py", 2, DataType.REAL, Direction.OUTPUT),
        Signal("pz", 3, DataType.REAL, Direction.OUTPUT),
        Signal("vx", 4, DataType.REAL, Direction.OUTPUT),
        Signal("label", 5, DataType.STRING, Direction.OUTPUT, capacity=11),
        Signal("force", 6, DataType.INTEGER, Direction.OUTPUT),
        Signal("set_vx", 7, DataType.REAL, Direction.INPUT),
    )
    return ModelDefinition(
        name=name,
        guid=deterministic_guid(name),
        step_size_s=0.01,
        signals=signals,
    )


def make_manifest() -> AdapterManifest:
    return AdapterManifest(
        identity=EntityIdentity(site=1, application=2, entity=3, marking="ALPHA"),
        origin=Origin(57.7, 12.9, 100.0),
        mapping=_MAPPING,
    )


def make_plan(tmp_path, name: str = "generic_model"):
    model = make_model(name)
    write_schema(model, tmp_path / name)
    return plan_from_bundle(tmp_path / name, make_manifest())


def test_generic_frame_round_trip_uses_the_packaged_wire_json(tmp_path) -> None:
    plan = make_plan(tmp_path)
    values = {
        "px": 12.5,
        "py": -3.25,
        "pz": 88.0,
        "vx": 4.5,
        "label": "ALPHA",
        "force": 2,
    }

    frame = encode_generic_frame(
        plan, values, instance=7, sequence=42, timestamp_ns=1_700_000_000_000_000_000
    )
    decoded = decode_generic(plan, frame)

    assert decoded.header.instance == 7
    assert decoded.header.sequence == 42
    assert decoded.header.timestamp_ns == 1_700_000_000_000_000_000
    assert decoded.header.model_id.hex() == plan.model_id
    assert decode_generic_frame(plan, frame) == {**values, "set_vx": 0.0}



def test_generic_frame_is_byte_deterministic(tmp_path) -> None:
    plan = make_plan(tmp_path)
    values = {"px": 1.0, "py": 2.0, "pz": 3.0, "vx": 0.0, "label": "", "force": 0}

    first = encode_generic_frame(
        plan, values, instance=1, sequence=2, timestamp_ns=3
    )
    second = encode_generic_frame(
        plan, values, instance=1, sequence=2, timestamp_ns=3
    )
    later = encode_generic_frame(
        plan, values, instance=1, sequence=2, timestamp_ns=4
    )

    assert first == second
    assert wire_decode(first).payload == wire_decode(later).payload


def test_frame_from_another_model_is_rejected(tmp_path) -> None:
    plan = make_plan(tmp_path, "generic_one")
    other = make_plan(tmp_path, "generic_other")
    frame = encode_generic_frame(
        plan, {"px": 1.0}, instance=1, sequence=1, timestamp_ns=1
    )

    with pytest.raises(GenericWireError, match="model id"):
        decode_generic(other, frame)


def test_rpr_to_generic_inputs_round_trip(tmp_path) -> None:
    plan = make_plan(tmp_path)
    values = {
        "px": 0.0,
        "py": 0.0,
        "pz": 0.0,
        "vx": 9.5,
        "label": "",
        "force": 1,
    }

    payload = to_rpr(plan, values, 0.0)
    frame = encode_generic_inputs(
        plan, payload, instance=1, sequence=1, timestamp_ns=1
    )
    decoded = decode_generic_frame(plan, frame)

    assert decoded["set_vx"] == pytest.approx(9.5, abs=1e-4)
