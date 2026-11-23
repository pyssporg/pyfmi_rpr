"""FMU-side adapter between the realtime IR and the RPR-derived vocabulary.

``pyfmi_rpr`` projects :class:`pyfmi_interop.ir.ModelDefinition` signals onto
the messages in :mod:`pysos_rpr.messages`, so that one real-time FMU can publish
its outputs as RPR entity state and subscribe its inputs from the same
vocabulary.  The adapter translates; it never becomes a second vocabulary.

Entity identity — site, application, entity, marking, force and exercise —
comes from the federation manifest that launches the FMU, never from the model
definition: one model may be instantiated as several entities in one
federation.

The codec and the generic wire helpers live in their own modules so importing
the package does not import ``pysos_rpr``; :class:`pyfmi_rpr.bridge.Bridge`
drives both directions from the step loop with a caller-supplied timestamp.
"""

from __future__ import annotations

from .definitions import rpr_entity
from .manifest import AdapterManifest, EntityIdentity, Frame, Origin
from .projection import ProjectionEntry, ProjectionPlan, projection_plan

__version__ = "0.1.0"

__all__ = [
    "AdapterManifest",
    "EntityIdentity",
    "Frame",
    "Origin",
    "ProjectionEntry",
    "ProjectionPlan",
    "__version__",
    "projection_plan",
    "rpr_entity",
]
