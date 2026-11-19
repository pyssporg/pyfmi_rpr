"""Projection of the realtime IR onto the RPR-derived vocabulary.

This module names the seam, not the translation.  It defines the value a
projection produces and the call that produces it; A2 fills in the mapping from
IR signals to RPR message fields and A3 drives the resulting plan from the FMU
step loop.

The plan is a pure value.  For the same definition and the same identity it
must be identical every time, because a plan that drifts between two runs turns
a wire difference into a debugging session.

Identity is an argument, never a field of the model: a model definition is
reusable and carries no entity, while a launched FMU instance is one entity in
one federation.  The identity is owned by the federation manifest.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyfmi_interop.ir import Direction, ModelDefinition


@dataclass(frozen=True)
class ProjectionEntry:
    """One IR signal and the RPR field it is projected onto.

    ``target`` is a dotted path into the vocabulary, for example
    ``"spatial.position.ecef_m"``.  A2 fixes the path set; keeping it a string
    here means the plan shape does not have to change when that set is chosen.
    """

    signal_name: str
    value_reference: int
    direction: Direction
    target: str


@dataclass(frozen=True)
class ProjectionPlan:
    """The publish and subscribe entries for one FMU instance.

    ``entity_id`` is the federation-manifest identity, passed through as an
    opaque string.  It never comes from the model definition.
    """

    model_name: str
    entity_id: str
    publish: tuple[ProjectionEntry, ...]
    subscribe: tuple[ProjectionEntry, ...]


def projection_plan(definition: ModelDefinition, *, entity_id: str) -> ProjectionPlan:
    """Return the publish and subscribe projection of ``definition``.

    Placeholder for A2.  It validates nothing and maps nothing, and it
    deliberately returns nothing: a plan built from a partial mapping would be a
    contract callers could depend on, so this call raises instead.

    Parameters are for publish-only projections too: ``Direction.PARAMETER``
    signals are model configuration, not wire state, and are not projected in
    either direction.
    """
    raise NotImplementedError("A2")
