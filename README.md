# pyfmi_rpr

`pyfmi_rpr` is the FMU-side adapter between the realtime IR and the
RPR-derived protobuf vocabulary. It takes a model definition from
`pyfmi_interop.ir` and projects its signals onto the messages defined by
`pysos_rpr.messages`, so a real-time FMU speaks the same entity vocabulary as
the rest of a federation.

Translation happens **at the wire boundary**, not in generated code.
`pyfmi_interop` 0.6.0 emits models that speak a generic wire (48-byte envelope
around a `<Model>Payload` protobuf, described by the packaged `wire.json`).
This package decodes that generic frame, projects the signal values, and
publishes RPR messages. It never changes the generated model.

Contributors read [`AGENTS.md`](AGENTS.md); current contracts live in
[`docs/breakdown/02-architecture/layers.md`](docs/breakdown/02-architecture/layers.md).

## Two directions

- **Publish.** Generic-wire signal values are projected onto RPR entity-state
  fields and encoded with the `pysos_rpr` codec.
- **Subscribe.** RPR entity-state payloads are decoded and projected onto model
  inputs; the bridge re-encodes those inputs as one generic wire frame.

`Direction.PARAMETER` signals are model configuration and are projected in
neither direction. The IR, not this package, owns the payload schema;
`pyfmi_interop.schema` remains the emitter for a model's own payload.

## Bridge

`pyfmi_rpr.bridge.Bridge` owns both directions with one lifecycle. The two paths have
separate sockets, separate endpoints and separate encoders:

| Path | Listens on | Sends to | Translation |
| --- | --- | --- | --- |
| publish | `generic_listen` (model frames) | `rpr_send` (federation) | generic decode -> projection -> RPR encode |
| subscribe | `rpr_listen` (federation payloads) | `generic_send` (model) | RPR decode -> inputs -> generic encode |

```python
from pyfmi_rpr.bridge import Bridge
from pyfmi_rpr.manifest import load_manifest
from pyfmi_rpr.bundle import plan_from_bundle

plan = plan_from_bundle("extracted_fmu/", load_manifest("manifest.json"))
bridge = Bridge(
    plan,
    generic_listen=("0.0.0.0", 5005),
    rpr_listen=("0.0.0.0", 6005),
    rpr_send=("127.0.0.1", 6006),
    generic_send=("127.0.0.1", 5006),
    instance=1,
)
with bridge:
    stats = bridge.step(timestamp_ns=1_700_000_000_000_000_000)
    # or: bridge.run(0.5, timestamp_ns=clock_ns_provider)
```

- The generic envelope is rebuilt from the packaged `wire.json` model id, the
  caller's `instance`, a monotonically increasing per-bridge sequence and the
  caller's `timestamp_ns`. The bridge never reads a clock to fill a frame.
- `step()` drains what is already queued (waiting at most `timeout_s`);
  `run(duration, timestamp_ns=...)` polls with waits of at most 1 ms. No
  thread is created.
- A frame that arrives as RPR can only leave as generic wire, and a frame that
  arrives as generic wire can only leave as RPR. Construction rejects aliased
  endpoints, so a self-echo loop cannot be configured.
- A malformed frame does not stop the bridge: it is recorded as a
  `FrameFailure` with its direction and peer endpoint, exposed in
  `BridgeStats.failures`/`last_error` and through `on_error`. Set
  `raise_on_bad_frame=True` to raise instead. Bind and send failures raise
  `BridgeError` naming the direction and endpoint.

The opposite side of each path is a plain UDP endpoint: the FMU runtime owns
its sockets, and the federation transport owns RPR delivery. Ports are chosen
by the caller; the bridge binds exactly what it is given.

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
    --generic-listen 0.0.0.0:5005 --rpr-listen 0.0.0.0:6005 \
    --rpr-send 127.0.0.1:6006 --generic-send 127.0.0.1:5006 \
    --instance 1 --duration 1.0 --dry-run
```

`plan` builds the plan from the packaged `wire.json` + `<Model>.proto` and
prints it. `bridge` runs both directions for `--duration` seconds and prints
per-direction counters plus every `FrameFailure` (direction, endpoint, error).
`--timestamp-ns` pins the caller timestamp; without it the CLI supplies the
wall clock once per poll. `--dry-run` translates without sending.

## Examples

[`examples/README.md`](examples/README.md) builds the packaged RPR entity
definition (`pyfmi_rpr.rpr_entity()`) into a standalone CoSimulation FMU and
inserts it as a component of a generated `.ssp`:

```bash
python examples/build_entity_fmu.py --out /tmp/rpr/entity
python examples/assemble_system.py --out /tmp/rpr/system
```

## Status

0.1.0 is the first functional release: manifest-owned identity, projection of
the RPR subset, frame conversions, deterministic payloads, one-way and two-way
UDP bridges, and the `plan`/`bridge` CLI. It is not proven against two real
models, a full FMU step loop, or any transport other than UDP loopback. The FMU
step loop still drives `Bridge.step`/`Bridge.run`; this package schedules
nothing.

## Install

The `pyfmi-interop` dependency requires the SysML-free 0.6.0 line, and
`pysos-rpr` is pinned to an immutable release wheel, so install against the
exact vocabulary artifact the package declares:

```bash
pip install -e ".[dev]"
```

This release was built and tested against `pyfmi-interop` 0.6.0 and
`pysos-rpr` v0.1.0 (`pysos_rpr-0.1.0-py3-none-any.whl`, pinned as an
immutable release URL).

In a workspace checkout the sibling packages are often already installed
editable; install with `pip install --no-deps -e .` then, so the declared pins
stay in place without re-resolving them, and install `pytest` and `ruff`
separately (or use the workspace venv that already has them).

## Development

```bash
python -m pytest
python -m ruff check src tests
```

### Generated-model evidence (manual)

A frame from a real generated model's wire path must decode through
`plan_from_bundle` and project to a valid RPR message. Build one fixture with
the protobuf wire mode, then decode what the binary prints:

```python
from pyfmi_interop.builder import build_model
from pyfmi_interop.codegen import generate_model
from pyfmi_interop.ir import DataType, Direction, ModelDefinition, Signal, deterministic_guid

model = ModelDefinition(
    name="a3_fixture", guid=deterministic_guid("a3_fixture"), step_size_s=0.01,
    signals=(Signal("p_e", 1, DataType.REAL, Direction.OUTPUT),
             Signal("cmd", 5, DataType.REAL, Direction.INPUT)),
)
generate_model(model, "/tmp/a3gen/src")
build_model("/tmp/a3gen/src", "/tmp/a3gen/build",
            cmake_args=["-DPYFMI_INTEROP_WIRE=protobuf"])
```

`/tmp/a3gen/build/wire_conformance` then prints one hex frame.

Then `decode_generic(plan_from_bundle('/tmp/a3gen/src', manifest), frame)`
yields the values and `to_rpr` yields a valid payload. On a host whose glibc
predates 2.38 the released runtime library needs a local
`__isoc23_strtoull` shim at link time; that is an environment workaround, not
a package requirement.

Python >= 3.11, `src/` layout.
