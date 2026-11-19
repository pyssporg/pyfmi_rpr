"""Projection plan construction, identity ownership and rejection cases."""

from __future__ import annotations

import json

import pytest
from pyfmi_interop.ir import (
    DataType,
    Direction,
    ModelDefinition,
    Signal,
    deterministic_guid,
)
from pyfmi_interop.schema import render_wire_json, write_schema

from pyfmi_rpr.errors import ProjectionPlanError
from pyfmi_rpr.manifest import AdapterManifest, EntityIdentity, Origin
from pyfmi_rpr.projection import plan_from_bundle, projection_plan

_MAPPING = {
    "p_e": "position.x",
    "p_n": "position.y",
    "p_u": "position.z",
    "roll": "orientation.roll",
    "pitch": "orientation.pitch",
    "yaw": "orientation.yaw",
    "v_e": "velocity.x",
    "v_n": "velocity.y",
    "v_u": "velocity.z",
    "w_x": "angular_velocity.x",
    "w_y": "angular_velocity.y",
    "w_z": "angular_velocity.z",
    "a_e": "acceleration.x",
    "a_n": "acceleration.y",
    "a_u": "acceleration.z",
    "label": "marking",
    "force": "force",
    "kind": "entity_type.kind",
    "country": "entity_type.country",
    "dr_alg": "dr.algorithm",
    "dr_params": "dr.parameters",
    "frozen": "is_frozen",
    "platform": "platform.kind",
}


def make_model() -> ModelDefinition:
    signals = [
        Signal("p_e", 1, DataType.REAL, Direction.OUTPUT),
        Signal("p_n", 2, DataType.REAL, Direction.OUTPUT),
        Signal("p_u", 3, DataType.REAL, Direction.OUTPUT),
        Signal("roll", 4, DataType.REAL, Direction.OUTPUT),
        Signal("pitch", 5, DataType.REAL, Direction.OUTPUT),
        Signal("yaw", 6, DataType.REAL, Direction.OUTPUT),
        Signal("v_e", 7, DataType.REAL, Direction.OUTPUT),
        Signal("v_n", 8, DataType.REAL, Direction.OUTPUT),
        Signal("v_u", 9, DataType.REAL, Direction.OUTPUT),
        Signal("w_x", 10, DataType.REAL, Direction.OUTPUT),
        Signal("w_y", 11, DataType.REAL, Direction.OUTPUT),
        Signal("w_z", 12, DataType.REAL, Direction.OUTPUT),
        Signal("a_e", 13, DataType.REAL, Direction.OUTPUT),
        Signal("a_n", 14, DataType.REAL, Direction.OUTPUT),
        Signal("a_u", 15, DataType.REAL, Direction.OUTPUT),
        Signal("label", 16, DataType.STRING, Direction.OUTPUT, capacity=11),
        Signal("force", 17, DataType.INTEGER, Direction.OUTPUT),
        Signal("kind", 18, DataType.INTEGER, Direction.OUTPUT),
        Signal("country", 19, DataType.INTEGER, Direction.OUTPUT),
        Signal("dr_alg", 20, DataType.INTEGER, Direction.OUTPUT),
        Signal("dr_params", 21, DataType.STRING, Direction.OUTPUT, capacity=15),
        Signal("frozen", 22, DataType.BOOLEAN, Direction.OUTPUT),
        Signal("platform", 23, DataType.INTEGER, Direction.OUTPUT),
        Signal("set_vx", 24, DataType.REAL, Direction.INPUT),
        Signal("mode", 25, DataType.INTEGER, Direction.PARAMETER, initial=2),
    ]
    return ModelDefinition(
        name="demo_model",
        guid=deterministic_guid("demo_model"),
        step_size_s=0.01,
        signals=tuple(signals),
    )


def make_manifest(**overrides) -> AdapterManifest:
    mapping = dict(_MAPPING)
    mapping["set_vx"] = "velocity.x"
    values = {
        "identity": EntityIdentity(
            site=1, application=2, entity=3, marking="ALPHA", force=1, exercise=7
        ),
        "origin": Origin(57.7, 12.9, 100.0),
        "mapping": mapping,
        "message_type": "Aircraft",
        "platform_kind": 1,
        "dead_reckoning_algorithm": 4,
        "dead_reckoning_parameters": b"abcdefghijklmno",
    }
    values.update(overrides)
    return AdapterManifest(**values)


def test_plan_resolves_every_signal_to_a_canonical_target() -> None:
    plan = projection_plan(make_model(), make_manifest())

    assert plan.entity_id == "1:2:3"
    assert plan.frame.value == "enu"
    assert len(plan.publish) == 23
    assert len(plan.subscribe) == 1
    targets = {entry.signal_name: entry.target for entry in plan.publish}
    assert targets["p_e"] == "spatial.world_location.x"
    assert targets["roll"] == "spatial.orientation.phi"
    assert targets["yaw"] == "spatial.orientation.psi"
    assert targets["label"] == "marking.characters"
    assert targets["dr_alg"] == "spatial.dead_reckoning.algorithm"
    assert targets["platform"] == "platform.kind"
    assert plan.subscribe[0].target == "spatial.velocity.x"


def test_identity_change_moves_the_plan_and_not_the_model() -> None:
    model = make_model()
    first = projection_plan(model, make_manifest())
    second = projection_plan(
        model,
        make_manifest(
            identity=EntityIdentity(site=9, application=8, entity=7, marking="BRAVO")
        ),
    )

    assert first.entity_id == "1:2:3"
    assert second.entity_id == "9:8:7"
    assert first.publish == second.publish
    assert model.name == "demo_model"


def test_plan_from_wire_json_matches_plan_from_definition() -> None:
    model = make_model()
    wire_data = json.loads(render_wire_json(model))

    from_json = projection_plan(wire_data, make_manifest())
    from_model = projection_plan(model, make_manifest())

    assert from_json.model_id == from_model.model_id
    assert from_json.publish == from_model.publish
    assert from_json.subscribe == from_model.subscribe
    assert from_json.identity == from_model.identity


def test_plan_from_packaged_bundle_cross_checks_the_proto(tmp_path) -> None:
    model = make_model()
    write_schema(model, tmp_path)

    plan = plan_from_bundle(tmp_path, make_manifest())

    assert plan.model_name == "demo_model"
    assert plan.payload_message == "DemoModelPayload"


def test_plan_from_bundle_rejects_a_mismatched_proto(tmp_path) -> None:
    model = make_model()
    proto, _wire = write_schema(model, tmp_path)
    proto.write_text(
        proto.read_text(encoding="utf-8").replace("Value p_e = 1;", "Value p_e = 99;")
    )

    with pytest.raises(Exception, match="do not match"):
        plan_from_bundle(tmp_path, make_manifest())


@pytest.mark.parametrize(
    ("mapping_change", "manifest_change", "signal"),
    [
        ({"p_e": "position.q"}, {}, "p_e"),
        ({"p_n": "position.x"}, {}, "p_n"),
        ({"ghost": "position.x"}, {}, "ghost"),
        ({}, {"message_type": "PhysicalEntity"}, "platform"),
        ({"p_e": "force"}, {}, "p_e"),
        ({"p_e": "entity_identifier.site"}, {}, "p_e"),
        ({"mode": "force"}, {}, "mode"),
        ({"label": "force"}, {}, "label"),
    ],
)
def test_projection_rejections_name_the_signal(mapping_change, manifest_change, signal) -> None:
    mapping = dict(_MAPPING)
    mapping["set_vx"] = "velocity.x"
    mapping.update(mapping_change)
    manifest = make_manifest(mapping=mapping, **manifest_change)

    with pytest.raises(ProjectionPlanError, match=signal):
        projection_plan(make_model(), manifest)


def test_unmapped_signal_is_rejected_by_name() -> None:
    mapping = dict(_MAPPING)
    mapping.pop("p_u")
    mapping["set_vx"] = "velocity.x"

    with pytest.raises(ProjectionPlanError, match="p_u"):
        projection_plan(make_model(), make_manifest(mapping=mapping))
