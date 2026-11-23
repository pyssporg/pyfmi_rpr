"""The RPR SysML port is this repository's asset; check it against the contract."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYSML = ROOT / "sysml" / "rpr_entity.sysml"

# Independent of the schema table: a proto leaf type names one bare SysML
# primitive.  Enums collapse to Integer.
_PRIMITIVES = {
    "double": "Real",
    "float": "Real",
    "int32": "Integer",
    "int64": "Integer",
    "uint32": "Integer",
    "uint64": "Integer",
    "sint32": "Integer",
    "sint64": "Integer",
    "fixed32": "Integer",
    "fixed64": "Integer",
    "sfixed32": "Integer",
    "sfixed64": "Integer",
    "bool": "Boolean",
    "string": "String",
}


def _primitive(proto_type: str) -> str:
    if proto_type.startswith("rpr.v2."):
        return "Integer"
    return _PRIMITIVES[proto_type]


def test_sysml_asset_is_present():
    assert SYSML.is_file(), SYSML


def test_port_definition_matches_schema_paths():
    sysml2 = pytest.importorskip("pycps_sysml2")
    table = pytest.importorskip("pysos_rpr.schema_paths")
    try:
        architecture = sysml2.load(SYSML)
    except Exception as exc:  # report the parser's verdict, do not hide it
        pytest.fail(f"pycps_sysml2 rejected {SYSML.relative_to(ROOT)}: {exc}")

    assert "EntityState" in architecture.port_definitions
    port = architecture.port_definitions["EntityState"]

    assert list(port.attributes) == list(table.SCHEMA_PATHS)
    assert set(table.PROTO_TYPES) == set(table.SCHEMA_PATHS)
    for flat, path in table.SCHEMA_PATHS.items():
        attribute = port.attributes[flat]
        assert attribute.type_name == _primitive(table.PROTO_TYPES[flat]), flat
        assert attribute.multiplicity is None, flat
        if table.PROTO_TYPES[flat].startswith("rpr.v2."):
            assert attribute.value == 0, flat
        assert path.replace(".", "_") == flat

    omitted = {path.replace(".", "_") for path in table.OMITTED_BYTES}
    assert not omitted & set(port.attributes)
    assert table.OMITTED_BYTES == ("spatial.dead_reckoning.parameters",)

    state = architecture.part_definitions["RprEntity"].ports["entityState"]
    assert state.direction == "out"
    assert state.type_name == "EntityState"

    version = architecture.part_definitions["RprEntity"].attributes["rpr_contract"]
    contract = architecture.resolve_attribute_def(version)
    assert contract is not None
    declared = contract.attributes["version"]
    assert declared.type_name == "String"
    assert declared.value == table.ENTITY_MESSAGE.rsplit(".", 1)[0]


def test_entity_is_an_fmu_model_with_build_metadata():
    sysml2 = pytest.importorskip("pycps_sysml2")
    metadata = pytest.importorskip("pycps_sysml2.metadata")

    architecture = sysml2.load(SYSML, sysml2.core_definitions())
    definition = architecture.part_definitions["RprEntity"]

    assert "FmuModel" in definition.specializes

    resolved = metadata.fmu_metadata(architecture, definition)
    assert resolved is not None
    assert resolved.source == "RprEntity.fmu"
    assert resolved.implementation == "CoSimulation"
