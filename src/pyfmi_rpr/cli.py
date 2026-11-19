"""Command line entry points for plan inspection and the one-way bridge."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .errors import AdapterError
from .manifest import load_manifest
from .projection import plan_from_bundle


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
            from .bridge import run_udp_bridge

            plan = _plan(args)
            stats = run_udp_bridge(
                plan,
                listen=_address(args.listen),
                send_to=None if args.dry_run else _address(args.send),
                max_frames=args.max_frames,
                timeout_s=args.timeout,
                dry_run=args.dry_run,
            )
            print(
                json.dumps(
                    {
                        "received": stats.received,
                        "published": stats.published,
                        "decode_errors": stats.decode_errors,
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

    bridge = subparsers.add_parser("bridge", help="run the generic-wire to RPR bridge")
    _bundle_arguments(bridge)
    bridge.add_argument("--listen", default="0.0.0.0:5005", help="host:port to receive on")
    bridge.add_argument("--send", default="127.0.0.1:5006", help="host:port to publish to")
    bridge.add_argument("--max-frames", type=int, default=None, help="stop after N datagrams")
    bridge.add_argument("--timeout", type=float, default=1.0, help="receive timeout seconds")
    bridge.add_argument("--dry-run", action="store_true", help="decode and project without sending")
    return parser


def _bundle_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--bundle", required=True, help="directory with wire.json and <Model>.proto"
    )
    parser.add_argument("--manifest", required=True, help="federation manifest JSON")


def _plan(args: argparse.Namespace):
    manifest = load_manifest(args.manifest)
    return plan_from_bundle(args.bundle, manifest)


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
