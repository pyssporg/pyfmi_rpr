# Layers

The package is an edge adapter with a single seam. It imports the IR and the
vocabulary; neither imports it back.

```
projection.py     projection_plan, ProjectionPlan, ProjectionEntry
      |
   pyfmi_interop.ir        pysos_rpr.messages
   ModelDefinition,        EntityIdentifier, Spatial,
   Signal, Direction       BaseEntity, Platform
```

## `projection`

`ProjectionEntry` binds one IR signal (`signal_name`, `value_reference`,
`direction`) to one vocabulary `target`. `ProjectionPlan` is the pair of
publish and subscribe tuples for one instance, plus the model name and the
manifest identity. The value is frozen and carries no runtime state.

`projection_plan` is a pure function of the definition and the identity. At
0.1.0 it raises `NotImplementedError("A2")`: the plan shape is a contract, and
returning an empty plan would let callers build against a mapping that does not
exist yet.

## Upstream layers (not this repository)

- `pyfmi_interop.ir` owns the model definition, signal directions, value
  references, rates and units. `pyfmi_interop.wire` owns the byte envelope.
- `pysos_rpr.messages` owns the entity vocabulary and its generated bindings.
  The proto definitions are the single source; bindings are projections.
- `pysos_interop.rpr` owns the entity-state codec and the frame conversions
  around the vocabulary. This package neither re-implements them nor imports
  `pysos_interop`.

## Rules

| Layer | May import | Must not import |
| --- | --- | --- |
| `projection` | `pyfmi_interop.ir`, `pysos_rpr.messages` | sockets, clocks, threads, `pysos_interop` |
| package `__init__` | `.projection` | `pysos_rpr`, wire code, scheduling |

## Direction of a projection

A signal's `Direction` decides where it goes and is never inferred from its
name:

- `OUTPUT` becomes a **publish** entry: FMU value to vocabulary field.
- `INPUT` becomes a **subscribe** entry: vocabulary field to FMU value.
- `PARAMETER` is projected in neither direction; it configures the model.

Identity is not modelled here at all. The plan carries the manifest's identity
string so the caller can construct `pysos_rpr.messages.EntityIdentifier`
without the model ever holding it.

## A3 boundary

Runtime glue belongs in a later layer: it reads the plan, reads and writes FMU
values at the step boundary, and hands message construction to
`pysos_rpr.messages`. The plan itself does no I/O, which is what keeps A3
testable without a running FMU.
