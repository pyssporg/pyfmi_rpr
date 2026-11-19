"""Manifest validation and identity ownership."""

from __future__ import annotations

import json

import pytest

from pyfmi_rpr.errors import ManifestError
from pyfmi_rpr.manifest import (
    AdapterManifest,
    EntityIdentity,
    Frame,
    load_manifest,
    manifest_from_mapping,
)


def _data(**overrides):
    data = {
        "identity": {
            "site": 1,
            "application": 2,
            "entity": 3,
            "marking": "ALPHA",
            "force": "friendly",
            "exercise": 7,
        },
        "origin": {"latitude_deg": 57.7, "longitude_deg": 12.9, "altitude_m": 100.0},
        "frame": "enu",
        "mapping": {"p_e": "position.x"},
        "message_type": "Aircraft",
        "platform_kind": "fixed_wing",
        "dead_reckoning_algorithm": "fpb",
        "dead_reckoning_parameters": "abcdefghijklmno",
    }
    data.update(overrides)
    return data


def test_manifest_from_mapping_normalises_identity_and_frame() -> None:
    manifest = manifest_from_mapping(_data())

    assert manifest.identity == EntityIdentity(1, 2, 3, "ALPHA", 1, 7)
    assert manifest.identity.entity_id == "1:2:3"
    assert manifest.frame is Frame.ENU
    assert manifest.platform_kind == 1
    assert manifest.dead_reckoning_algorithm == 4
    assert manifest.dead_reckoning_parameters == b"abcdefghijklmno"


def test_manifest_loads_from_json(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_data()), encoding="utf-8")

    assert load_manifest(path).identity.entity_id == "1:2:3"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"frame": "body"}, "frame"),
        ({"entity_type": (1, 2)}, "seven"),
        ({"platform_kind": 9}, "between 0 and 7"),
        ({"dead_reckoning_algorithm": 10}, "between 0 and 9"),
        ({"dead_reckoning_parameters": "short"}, "15"),
        ({"unknown": 1}, "unknown manifest keys"),
    ],
)
def test_manifest_rejects_bad_values(mutation, message) -> None:
    with pytest.raises(ManifestError, match=message):
        manifest_from_mapping(_data(**mutation))


@pytest.mark.parametrize(
    ("identity", "message"),
    [
        ({"site": -1}, "site"),
        ({"site": 65536}, "site"),
        ({"application": True}, "application"),
        ({"marking": "x" * 12}, "marking"),
        ({"marking": "\x00"}, "marking"),
        ({"force": 4}, "force"),
        ({"force": "ally"}, "force"),
        ({"exercise": 256}, "exercise"),
    ],
)
def test_identity_rejects_bad_values(identity, message) -> None:
    data = _data()
    data["identity"] = {**data["identity"], **identity}
    with pytest.raises(ManifestError, match=message):
        manifest_from_mapping(data)


@pytest.mark.parametrize(
    ("origin", "message"),
    [
        ({"latitude_deg": 91.0}, "latitude"),
        ({"longitude_deg": -181.0}, "longitude"),
        ({"altitude_m": float("nan")}, "finite"),
        ({"latitude_deg": "north"}, "number"),
    ],
)
def test_origin_rejects_bad_values(origin, message) -> None:
    data = _data()
    data["origin"] = {**data["origin"], **origin}
    with pytest.raises(ManifestError, match=message):
        manifest_from_mapping(data)


def test_manifest_requires_identity_and_origin() -> None:
    with pytest.raises(ManifestError, match="identity"):
        manifest_from_mapping({"origin": _data()["origin"]})
    with pytest.raises(ManifestError, match="origin"):
        manifest_from_mapping({"identity": _data()["identity"]})


def test_manifest_is_frozen_and_mapping_is_read_only() -> None:
    manifest = manifest_from_mapping(_data())
    assert isinstance(manifest, AdapterManifest)
    with pytest.raises(TypeError):
        manifest.mapping["x"] = "position.y"  # type: ignore[index]
