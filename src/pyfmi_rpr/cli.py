"""Command line entry points for plan inspection and the two-way bridge."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Sequence

from .bundle import plan_from_bundle
from .errors import AdapterError
from .manifest import load_manifest


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``pyfmi_rpr`` command line."""

    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            plan = _plan(args)
            print(json.dumps(_describe(plan), indent=2, sort_keys=True))
            return 0
        if args.command == "bridge":
            from .bridge import Bridge

            plan = _plan(args)
            bridge = Bridge(
                plan,
                generic_listen=_address(args.generic_listen),
                rpr_listen=_address(args.rpr_listen),
                rpr_send=_address(args.rpr_send),
                generic_send=_address(args.generic_send),
                instance=args.instance,
                dry_run=args.dry_run,
                raise_on_bad_frame=args.strict,
            )
            with bridge:
                stats = bridge.run(
                    args.duration,
                    timestamp_ns=_timestamp_source(args.timestamp_ns),
                    poll_s=args.poll,
                )
            print(
                json.dumps(
                    {
                        "received_generic": stats.received_generic,
                        "published_rpr": stats.published_rpr,
                        "received_rpr": stats.received_rpr,
                        "published_generic": stats.published_generic,
                        "failures": [
                            {
                                "direction": failure.direction,
                                "endpoint": list(failure.endpoint),
                                "error": failure.error,
                            }
                            for failure in stats.failures
                        ],
                        "last_error": stats.last_error,
                        "dry_run": args.dry_run,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
    except (AdapterError, OSError, ValueError) as exc:
        print(f"pyfmi_rpr: {exc}", file=sys.stderr)
        return 2
    parser.print_help()
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyfmi_rpr")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="print the projection for one instance")
    _bundle_arguments(plan)

    bridge = subparsers.add_parser(
        "bridge", help="run the two-way generic-wire <-> RPR bridge"
    )
    _bundle_arguments(bridge)
    bridge.add_argument(
        "--generic-listen",
        default="0.0.0.0:5005",
        help="host:port receiving generic wire frames from the model (publish path)",
    )
    bridge.add_argument(
        "--rpr-send",
        default="127.0.0.1:6006",
        help="host:port to publish RPR payloads to (publish path)",
    )
    bridge.add_argument(
        "--rpr-listen",
        default="0.0.0.0:6005",
        help="host:port receiving RPR payloads from the federation (subscribe path)",
    )
    bridge.add_argument(
        "--generic-send",
        default="127.0.0.1:5006",
        help="host:port to send re-encoded generic frames to (subscribe path)",
    )
    bridge.add_argument("--instance", type=int, default=1, help="generic wire instance id")
    bridge.add_argument(
        "--duration", type=float, default=1.0, help="seconds to poll before returning"
    )
    bridge.add_argument(
        "--poll", type=float, default=0.001, help="poll wait per loop, at most 0.001 s"
    )
    bridge.add_argument(
        "--timestamp-ns",
        type=int,
        default=None,
        help="fixed caller timestamp for every frame (default: wall clock per poll)",
    )
    bridge.add_argument("--dry-run", action="store_true", help="translate without sending")
    bridge.add_argument(
        "--strict", action="store_true", help="fail on the first malformed frame"
    )
    return parser


def _bundle_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--bundle", required=True, help="directory with wire.json and <Model>.proto"
    )
    parser.add_argument("--manifest", required=True, help="federation manifest JSON")


def _plan(args: argparse.Namespace):
    manifest = load_manifest(args.manifest)
    return plan_from_bundle(args.bundle, manifest)


def _timestamp_source(fixed: int | None):
    """Return the caller's timestamp provider; the bridge never reads a clock."""

    if fixed is not None:
        return lambda: fixed
    return time.time_ns


def _address(value: str) -> tuple[str, int]:
    host, separator, port = value.rpartition(":")
    if not separator or not host:
        raise ValueError(f"address must be host:port, got {value!r}")
    return (host, int(port))


def _describe(plan) -> dict:
    return {
        "model": plan.model_name,
        "model_id": plan.model_id,
        "payload_message": plan.payload_message,
        "identity": {
            "entity_id": plan.entity_id,
            "site": plan.identity.site,
            "application": plan.identity.application,
            "entity": plan.identity.entity,
            "marking": plan.identity.marking,
            "force": plan.identity.force,
            "exercise": plan.identity.exercise,
        },
        "origin": {
            "latitude_deg": plan.origin.latitude_deg,
            "longitude_deg": plan.origin.longitude_deg,
            "altitude_m": plan.origin.altitude_m,
        },
        "frame": plan.frame.value,
        "message_type": plan.message_type,
        "publish": [
            {"signal": entry.signal_name, "target": entry.target}
            for entry in plan.publish
        ],
        "subscribe": [
            {"signal": entry.signal_name, "target": entry.target}
            for entry in plan.subscribe
        ],
    }
