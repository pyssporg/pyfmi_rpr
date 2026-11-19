"""FMU-side adapter between the realtime IR and the RPR-derived vocabulary.

``pyfmi_rpr`` projects :class:`pyfmi_interop.ir.ModelDefinition` signals onto
the messages in :mod:`pysos_rpr.messages`, so that one real-time FMU can publish
its outputs as RPR entity state and subscribe its inputs from the same
vocabulary.  The adapter translates; it never becomes a second vocabulary.

Entity identity — site, application, entity, marking — comes from the
federation manifest that launches the FMU, never from the model definition: one
model may be instantiated as several entities in one federation.

The projection itself is A2 and the runtime glue is A3.  At 0.1.0 only the seam
exists: :func:`projection_plan` is documented and typed, and refuses to build a
plan rather than returning a half-truth callers could depend on.
"""

from __future__ import annotations

from .projection import ProjectionEntry, ProjectionPlan, projection_plan

__version__ = "0.1.0"

__all__ = ["ProjectionEntry", "ProjectionPlan", "__version__", "projection_plan"]
