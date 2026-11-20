"""Package contract: version, pinned distributions, imports and the seam."""

from __future__ import annotations

import importlib.metadata
import importlib.util

import pytest

import pyfmi_rpr

# A checkout without the release wheels still has to collect and run this
# suite, so the vocabulary checks report a skip instead of an import error.
HAS_RPR = importlib.util.find_spec("pysos_rpr") is not None


def test_version() -> None:
    assert pyfmi_rpr.__version__ == "0.1.0"


def test_ir_and_wire_import() -> None:
    import pyfmi_interop
    import pyfmi_interop.schema
    import pyfmi_interop.wire

    assert pyfmi_interop.__version__ == "0.5.0"
    assert callable(pyfmi_interop.wire.encode)
    assert callable(pyfmi_interop.wire.decode)
    assert callable(pyfmi_interop.schema.build_schema)


@pytest.mark.skipif(not HAS_RPR, reason="pysos-rpr release wheel is not installed")
def test_vocabulary_import() -> None:
    from pysos_rpr import messages

    assert callable(messages.encode)
    assert callable(messages.decode)


def test_pinned_ir_version() -> None:
    assert importlib.metadata.version("pyfmi-interop") == "0.5.0"


@pytest.mark.skipif(not HAS_RPR, reason="pysos-rpr release wheel is not installed")
def test_pinned_vocabulary_version() -> None:
    assert importlib.metadata.version("pysos-rpr") == "0.1.0"


def test_projection_plan_is_available_and_identity_is_manifest_owned() -> None:
    from pyfmi_interop.ir import DataType, Direction, ModelDefinition, Signal

    from pyfmi_rpr.manifest import AdapterManifest, EntityIdentity, Origin

    definition = ModelDefinition(
        name="demo",
        guid="demo-guid",
        step_size_s=0.01,
        signals=(Signal("x", 1, DataType.REAL, Direction.OUTPUT),),
    )
    manifest = AdapterManifest(
        identity=EntityIdentity(site=1, application=2, entity=3),
        origin=Origin(57.7, 12.9, 100.0),
        mapping={"x": "position.x"},
    )
    plan = pyfmi_rpr.projection_plan(definition, manifest)

    assert plan.entity_id == "1:2:3"
    assert plan.publish[0].target == "spatial.world_location.x"


def test_package_import_does_not_import_the_vocabulary() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, pyfmi_rpr; "
            "print(sorted(m for m in sys.modules if m.startswith('pysos_')))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "[]"
