"""Two-way UDP bridge between the generic wire and the RPR vocabulary.

A2 owned the publish direction only.  A3 adds the subscribe direction and puts
both behind one :class:`Bridge` with a single lifecycle:

``publish`` path (model -> federation)
    listen for generic wire frames, decode them against the plan, project the
    model outputs onto RPR and send one RPR payload per frame.

``subscribe`` path (federation -> model)
    listen for RPR payloads, decode them, take the plan's input signals and
    re-encode them as a generic wire frame with the packaged model id, the
    caller's instance id, a monotonically increasing sequence and the
    caller-supplied timestamp.

The two paths never share a socket, an endpoint or an encoder.  A frame that
arrives as RPR can only leave as generic wire, and a frame that arrives as
generic wire can only leave as RPR; that is what makes an echo loop impossible
by construction.  Exposing the two listen ports as distinct endpoints is
enforced at construction time.

The bridge owns no thread and no scheduled loop.  :meth:`Bridge.step` drains
what the sockets already have (waiting at most ``timeout_s``) and
:meth:`Bridge.run` polls for a caller-given duration, waiting at most one
millisecond at a time.  No clock is read for the content of a frame: every
timestamp comes from the caller, so equal inputs still produce equal bytes.
"""

from __future__ import annotations

import select
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass

from pyfmi_interop.wire import WireError

from .codec import from_rpr, to_rpr
from .errors import AdapterError, BridgeError
from .generic import decode_generic, encode_generic_frame
from .projection import ProjectionPlan

__all__ = [
    "Bridge",
    "BridgeStats",
    "FrameFailure",
    "run_bridge",
    "run_udp_bridge",
]

Address = tuple[str, int]
Direction = str

_PUBLISH = "publish"
_SUBSCRIBE = "subscribe"
_MAX_WAIT_S = 0.001
_DATAGRAM = 65535

# Decoding and projection failures are recoverable: one bad datagram must not
# stop a federation.  They are recorded with their direction and peer instead
# of being discarded.
_FRAME_ERRORS = (WireError, AdapterError, ValueError, OverflowError)


@dataclass(frozen=True)
class FrameFailure:
    """One frame that could not be translated, and where it came from."""

    direction: Direction
    endpoint: Address
    error: str


@dataclass(frozen=True)
class BridgeStats:
    """What one bridge step or run observed, per direction."""

    received_generic: int = 0
    published_rpr: int = 0
    received_rpr: int = 0
    published_generic: int = 0
    failures: tuple[FrameFailure, ...] = ()

    @property
    def received(self) -> int:
        """Generic frames received on the publish path (A2 compatibility)."""

        return self.received_generic

    @property
    def published(self) -> int:
        """RPR payloads sent on the publish path (A2 compatibility)."""

        return self.published_rpr

    @property
    def decode_errors(self) -> int:
        return len(self.failures)

    @property
    def last_error(self) -> str | None:
        if not self.failures:
            return None
        failure = self.failures[-1]
        return f"{failure.direction} endpoint={failure.endpoint}: {failure.error}"

    def merge(self, other: BridgeStats) -> BridgeStats:
        """Return the sum of two observations."""

        return BridgeStats(
            received_generic=self.received_generic + other.received_generic,
            published_rpr=self.published_rpr + other.published_rpr,
            received_rpr=self.received_rpr + other.received_rpr,
            published_generic=self.published_generic + other.published_generic,
            failures=self.failures + other.failures,
        )


class Bridge:
    """One instance's publish and subscribe paths over UDP.

    ``generic_listen`` receives model frames; ``rpr_send`` is where their
    projection is published.  ``rpr_listen`` receives federation payloads;
    ``generic_send`` is where their re-encoding for the model inputs is sent.
    A direction is enabled by supplying its send endpoint; a bridge may run
    publish-only or subscribe-only, but never with both directions on one
    listen address.
    """

    def __init__(
        self,
        plan: ProjectionPlan,
        *,
        generic_listen: Address | None = None,
        rpr_listen: Address | None = None,
        rpr_send: Address | None = None,
        generic_send: Address | None = None,
        instance: int = 1,
        on_error: Callable[[FrameFailure], object] | None = None,
        raise_on_bad_frame: bool = False,
        dry_run: bool = False,
    ) -> None:
        if not isinstance(plan, ProjectionPlan):
            raise TypeError("plan must be a ProjectionPlan")
        publish = rpr_send is not None or (dry_run and generic_listen is not None)
        subscribe = generic_send is not None or (dry_run and rpr_listen is not None)
        if publish and rpr_send is None and not dry_run:
            raise BridgeError("publish path requires rpr_send")
        if subscribe and generic_send is None and not dry_run:
            raise BridgeError("subscribe path requires generic_send")
        if publish and generic_listen is None:
            raise BridgeError("publish path requires generic_listen")
        if subscribe and rpr_listen is None:
            raise BridgeError("subscribe path requires rpr_listen")
        if not publish and generic_listen is not None:
            raise BridgeError("generic_listen requires rpr_send")
        if not subscribe and rpr_listen is not None:
            raise BridgeError("rpr_listen requires generic_send")
        if not publish and not subscribe:
            raise BridgeError("a bridge needs rpr_send, generic_send or both")
        if publish and subscribe:
            assert generic_listen is not None and rpr_listen is not None
            if _same_endpoint(generic_listen, rpr_listen):
                raise BridgeError(
                    "publish and subscribe must listen on distinct endpoints, "
                    f"both are {generic_listen}"
                )
            for label, send, listen in (
                ("publish RPR", rpr_send, rpr_listen),
                ("publish RPR", rpr_send, generic_listen),
                ("subscribe generic", generic_send, generic_listen),
                ("subscribe generic", generic_send, rpr_listen),
            ):
                if _same_endpoint(send, listen):
                    raise BridgeError(
                        f"{label} would be delivered back to this bridge's own "
                        f"listen endpoint {listen}"
                    )
        if isinstance(instance, bool) or not isinstance(instance, int):
            raise BridgeError("instance must be an integer")
        if not 0 <= instance <= 0xFFFFFFFF:
            raise BridgeError("instance must fit uint32")

        self._plan = plan
        self._generic_listen = generic_listen
        self._rpr_listen = rpr_listen
        self._rpr_send = rpr_send
        self._generic_send = generic_send
        self._instance = instance
        self._on_error = on_error
        self._dry_run = dry_run
        self._raise_on_bad_frame = raise_on_bad_frame
        self._publish = publish
        self._subscribe = subscribe
        self._generic_sock: socket.socket | None = None
        self._rpr_sock: socket.socket | None = None
        self._sequence = 0
        self._started = False
        self._closed = False

    @property
    def generic_endpoint(self) -> Address | None:
        """The endpoint the publish path listens on, if enabled."""

        return self._generic_listen

    @property
    def rpr_endpoint(self) -> Address | None:
        """The endpoint the subscribe path listens on, if enabled."""

        return self._rpr_listen

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> Bridge:
        """Bind the listen sockets.  Idempotent; call :meth:`close` to reset."""

        if self._closed:
            raise BridgeError("bridge is closed; create a new Bridge")
        if self._started:
            return self
        if self._publish:
            assert self._generic_listen is not None
            self._generic_sock = _bind(
                self._generic_listen, _PUBLISH, "generic listen endpoint"
            )
        if self._subscribe:
            assert self._rpr_listen is not None
            self._rpr_sock = _bind(
                self._rpr_listen, _SUBSCRIBE, "RPR listen endpoint"
            )
        self._started = True
        return self

    def close(self) -> None:
        """Close every socket this bridge opened and release the endpoints."""

        for sock in (self._generic_sock, self._rpr_sock):
            if sock is not None:
                sock.close()
        self._generic_sock = None
        self._rpr_sock = None
        self._started = False
        self._closed = True

    def __enter__(self) -> Bridge:
        return self.start()

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # -- stepping ----------------------------------------------------------

    def step(
        self,
        *,
        timestamp_ns: int,
        timeout_s: float = 0.0,
        max_frames: int | None = None,
    ) -> BridgeStats:
        """Drain ready datagrams in both directions and return what happened.

        ``timeout_s`` waits for the first datagram; the rest are taken without
        waiting.  ``timestamp_ns`` is the caller's step timestamp and is the
        only timestamp any re-encoded frame carries.  At most ``max_frames``
        datagrams are handled, publish direction first.
        """

        self._require_started()
        _require_uint64(timestamp_ns, "timestamp_ns")
        if timeout_s < 0:
            raise BridgeError("timeout_s must be >= 0")
        if max_frames is not None and max_frames < 0:
            raise BridgeError("max_frames must be >= 0")
        if max_frames == 0:
            return BridgeStats()

        sockets = [
            sock
            for sock in (self._generic_sock, self._rpr_sock)
            if sock is not None
        ]
        if not sockets:
            return BridgeStats()

        ready: list[socket.socket] = []
        if timeout_s > 0:
            readable, _, _ = select.select(sockets, [], [], timeout_s)
            ready = list(readable)
        else:
            readable, _, _ = select.select(sockets, [], [], 0)
            ready = list(readable)
            if not ready:
                # Still drain each socket: a datagram may arrive between the
                # select and the recv, and recvfrom is non-blocking.
                ready = sockets

        stats = BridgeStats()
        budget = max_frames
        for sock in ready:
            if sock is self._generic_sock:
                stats = stats.merge(self._drain_generic(budget))
            else:
                stats = stats.merge(
                    self._drain_rpr(timestamp_ns, budget)
                )
            budget = None if budget is None else max(0, budget - _handled(stats))
            if budget == 0:
                break
        return stats

    def run(
        self,
        duration_s: float,
        *,
        timestamp_ns: Callable[[], int],
        poll_s: float = _MAX_WAIT_S,
    ) -> BridgeStats:
        """Poll both directions for ``duration_s`` seconds.

        ``timestamp_ns`` is the caller's timestamp provider; the bridge never
        reads a clock to fill a frame.  Each wait is at most ``poll_s``, which
        must be positive and no larger than one millisecond.
        """

        self._require_started()
        if duration_s < 0:
            raise BridgeError("duration_s must be >= 0")
        if not 0 < poll_s <= _MAX_WAIT_S:
            raise BridgeError(f"poll_s must be in (0, {_MAX_WAIT_S}]")
        if not callable(timestamp_ns):
            raise BridgeError("timestamp_ns must be a callable returning int")

        deadline = time.monotonic() + duration_s
        total = BridgeStats()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            total = total.merge(
                self.step(
                    timestamp_ns=timestamp_ns(),
                    timeout_s=min(poll_s, remaining),
                )
            )
        return total

    # -- path handlers -----------------------------------------------------

    def _drain_generic(self, budget: int | None) -> BridgeStats:
        assert self._generic_sock is not None
        received = published = 0
        failures: list[FrameFailure] = []
        while budget is None or received < budget:
            datagram, peer = _recv(self._generic_sock, _PUBLISH, self._generic_listen)
            if peer is None:
                break
            received += 1
            try:
                payload = _project_generic(self._plan, datagram)
            except _FRAME_ERRORS as exc:
                failure = _failure(_PUBLISH, peer, exc)
                failures.append(failure)
                self._report(failure)
                continue
            # Only RPR leaves this path.
            if not self._dry_run:
                _send(
                    self._generic_sock,
                    payload,
                    self._rpr_send,
                    _PUBLISH,
                    "RPR payload",
                )
            published += 1
        return BridgeStats(
            received_generic=received,
            published_rpr=published,
            failures=tuple(failures),
        )

    def _drain_rpr(self, timestamp_ns: int, budget: int | None) -> BridgeStats:
        assert self._rpr_sock is not None
        received = published = 0
        failures: list[FrameFailure] = []
        while budget is None or received < budget:
            datagram, peer = _recv(self._rpr_sock, _SUBSCRIBE, self._rpr_listen)
            if peer is None:
                break
            received += 1
            sequence = self._sequence
            try:
                frame = _reencode_inputs(
                    self._plan,
                    datagram,
                    instance=self._instance,
                    sequence=sequence,
                    timestamp_ns=timestamp_ns,
                )
            except _FRAME_ERRORS as exc:
                failure = _failure(_SUBSCRIBE, peer, exc)
                failures.append(failure)
                self._report(failure)
                continue
            # Only generic wire leaves this path.
            if not self._dry_run:
                _send(
                    self._rpr_sock,
                    frame,
                    self._generic_send,
                    _SUBSCRIBE,
                    "generic wire frame",
                )
            self._sequence += 1
            published += 1
        return BridgeStats(
            received_rpr=received,
            published_generic=published,
            failures=tuple(failures),
        )

    def _report(self, failure: FrameFailure) -> None:
        if self._on_error is not None:
            self._on_error(failure)
        if self._raise_on_bad_frame:
            raise BridgeError(
                f"{failure.direction} endpoint={failure.endpoint}: {failure.error}"
            )

    def _require_started(self) -> None:
        if not self._started:
            raise BridgeError("bridge is not started; call start() first")


# -- pure translation seams ------------------------------------------------


def _project_generic(plan: ProjectionPlan, datagram: bytes) -> bytes:
    """Generic wire -> RPR.  The only publish-path translation."""

    decoded = decode_generic(plan, datagram)
    return to_rpr(plan, decoded.values, decoded.header.timestamp_ns / 1e9)


def _reencode_inputs(
    plan: ProjectionPlan,
    payload: bytes,
    *,
    instance: int,
    sequence: int,
    timestamp_ns: int,
) -> bytes:
    """RPR -> generic wire carrying only the plan's input signals.

    The envelope is always rebuilt from the packaged plan: model id from
    ``wire.json``, the caller's instance id, the bridge's monotonic sequence
    and the caller's timestamp.
    """

    values = from_rpr(plan, payload)
    inputs = {entry.signal_name: values[entry.signal_name] for entry in plan.subscribe}
    return encode_generic_frame(
        plan,
        inputs,
        instance=instance,
        sequence=sequence,
        timestamp_ns=timestamp_ns,
    )


# -- socket helpers --------------------------------------------------------


def _bind(endpoint: Address, direction: str, role: str) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(endpoint)
    except OSError as exc:
        sock.close()
        raise BridgeError(
            f"{direction}: cannot bind {role} {endpoint}: {exc}"
        ) from exc
    sock.setblocking(False)
    return sock


def _recv(
    sock: socket.socket, direction: str, endpoint: Address | None
) -> tuple[bytes, Address | None]:
    try:
        return sock.recvfrom(_DATAGRAM)
    except BlockingIOError:
        return b"", None
    except OSError as exc:
        raise BridgeError(
            f"{direction}: cannot receive on {endpoint}: {exc}"
        ) from exc


def _send(
    sock: socket.socket,
    data: bytes,
    endpoint: Address | None,
    direction: str,
    what: str,
) -> None:
    if endpoint is None:
        raise BridgeError(f"{direction}: no endpoint configured for {what}")
    try:
        sock.sendto(data, endpoint)
    except OSError as exc:
        raise BridgeError(
            f"{direction}: cannot send {what} to {endpoint}: {exc}"
        ) from exc


def _failure(direction: str, peer: Address, exc: BaseException) -> FrameFailure:
    return FrameFailure(
        direction=direction,
        endpoint=peer,
        error=f"{type(exc).__name__}: {exc}",
    )


def _same_endpoint(left: Address | None, right: Address | None) -> bool:
    if left is None or right is None:
        return False
    left_host, left_port = left
    right_host, right_port = right
    if left_port != right_port or left_port < 0:
        return False
    wildcard = {"", "0.0.0.0", "::", "localhost"}
    return left_host == right_host or left_host in wildcard or right_host in wildcard


def _require_uint64(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BridgeError(f"{name} must be an integer")
    if not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
        raise BridgeError(f"{name} must fit uint64")


def _handled(stats: BridgeStats) -> int:
    """Datagrams handled by ``stats``; used for the per-step frame budget."""

    return (
        stats.received_generic
        + stats.received_rpr
    )


# -- A2 compatibility: publish-only helpers --------------------------------


def run_bridge(
    plan: ProjectionPlan,
    sock: socket.socket,
    *,
    send_to: Address | None = None,
    sink: Callable[[bytes], object] | None = None,
    max_frames: int | None = None,
    timeout_s: float = 1.0,
    dry_run: bool = False,
) -> BridgeStats:
    """Run the publish direction over an already-bound datagram socket.

    Kept from A2 for callers that own the socket.  New code should use
    :class:`Bridge`, which owns both directions and the sequence state.
    """

    if not dry_run and send_to is None and sink is None:
        raise BridgeError("send_to or sink is required unless dry_run is true")
    if max_frames is not None and max_frames < 0:
        raise BridgeError("max_frames must be >= 0")

    received = published = 0
    failures: list[FrameFailure] = []
    sock.settimeout(timeout_s)
    while max_frames is None or received < max_frames:
        try:
            datagram, peer = sock.recvfrom(_DATAGRAM)
        except TimeoutError:
            break
        except OSError as exc:
            raise BridgeError(
                f"{_PUBLISH}: cannot receive on {sock.getsockname()}: {exc}"
            ) from exc
        received += 1
        try:
            payload = _project_generic(plan, datagram)
        except _FRAME_ERRORS as exc:
            failures.append(_failure(_PUBLISH, peer, exc))
            continue
        if not dry_run:
            if sink is not None:
                sink(payload)
            else:
                assert send_to is not None
                try:
                    sock.sendto(payload, send_to)
                except OSError as exc:
                    raise BridgeError(
                        f"{_PUBLISH}: cannot send RPR payload to {send_to}: {exc}"
                    ) from exc
        published += 1
    return BridgeStats(
        received_generic=received,
        published_rpr=published,
        failures=tuple(failures),
    )


def run_udp_bridge(
    plan: ProjectionPlan,
    *,
    listen: Address,
    send_to: Address | None,
    max_frames: int | None = None,
    timeout_s: float = 1.0,
    dry_run: bool = False,
) -> BridgeStats:
    """Bind ``listen`` and run the publish-only bridge for one direction."""

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.bind(listen)
        except OSError as exc:
            raise BridgeError(
                f"{_PUBLISH}: cannot bind generic listen endpoint {listen}: {exc}"
            ) from exc
        return run_bridge(
            plan,
            sock,
            send_to=send_to,
            max_frames=max_frames,
            timeout_s=timeout_s,
            dry_run=dry_run,
        )
