"""Package contract: version, pinned distributions, imports and the seam."""

from __future__ import annotations

import importlib.metadata
import importlib.util

import pytest

import pyfmi_rpr

# The pysos-rpr release lives in a private repository.  A checkout without the
# release wheel still has to collect and run the public half of this suite, so
# the vocabulary checks report a skip instead of an import error.
HAS_RPR = importlib.util.find_spec("pysos_rpr") is not None


def test_version() -> None:
    assert pyfmi_rpr.__version__ == "0.1.0"


def test_ir_and_wire_import() -> None:
    import pyfmi_interop
    import pyfmi_interop.schema
    import pyfmi_interop.wire

    assert pyfmi_interop.__version__ == "0.3.0"
    assert callable(pyfmi_interop.wire.encode)
    assert callable(pyfmi_interop.wire.decode)
    assert callable(pyfmi_interop.schema.build_schema)


@pytest.mark.skipif(not HAS_RPR, reason="pysos-rpr release wheel is not installed")
def test_vocabulary_import() -> None:
    from pysos_rpr import messages

    assert callable(messages.encode)
    assert callable(messages.decode)


def test_pinned_ir_version() -> None:
    assert importlib.metadata.version("pyfmi-interop") == "0.3.0"


@pytest.mark.skipif(not HAS_RPR, reason="pysos-rpr release wheel is not installed")
def test_pinned_vocabulary_version() -> None:
    assert importlib.metadata.version("pysos-rpr") == "0.1.0"


def test_projection_plan_is_a_declared_seam() -> None:
    from pyfmi_interop.ir import ModelDefinition

    definition = ModelDefinition(name="demo", guid="demo-guid", step_size_s=0.01)
    with pytest.raises(NotImplementedError, match="A2"):
        pyfmi_rpr.projection_plan(definition, entity_id="site:app:entity")
