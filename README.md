# pyfmi_rpr

`pyfmi_rpr` is the FMU-side adapter between the realtime IR and the
RPR-derived protobuf vocabulary. It takes a model definition from
`pyfmi_interop.ir` and projects its signals onto the messages defined by
`pysos_rpr.messages`, so a real-time FMU speaks the same entity vocabulary as
the rest of a federation.

Translation happens **at the wire boundary**, not in generated code.
`pyfmi_interop` 0.3.0 emits models that speak a generic wire (48-byte envelope
around a `<Model>Payload` protobuf, described by the packaged `wire.json`).
This package decodes that generic frame, projects the signal values, and
publishes RPR messages. It never changes the generated model.

## Two directions

- **Publish.** Generic-wire signal values are projected onto RPR entity-state
  fields and encoded with the `pysos_rpr` codec.
- **Subscribe.** RPR entity-state payloads are decoded and projected onto model
  inputs; `encode_generic_inputs` re-encodes the generic payload for A3's step
  loop.

`Direction.PARAMETER` signals are model configuration and are projected in
neither direction. The IR, not this package, owns the payload schema;
`pyfmi_interop.schema` remains the emitter for a model's own payload.

## Identity and manifest

Entity identity — site, application, entity, marking, force and exercise — is
**not** part of the model. It comes from the federation manifest that launches
the instance. One model may be started as several entities in one federation.

The adapter manifest also declares the WGS84 origin, the model-side frame and
the signal mapping:

```json
{
  "identity": {
    "site": 10,
    "application": 20,
    "entity": 30,
    "marking": "FALCON",
    "force": "friendly",
    "exercise": 3
  },
  "origin": {
    "latitude_deg": 57.7,
    "longitude_deg": 12.9,
    "altitude_m": 100.0
  },
  "frame": "enu",
  "mapping": {
    "p_e": "position.x",
    "p_n": "position.y",
    "p_u": "position.z",
    "v_e": "velocity.x",
    "v_n": "velocity.y",
    "v_u": "velocity.z",
    "roll": "orientation.roll",
    "pitch": "orientation.pitch",
    "yaw": "orientation.yaw",
    "label": "marking",
    "force": "force"
  }
}
```

`exercise` is carried for federation bookkeeping; `pysos_rpr` 0.1.0 has no
exercise field, so it is not encoded into RPR messages (the same drop as
`pysos_interop.rpr`).

## Mapping surface

Canonical targets are protobuf paths; the shorter aliases in the example are
accepted and canonicalised by `pyfmi_rpr.projection`.

| Area | Targets | Signal type |
| --- | --- | --- |
| Position | `spatial.world_location.x/y/z` | real |
| Orientation | `spatial.orientation.psi/theta/phi` (aliases yaw/pitch/roll) | real |
| Velocity | `spatial.velocity.x/y/z` | real |
| Acceleration | `spatial.acceleration.x/y/z` | real |
| Angular velocity | `spatial.angular_velocity.x/y/z` | real |
| Dead reckoning | `spatial.dead_reckoning.algorithm/parameters` | integer / string |
| Frozen hint | `spatial.is_frozen` | boolean |
| Entity type | `entity_type.kind/domain/country/category/subcategory/specific/extra` | integer |
| Marking | `marking.characters`, `marking.character_set` | string / integer |
| Force | `force` | integer |
| Platform | `platform.kind` | integer |

`entity_identifier.site/application/entity` and `exercise` are manifest-owned
and cannot be mapped. A duplicate target, an unknown target, an unmapped
non-parameter signal, or a signal-type mismatch is rejected with the signal
name in the error.

## Frames

`frame` declares how the model's position, linear velocity and linear
acceleration are expressed: `enu` (metres/metres-per-second relative to the
explicit origin) or `ecef` (geocentric metres). RPR itself is always:

- position: geocentric ECEF metres;
- linear velocity and acceleration: body frame, m/s and m/s²;
- orientation: Euler `(psi, theta, phi)` = `(yaw, pitch, roll)` radians, Z-Y-X;
- angular velocity: body frame, rad/s.

The conversion lives in `pyfmi_rpr.frames` and has no runtime dependency on
`pysos_interop`. A development-only parity test compares it against
`pysos_interop.geo` within 1e-6 m when that package is installed.

## CLI

```bash
python -m pyfmi_rpr plan   --bundle extracted_fmu/ --manifest manifest.json
python -m pyfmi_rpr bridge --bundle extracted_fmu/ --manifest manifest.json \
    --listen 0.0.0.0:5005 --send 127.0.0.1:5006 --dry-run
```

`plan` builds the plan from the packaged `wire.json` + `<Model>.proto` and
prints it. `bridge` runs the publish direction over UDP; `--dry-run` decodes
and projects without sending. A3 adds the reverse direction on the same seam.

## Status

0.1.0 is the scaffold release; this tree adds the A2 projection, codec and
one-way bridge without a version bump (A4 owns the release). The runtime glue
that drives the plan from the FMU step loop is A3.

## Install

The siblings are pinned to immutable release wheels, so install against the
exact artifacts the package declares:

```bash
pip install -e .
```

In a workspace checkout the sibling packages are often already installed
editable; install this package with `--no-deps` then, so the pins stay declared
without re-resolving them.

## Development

```bash
python -m pytest
python -m ruff check src tests
```

Python >= 3.11, `src/` layout.
