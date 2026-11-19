"""One-direction generic-wire to RPR bridge.

A2 owns the publish direction only: datagrams carrying a ``pyfmi_interop``
envelope are decoded, projected onto the plan, and sent as RPR payloads.  A3
will add the reverse direction; :func:`run_bridge` takes an injected socket and
an optional sink so that seam stays testable and uncontaminated.

The bridge owns no scheduler and no thread.  It loops synchronously over the
datagrams a socket already received (or will receive before its timeout), and
``dry_run`` performs the full decode and projection without sending.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from dataclasses import dataclass

from pyfmi_interop.wire import WireError

from .codec import to_rpr
from .errors import BridgeError, CodecError, GenericWireError
from .generic import decode_generic
from .projection import ProjectionPlan

__all__ = ["BridgeStats", "run_bridge", "run_udp_bridge"]

Address = tuple[str, int]


@dataclass(frozen=True)
class BridgeStats:
    """What one bridge run observed."""

    received: int = 0
    published: int = 0
    decode_errors: int = 0
    last_error: str | None = None


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
    """Run the publish bridge over an already-bound datagram socket.

    ``max_frames=None`` loops until a receive timeout.  ``sink`` receives
    payloads instead of ``send_to`` and is how tests observe the output without
    opening a second socket.  A malformed frame is counted and skipped: one bad
    datagram must not stop a federation.
    """

    if not dry_run and send_to is None and sink is None:
        raise BridgeError("send_to or sink is required unless dry_run is true")
    if max_frames is not None and max_frames < 0:
        raise BridgeError("max_frames must be >= 0")

    received = published = errors = 0
    last_error: str | None = None
    sock.settimeout(timeout_s)
    while max_frames is None or received < max_frames:
        try:
            datagram, _peer = sock.recvfrom(65535)
        except TimeoutError:
            break
        except OSError as exc:
            raise BridgeError(f"cannot receive datagram: {exc}") from exc
        received += 1
        try:
            frame = decode_generic(plan, datagram)
            payload = to_rpr(plan, frame.values, frame.header.timestamp_ns / 1e9)
        except (WireError, GenericWireError, CodecError) as exc:
            errors += 1
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        if not dry_run:
            if sink is not None:
                sink(payload)
            else:
                assert send_to is not None
                sock.sendto(payload, send_to)
        published += 1
    return BridgeStats(
        received=received,
        published=published,
        decode_errors=errors,
        last_error=last_error,
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
    """Bind ``listen`` and run :func:`run_bridge` for one direction."""

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.bind(listen)
        except OSError as exc:
            raise BridgeError(f"cannot bind {listen}: {exc}") from exc
        return run_bridge(
            plan,
            sock,
            send_to=send_to,
            max_frames=max_frames,
            timeout_s=timeout_s,
            dry_run=dry_run,
        )
