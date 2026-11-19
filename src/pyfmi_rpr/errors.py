"""Typed failures raised by the adapter.

Every error derives from :class:`AdapterError` so a caller that only wants
"this instance cannot be adapted" catches one type.  The subclasses name the
layer that rejected the input: the manifest, the projection plan, frame
conversion, the RPR codec, the generic wire payload, the schema bundle, or the
bridge loop.
"""

from __future__ import annotations

__all__ = [
    "AdapterError",
    "BridgeError",
    "BundleError",
    "CodecError",
    "FrameError",
    "GenericWireError",
    "ManifestError",
    "ProjectionPlanError",
]


class AdapterError(Exception):
    """Base class for every adapter failure."""


class ManifestError(AdapterError, ValueError):
    """The federation manifest is missing, malformed or out of range."""


class ProjectionPlanError(AdapterError, ValueError):
    """A model signal cannot be projected onto the RPR vocabulary."""


class FrameError(AdapterError, ValueError):
    """A frame conversion received a non-finite or degenerate value."""


class CodecError(AdapterError, ValueError):
    """A value or payload cannot be encoded or decoded as RPR state."""


class GenericWireError(CodecError):
    """The generic wire payload or its envelope is inconsistent with the plan."""


class BundleError(AdapterError, ValueError):
    """A packaged ``wire.json`` / ``<Model>.proto`` bundle is incomplete."""


class BridgeError(AdapterError, RuntimeError):
    """The one-direction bridge cannot run its configuration."""
