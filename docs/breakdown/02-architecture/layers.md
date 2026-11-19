# Layers

The package is an edge adapter with one translation boundary: the generic wire.
It imports the IR and the vocabulary; neither imports it back.

```
cli / bridge            plan, two-way UDP publish + subscribe
     |
  codec                 values <-> RPR payload, frame conversion
     |
 projection             signal -> canonical RPR attribute
     |
  manifest              identity, explicit origin, frame, mapping
     |
pyfmi_interop.ir/schema/wire      pysos_rpr.messages
     |                                  |
  ModelDefinition, Signal          EntityIdentifier, EntityType,
  Direction, wire.json             Marking, Spatial, Platform, Aircraft
```

`frames` is a leaf helper used by `codec` and the parity tests.

## `manifest`

`AdapterManifest` is the adapter's own input model: `EntityIdentity`
(`site`, `application`, `entity`, `marking`, `force`, `exercise`), an explicit
WGS84 `Origin`, a `Frame` (`enu` or `ecef`) for position and linear kinematics,
and the `signal -> RPR attribute` mapping. It validates strictly and raises
`ManifestError`. No default origin and no process-wide identity exist.

`exercise` is carried but not encoded: `pysos_rpr` 0.1.0 has no exercise field.

## `projection`

`ProjectionEntry` binds one non-parameter IR signal (`signal_name`,
`value_reference`, `data_type`, `direction`) to one canonical RPR `target`.
`ProjectionPlan` is the publish and subscribe tuple for one instance, the model
identity (`model_id`, payload message, guid, step size), the manifest identity,
origin and frame, and the static entity type / platform / dead-reckoning
values.

`projection_plan(definition | wire.json, manifest)` is a pure function. It
rejects unknown, duplicate, unmapped, identity-owned and type-incompatible
targets by signal name. `plan_from_bundle` additionally cross-checks the
packaged `<Model>.proto` against `wire.json`.

The canonical target paths are the protobuf paths. Short aliases such as
`position.x`, `orientation.yaw`, `velocity.z`, `angular_velocity.x`,
`acceleration.y`, `marking`, `force`, `dr.algorithm` and `platform.kind` are
folded onto them before the plan is built.

## `frames` and `codec`

`frames` implements WGS84 geodetic -> ECEF, ENU <-> ECEF and body <-> ENU
conversions locally. It never imports `pysos_interop`; a development-only test
compares the results with `pysos_interop.geo` within 1e-6 m.

`codec` owns the value translation:

- position is ECEF in RPR; the model side is ENU relative to the manifest origin
  or ECEF;
- velocity and acceleration are body-frame in RPR; the model side is ENU or
  ECEF and is rotated with the Euler attitude;
- orientation is Z-Y-X `(psi, theta, phi)` = `(yaw, pitch, roll)` radians,
  matching `pysos_interop.EntityState.orientation_rps`;
- angular velocity is body-frame rad/s.

`to_rpr(plan, values, t)` and `from_rpr(plan, payload)` use
`pysos_rpr.messages` for encoding and decoding. `t` is accepted and not
encoded: RPR has no time field, and the codec never reads a clock.

## `generic` and `bridge`

`generic` reconstructs the model's `<Model>Payload` protobuf dynamically from
the plan (which was built from `wire.json`), so decoding a real generic frame
needs no `protoc` and no generated code. `pyfmi_interop.wire` owns the 48-byte
envelope for that side only. `encode_generic_frame` rebuilds that envelope from
the packaged `wire.json` model id, a caller-supplied instance id and timestamp,
and the bridge's monotonic sequence.

`bridge` owns both directions with one lifecycle. The publish path listens for
generic frames on `generic_listen` and sends RPR to `rpr_send`; the subscribe
path listens for RPR on `rpr_listen` and sends generic frames to `generic_send`.
The paths share no socket, endpoint or encoder, so a received RPR payload can
only leave as generic wire and a received generic frame can only leave as RPR.
`step` drains queued datagrams, `run(duration, timestamp_ns=...)` polls with
waits of at most 1 ms, and there is no thread and no clock read for frame
content. `dry_run` translates without sending.

Malformed frames are recoverable and reported: `BridgeStats.failures` carries
`(direction, peer endpoint, error)` for each, and `raise_on_bad_frame` turns
them into a `BridgeError` with the same attribution. Bind and send failures
raise `BridgeError` naming the direction and endpoint.

## Rules

| Layer | May import | Must not import |
| --- | --- | --- |
| `manifest` | stdlib, `errors` | pyfmi, pysos, sockets |
| `projection` | `manifest`, `pyfmi_interop.ir/schema/wire` | `pysos_rpr`, `pysos_interop`, sockets, clocks |
| `frames` | `manifest`, stdlib | `pysos_interop`, pyfmi, pysos_rpr |
| `codec` | `manifest`, `projection`, `frames`, `pysos_rpr.messages` | `pysos_interop`, sockets, clocks |
| `generic` | `projection`, `codec`, `pyfmi_interop.wire` | sockets, clocks |
| `bridge` | `codec`, `generic`, stdlib sockets/select | run control, schedulers, threads |
| package `__init__` | `.manifest`, `.projection` | `pysos_rpr`, wire code, bridge, scheduling |

## Direction of a projection

A signal's `Direction` decides where it goes and is never inferred from its
name:

- `OUTPUT` becomes a **publish** entry: FMU value to RPR attribute.
- `INPUT` becomes a **subscribe** entry: RPR attribute to FMU value.
- `PARAMETER` is projected in neither direction; it configures the model.

Identity is not modelled here at all. The plan carries the manifest's identity
so the caller can construct `pysos_rpr.messages.EntityIdentifier` without the
model ever holding it.

## Runtime boundary

The bridge is the only I/O in the package. It still does not schedule itself:
the caller owns the step loop, supplies every timestamp, and calls `step` or
`run`; the plan and codec stay pure. An FMU runtime that already has a socket
can keep using `run_bridge` for the publish direction, but the two-way
lifecycle is `Bridge`.

Proof of both directions over real UDP: `tests/test_bridge_twoway.py` runs two
bridge instances with distinct packaged bundles and manifest identities on
loopback, exchanges RPR in both directions and asserts the projected values
within tolerance. A manual generated-model check builds one codegen fixture
with `-DPYFMI_INTEROP_WIRE=protobuf` and decodes the frame printed by its
`wire_conformance` binary through `plan_from_bundle`; the full FMU run is not
part of the suite.
