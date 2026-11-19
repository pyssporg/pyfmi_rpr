---
id: INFO-001
type: info
title: Intent
summary: "Why pyfmi_rpr exists: project the realtime FMU IR onto the RPR-derived vocabulary in both directions, and own nothing else"
date: 2026-11-19
status: current
---

# Intent

## Purpose

`pyfmi_rpr` is the FMU-side adapter between two packages that own their own
contracts: the realtime IR from `pyfmi_interop.ir` and the RPR-derived
vocabulary from `pysos_rpr.messages`. It projects FMU outputs onto entity state
for publishing and entity state onto FMU inputs for subscribing, so a
real-time FMU participates in a federation without learning the vocabulary's
message layout and without the vocabulary learning FMI.

## Scope

| Belongs here | Belongs elsewhere |
| --- | --- |
| IR signal to vocabulary field projection (A2) | the IR, value references and payload schema (`pyfmi_interop`) |
| publish and subscribe direction handling | the entity model and protocol codecs (`pysos_interop`) |
| value conversion at the FMU step boundary (A3) | frame conversion and dead reckoning (`pysos_interop.rpr`) |
| the plan that binds signals to vocabulary targets | protobuf messages and their generated bindings (`pysos_rpr`) |
| explicit identity input from the manifest | federation manifest and process supervision (`pysos_coordinate`) |

## Commitments

- **Translation, not ownership.** This package defines no payload, no message
  and no entity model. When a shape must change, the change belongs upstream.
- **Both directions, one plan.** Publishing and subscribing are read from the
  same projection plan so a model cannot publish on one field and subscribe on
  another.
- **Identity is manifest-owned.** Site, application, entity and marking arrive
  as explicit arguments. They are never read from, or added to, the model.
- **The seam is honest.** A placeholder raises. It never returns an empty or
  partial plan that a caller could mistake for a complete mapping.
- **Immutable sibling pins.** The two sibling dependencies are pinned to exact
  release-wheel URLs, never to PyPI names or ranges.
- **Small and pure.** Plan construction is a pure function of the definition
  and the identity; nothing global, nothing mutable.

## Non-goals

- Scenario authoring, federation launch, port allocation, or run control.
- Time synchronisation, scheduling, or the master algorithm.
- Encoding the wire envelope; framing belongs to `pyfmi_interop.wire`.
- Owning a second entity model or caching protocol state of its own.
- Treating an FMU model as an entity: one model may be launched as several
  entities, and this package must keep that true.

## Success

An FMU author can hand the adapter a `ModelDefinition` and the manifest
identity of the instance and receive a plan that says exactly which output
publishes to which vocabulary field and which input subscribes from which
field — with no protocol knowledge in the model and no FMI knowledge in the
vocabulary.
