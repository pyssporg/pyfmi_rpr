"""I/O boundary for packaged model bundles.

Plan construction is pure in :mod:`pyfmi_rpr.projection`; this module is the
one adapter that reads a packaged artifact from disk.  It loads ``wire.json``
from an extracted ``.fmu`` directory and cross-checks it against the
``<Model>.proto`` before handing the decoded mapping to the pure projection.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .errors import BundleError
from .manifest import AdapterManifest
from .projection import ProjectionPlan, projection_plan

__all__ = ["plan_from_bundle"]

_FIELD_RE = re.compile(r"^\s*Value\s+(\w+)\s*=\s*(\d+)\s*;\s*$", re.MULTILINE)


def plan_from_bundle(
    directory: str | Path,
    manifest: AdapterManifest,
) -> ProjectionPlan:
    """Build a plan from a packaged directory containing ``wire.json`` and proto.

    Both artifacts are required and are cross-checked: the ``<Model>.proto``
    must declare exactly the payload message and ``Value`` fields the
    ``wire.json`` descriptor names.  An extracted ``.fmu`` directory with the
    artifacts under ``binaries/<platform>/`` works too.
    """

    root = Path(directory)
    wire_path = _find_one(root, "wire.json")
    try:
        wire_data = json.loads(wire_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"cannot read {wire_path}: {exc}") from exc
    if not isinstance(wire_data, Mapping):
        raise BundleError(f"{wire_path} does not contain a JSON object")
    model_name = wire_data.get("model")
    if not isinstance(model_name, str) or not model_name:
        raise BundleError(f"{wire_path} does not name a model")
    proto_path = _find_one(root, f"{model_name}.proto")
    _check_proto(proto_path, wire_data)
    return projection_plan(wire_data, manifest)


def _find_one(root: Path, name: str) -> Path:
    if not root.exists():
        raise BundleError(f"bundle directory does not exist: {root}")
    if root.is_file() and zipfile.is_zipfile(root):
        raise BundleError("pass an extracted FMU directory, not the .fmu archive")
    if not root.is_dir():
        raise BundleError(f"bundle path is not a directory: {root}")
    matches = sorted(path for path in root.rglob(name) if path.is_file())
    if not matches:
        raise BundleError(f"{name} not found under {root}")
    if len(matches) > 1:
        raise BundleError(f"multiple {name} files under {root}: {matches}")
    return matches[0]


def _check_proto(path: Path, wire_data: Mapping[str, Any]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BundleError(f"cannot read {path}: {exc}") from exc
    payload_message = wire_data.get("payload_message")
    if not isinstance(payload_message, str) or f"message {payload_message} {{" not in text:
        raise BundleError(f"{path} does not declare message {payload_message!r}")
    fields = {name: int(identifier) for name, identifier in _FIELD_RE.findall(text)}
    expected = {
        str(item["name"]): int(item["id"])
        for item in wire_data.get("signals", ())
        if isinstance(item, Mapping) and "name" in item and "id" in item
    }
    if fields != expected:
        missing = sorted(set(expected) - set(fields))
        extra = sorted(set(fields) - set(expected))
        mismatched = sorted(
            name for name in set(fields) & set(expected) if fields[name] != expected[name]
        )
        detail = ", ".join(
            part
            for part in (
                f"missing={missing}" if missing else "",
                f"extra={extra}" if extra else "",
                f"id-mismatch={mismatched}" if mismatched else "",
            )
            if part
        )
        raise BundleError(f"{path} Value fields do not match wire.json ({detail})")
