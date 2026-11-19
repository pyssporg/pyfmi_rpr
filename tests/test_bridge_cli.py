"""One-direction bridge and command-line plan inspection."""

from __future__ import annotations

import json
import socket

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
from pysos_rpr import messages  # noqa: E402

from pyfmi_rpr.bridge import run_bridge  # noqa: E402
from pyfmi_rpr.cli import main  # noqa: E402
from pyfmi_rpr.generic import encode_generic_frame  # noqa: E402
from pyfmi_rpr.manifest import AdapterManifest, EntityIdentity, Origin  # noqa: E402
from pyfmi_rpr.projection import projection_plan  # noqa: E402

_MANIFEST = {
    "identity": {"site": 4, "application": 5, "entity": 6, "marking": "BRAVO", "force": 1},
    "origin": {"latitude_deg": 57.7, "longitude_deg": 12.9, "altitude_m": 100.0},
    "mapping": {"px": "position.x", "label": "marking"},
}


def make_model() -> ModelDefinition:
    return ModelDefinition(
        name="bridge_model",
        guid=deterministic_guid("bridge_model"),
        step_size_s=0.01,
        signals=(
            Signal("px", 1, DataType.REAL, Direction.OUTPUT),
            Signal("label", 2, DataType.STRING, Direction.OUTPUT, capacity=11),
        ),
    )


def make_manifest() -> AdapterManifest:
    return AdapterManifest(
        identity=EntityIdentity(site=4, application=5, entity=6, marking="BRAVO"),
        origin=Origin(57.7, 12.9, 100.0),
        mapping=_MANIFEST["mapping"],
    )


def test_bridge_publishes_one_projected_payload() -> None:
    plan = projection_plan(make_model(), make_manifest())
    frame = encode_generic_frame(
        plan, {"px": 25.0, "label": "WIRE"}, instance=1, sequence=1, timestamp_ns=10
    )
    seen: list[bytes] = []

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(frame, receiver.getsockname())
        stats = run_bridge(
            plan, receiver, sink=seen.append, max_frames=1, timeout_s=0.5
        )

    assert stats.received == 1
    assert stats.published == 1
    assert stats.decode_errors == 0
    assert len(seen) == 1
    message = messages.decode(messages.PhysicalEntity, seen[0], strict=True)
    assert message.base.entity_identifier.site == 4
    assert message.base.marking.characters == "WIRE"


def test_bridge_dry_run_decodes_but_does_not_send() -> None:
    plan = projection_plan(make_model(), make_manifest())
    frame = encode_generic_frame(
        plan, {"px": 1.0, "label": ""}, instance=1, sequence=1, timestamp_ns=10
    )

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(frame, receiver.getsockname())
        stats = run_bridge(plan, receiver, max_frames=1, timeout_s=0.5, dry_run=True)
        receiver.settimeout(0.05)
        with pytest.raises(TimeoutError):
            receiver.recvfrom(65535)

    assert stats.received == 1
    assert stats.published == 1


def test_cli_plan_prints_the_manifest_identity(tmp_path, capsys) -> None:
    write_schema(make_model(), tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_MANIFEST), encoding="utf-8")

    code = main(
        ["plan", "--bundle", str(tmp_path), "--manifest", str(manifest_path)]
    )

    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["identity"]["entity_id"] == "4:5:6"
    assert output["publish"] == [
        {"signal": "px", "target": "spatial.world_location.x"},
        {"signal": "label", "target": "marking.characters"},
    ]


def _free_ports(count: int) -> list[int]:
    sockets = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(count)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def test_cli_bridge_reports_both_directions(tmp_path, capsys) -> None:
    write_schema(make_model(), tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_MANIFEST), encoding="utf-8")

    generic_port, rpr_port = _free_ports(2)
    code = main(
        [
            "bridge",
            "--bundle",
            str(tmp_path),
            "--manifest",
            str(manifest_path),
            "--generic-listen",
            f"127.0.0.1:{generic_port}",
            "--rpr-listen",
            f"127.0.0.1:{rpr_port}",
            "--duration",
            "0",
            "--dry-run",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["dry_run"] is True
    assert output["failures"] == []
    assert set(output) >= {
        "received_generic",
        "published_rpr",
        "received_rpr",
        "published_generic",
    }
