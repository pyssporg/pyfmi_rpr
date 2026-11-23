"""Two-way bridge over real UDP loopback sockets.

The required A3 proof: two independent bridge instances, each with its own
packaged bundle (fixture ``ModelDefinition`` -> ``wire.json``) and manifest
identity, exchange RPR payloads in both directions and each side receives the
other's projected values within tolerance.

The other tests pin the anti-echo construction, the error reporting (direction
plus endpoint) and the caller-owned envelope (instance, monotonic sequence,
caller timestamp).
"""

from __future__ import annotations

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
from pyfmi_interop.wire import decode as decode_wire  # noqa: E402

from pyfmi_rpr.bridge import Bridge  # noqa: E402
from pyfmi_rpr.bundle import plan_from_bundle  # noqa: E402
from pyfmi_rpr.codec import to_rpr  # noqa: E402
from pyfmi_rpr.errors import BridgeError  # noqa: E402
from pyfmi_rpr.generic import decode_generic, encode_generic_frame  # noqa: E402
from pyfmi_rpr.manifest import AdapterManifest, EntityIdentity, Origin  # noqa: E402

_MAPPING = {
    "out_e": "position.x",
    "out_n": "position.y",
    "out_u": "position.z",
    "out_label": "marking",
    "in_e": "position.x",
    "in_n": "position.y",
    "in_u": "position.z",
    "in_label": "marking",
}

_VALUES_A = {"out_e": 1523.25, "out_n": -874.5, "out_u": 312.75, "out_label": "ALPHA-1"}
_VALUES_B = {"out_e": -2048.125, "out_n": 640.5, "out_u": -12.25, "out_label": "BRAVO-2"}
# One federation origin: the two instances differ by identity, not by frame.
_ORIGIN = Origin(57.7, 12.9, 100.0)


def _model(name: str, step_size_s: float) -> ModelDefinition:
    return ModelDefinition(
        name=name,
        guid=deterministic_guid(name),
        step_size_s=step_size_s,
        signals=(
            Signal("out_e", 1, DataType.REAL, Direction.OUTPUT),
            Signal("out_n", 2, DataType.REAL, Direction.OUTPUT),
            Signal("out_u", 3, DataType.REAL, Direction.OUTPUT),
            Signal("out_label", 4, DataType.STRING, Direction.OUTPUT, capacity=11),
            Signal("in_e", 5, DataType.REAL, Direction.INPUT),
            Signal("in_n", 6, DataType.REAL, Direction.INPUT),
            Signal("in_u", 7, DataType.REAL, Direction.INPUT),
            Signal("in_label", 8, DataType.STRING, Direction.INPUT, capacity=11),
        ),
    )


def _manifest(site: int, entity: int, marking: str, origin: Origin) -> AdapterManifest:
    return AdapterManifest(
        identity=EntityIdentity(site=site, application=site + 1, entity=entity, marking=marking),
        origin=origin,
        mapping=_MAPPING,
    )


def _plan(tmp_path, name: str, step_size_s: float, manifest: AdapterManifest):
    bundle = tmp_path / f"{name}_bundle"
    write_schema(_model(name, step_size_s), bundle)
    return plan_from_bundle(bundle, manifest)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _udp() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    return sock


def _recv(sock: socket.socket, timeout_s: float = 1.0) -> bytes:
    sock.settimeout(timeout_s)
    datagram, _peer = sock.recvfrom(65535)
    return datagram


def _empty(sock: socket.socket, timeout_s: float = 0.05) -> None:
    sock.settimeout(timeout_s)
    with pytest.raises(TimeoutError):
        sock.recvfrom(65535)


def test_two_bridges_exchange_rpr_in_both_directions(tmp_path) -> None:
    plan_a = _plan(
        tmp_path,
        "fixture_alpha",
        0.01,
        _manifest(11, 21, "ALPHA", _ORIGIN),
    )
    plan_b = _plan(
        tmp_path,
        "fixture_bravo",
        0.02,
        _manifest(31, 41, "BRAVO", _ORIGIN),
    )
    assert plan_a.model_id != plan_b.model_id

    port = {
        name: _free_port()
        for name in ("a_generic", "a_rpr", "b_generic", "b_rpr")
    }
    model_a, model_b = _udp(), _udp()
    sender_a, sender_b = _udp(), _udp()
    try:
        bridge_a = Bridge(
            plan_a,
            generic_listen=("127.0.0.1", port["a_generic"]),
            rpr_listen=("127.0.0.1", port["a_rpr"]),
            rpr_send=("127.0.0.1", port["b_rpr"]),
            generic_send=model_a.getsockname(),
            instance=1001,
        )
        bridge_b = Bridge(
            plan_b,
            generic_listen=("127.0.0.1", port["b_generic"]),
            rpr_listen=("127.0.0.1", port["b_rpr"]),
            rpr_send=("127.0.0.1", port["a_rpr"]),
            generic_send=model_b.getsockname(),
            instance=2002,
        )
        with bridge_a, bridge_b:
            # A publishes its outputs as RPR; B receives RPR and emits generic
            # wire for its own inputs.
            frame = encode_generic_frame(
                plan_a, _VALUES_A, instance=77, sequence=1, timestamp_ns=111
            )
            sender_a.sendto(frame, ("127.0.0.1", port["a_generic"]))
            publish_stats = bridge_a.step(timestamp_ns=1_000, timeout_s=1.0)
            assert publish_stats.received_generic == 1
            assert publish_stats.published_rpr == 1
            assert publish_stats.failures == ()

            subscribe_stats = bridge_b.step(timestamp_ns=2_000, timeout_s=1.0)
            assert subscribe_stats.received_rpr == 1
            assert subscribe_stats.published_generic == 1
            assert subscribe_stats.failures == ()

            received = _recv(model_b)
            decoded = decode_generic(plan_b, received)
            header = decode_wire(received).header
            # The envelope is rebuilt from B's packaged wire.json and the
            # caller's instance/timestamp, with B's own sequence counter.
            assert header.model_id.hex() == plan_b.model_id
            assert header.instance == 2002
            assert header.sequence == 0
            assert header.timestamp_ns == 2_000
            assert decoded.values["in_e"] == pytest.approx(_VALUES_A["out_e"], abs=1e-3)
            assert decoded.values["in_n"] == pytest.approx(_VALUES_A["out_n"], abs=1e-3)
            assert decoded.values["in_u"] == pytest.approx(_VALUES_A["out_u"], abs=1e-3)
            assert decoded.values["in_label"] == _VALUES_A["out_label"]

            # B publishes its outputs; A projects them onto A's inputs.
            frame = encode_generic_frame(
                plan_b, _VALUES_B, instance=88, sequence=2, timestamp_ns=222
            )
            sender_b.sendto(frame, ("127.0.0.1", port["b_generic"]))
            publish_stats = bridge_b.step(timestamp_ns=3_000, timeout_s=1.0)
            assert publish_stats.received_generic == 1
            assert publish_stats.published_rpr == 1

            subscribe_stats = bridge_a.step(timestamp_ns=4_000, timeout_s=1.0)
            assert subscribe_stats.received_rpr == 1
            assert subscribe_stats.published_generic == 1

            received = _recv(model_a)
            decoded = decode_generic(plan_a, received)
            header = decode_wire(received).header
            assert header.model_id.hex() == plan_a.model_id
            assert header.instance == 1001
            assert header.sequence == 0
            assert header.timestamp_ns == 4_000
            assert decoded.values["in_e"] == pytest.approx(_VALUES_B["out_e"], abs=1e-3)
            assert decoded.values["in_n"] == pytest.approx(_VALUES_B["out_n"], abs=1e-3)
            assert decoded.values["in_u"] == pytest.approx(_VALUES_B["out_u"], abs=1e-3)
            assert decoded.values["in_label"] == _VALUES_B["out_label"]
    finally:
        model_a.close()
        model_b.close()
        sender_a.close()
        sender_b.close()


def test_rpr_in_never_leaves_as_rpr_and_generic_in_never_leaves_as_generic(
    tmp_path,
) -> None:
    plan = _plan(
        tmp_path, "echo_fixture", 0.01, _manifest(5, 6, "ECHO", Origin(57.7, 12.9, 100.0))
    )
    rpr_out, generic_out, sender = _udp(), _udp(), _udp()
    bridge = Bridge(
        plan,
        generic_listen=("127.0.0.1", _free_port()),
        rpr_listen=("127.0.0.1", _free_port()),
        rpr_send=rpr_out.getsockname(),
        generic_send=generic_out.getsockname(),
        instance=9,
    )
    try:
        with bridge:
            # RPR in: only a generic frame may leave the subscribe path.
            rpr_payload = to_rpr(plan, _VALUES_A, 0.0)
            sender.sendto(rpr_payload, bridge.rpr_endpoint)
            stats = bridge.step(timestamp_ns=10, timeout_s=1.0)
            assert (stats.received_rpr, stats.published_generic) == (1, 1)
            assert (stats.received_generic, stats.published_rpr) == (0, 0)
            _empty(rpr_out)
            assert _recv(generic_out) != rpr_payload

            # Generic in: only an RPR payload may leave the publish path.
            frame = encode_generic_frame(
                plan, _VALUES_B, instance=9, sequence=3, timestamp_ns=10
            )
            sender.sendto(frame, bridge.generic_endpoint)
            stats = bridge.step(timestamp_ns=20, timeout_s=1.0)
            assert (stats.received_generic, stats.published_rpr) == (1, 1)
            assert (stats.received_rpr, stats.published_generic) == (0, 0)
            _empty(generic_out)
            assert _recv(rpr_out) != frame
    finally:
        rpr_out.close()
        generic_out.close()
        sender.close()


def test_subscribe_sequence_is_monotonic_and_timestamp_is_the_callers(tmp_path) -> None:
    plan = _plan(
        tmp_path, "sequence_fixture", 0.01, _manifest(7, 8, "SEQ", Origin(57.7, 12.9, 100.0))
    )
    generic_out, sender = _udp(), _udp()
    bridge = Bridge(
        plan,
        rpr_listen=("127.0.0.1", _free_port()),
        generic_send=generic_out.getsockname(),
        instance=42,
    )
    try:
        with bridge:
            payload = to_rpr(plan, _VALUES_A, 0.0)
            headers = []
            for timestamp_ns in (5_000, 6_000):
                sender.sendto(payload, bridge.rpr_endpoint)
                stats = bridge.step(timestamp_ns=timestamp_ns, timeout_s=1.0)
                assert stats.published_generic == 1
                headers.append(decode_wire(_recv(generic_out)).header)
            assert [header.timestamp_ns for header in headers] == [5_000, 6_000]
            assert [header.sequence for header in headers] == [0, 1]
    finally:
        generic_out.close()
        sender.close()


@pytest.mark.parametrize(
    ("path", "direction"),
    [("generic", "publish"), ("rpr", "subscribe")],
)
def test_bad_frame_names_direction_and_endpoint(tmp_path, path, direction) -> None:
    plan = _plan(
        tmp_path, f"bad_{path}", 0.01, _manifest(1, 2, "BAD", Origin(57.7, 12.9, 100.0))
    )
    sender = _udp()
    bridge = Bridge(
        plan,
        generic_listen=("127.0.0.1", _free_port()),
        rpr_listen=("127.0.0.1", _free_port()),
        rpr_send=sender.getsockname(),
        generic_send=sender.getsockname(),
        instance=1,
    )
    try:
        with bridge:
            listen = bridge.generic_endpoint if path == "generic" else bridge.rpr_endpoint
            sender.sendto(b"not a frame", listen)
            stats = bridge.step(timestamp_ns=1, timeout_s=1.0)

        assert stats.decode_errors == 1
        failure = stats.failures[0]
        assert failure.direction == direction
        assert failure.endpoint[0] == "127.0.0.1"
        assert failure.endpoint[1] == sender.getsockname()[1]
        assert direction in (stats.last_error or "")
        assert str(failure.endpoint[1]) in (stats.last_error or "")
    finally:
        sender.close()


def test_bad_frame_can_be_raised_with_direction_and_endpoint(tmp_path) -> None:
    plan = _plan(
        tmp_path, "strict_bad", 0.01, _manifest(1, 2, "BAD", Origin(57.7, 12.9, 100.0))
    )
    sender = _udp()
    bridge = Bridge(
        plan,
        rpr_listen=("127.0.0.1", _free_port()),
        generic_send=sender.getsockname(),
        raise_on_bad_frame=True,
    )
    try:
        with bridge:
            sender.sendto(b"junk", bridge.rpr_endpoint)
            with pytest.raises(BridgeError) as caught:
                bridge.step(timestamp_ns=1, timeout_s=1.0)
        assert "subscribe" in str(caught.value)
        assert str(sender.getsockname()[1]) in str(caught.value)
    finally:
        sender.close()


def test_bind_error_names_endpoint_and_direction(tmp_path) -> None:
    plan = _plan(
        tmp_path, "bind_fixture", 0.01, _manifest(1, 2, "BIND", Origin(57.7, 12.9, 100.0))
    )
    occupied = _udp()
    bridge = Bridge(
        plan,
        generic_listen=occupied.getsockname(),
        rpr_send=("127.0.0.1", _free_port()),
        instance=1,
    )
    try:
        with pytest.raises(BridgeError) as caught:
            bridge.start()
        message = str(caught.value)
        assert "publish" in message
        assert "cannot bind" in message
        assert str(occupied.getsockname()[1]) in message
    finally:
        occupied.close()


def test_echo_endpoints_are_rejected_at_construction(tmp_path) -> None:
    plan = _plan(
        tmp_path, "echo_reject", 0.01, _manifest(1, 2, "ECHO", Origin(57.7, 12.9, 100.0))
    )
    rpr_port = _free_port()
    with pytest.raises(BridgeError, match="own listen endpoint"):
        Bridge(
            plan,
            generic_listen=("127.0.0.1", _free_port()),
            rpr_listen=("127.0.0.1", rpr_port),
            rpr_send=("127.0.0.1", rpr_port),
            generic_send=("127.0.0.1", _free_port()),
            instance=1,
        )
    with pytest.raises(BridgeError, match="own listen endpoint"):
        Bridge(
            plan,
            generic_listen=("127.0.0.1", _free_port()),
            rpr_listen=("127.0.0.1", rpr_port),
            rpr_send=("127.0.0.1", _free_port()),
            generic_send=("127.0.0.1", rpr_port),
            instance=1,
        )
    with pytest.raises(BridgeError, match="distinct endpoints"):
        Bridge(
            plan,
            generic_listen=("127.0.0.1", rpr_port),
            rpr_listen=("127.0.0.1", rpr_port),
            rpr_send=("127.0.0.1", _free_port()),
            generic_send=("127.0.0.1", _free_port()),
            instance=1,
        )
