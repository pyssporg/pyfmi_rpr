# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Own the RPR entity-state SysML port (`sysml/rpr_entity.sysml`), moved from
  `pysos_rpr`; the protobuf vocabulary and its schema table stay upstream.
- Declare `RprContract.version = "rpr.v2"` on `RprEntity`, so a consumer can
  check the port against the implemented proto package.

### Changed

- Require `pyfmi-interop>=0.6.0`; the retained IR/schema/wire surface is compatible (2026-11-22).

## [0.1.0] - 2026-11-19

First functional release: manifest-owned identity, projection of the RPR
subset, frame conversions, deterministic payloads, one-way and two-way UDP
bridges, and the `plan`/`bridge` CLI.

### Added

- `pyfmi_rpr.manifest`: strict `AdapterManifest`, `EntityIdentity`, `Origin`
  and `Frame` with typed `ManifestError` failures. Identity, marking, force and
  exercise live on the manifest; the model interface never carries them.
- `pyfmi_rpr.projection`: `projection_plan` now resolves every non-parameter
  signal to a canonical RPR attribute (`spatial.world_location.*`,
  orientation, velocity, acceleration, angular velocity, dead reckoning,
  marking, force, entity type, platform kind, frozen hint) and every input to
  an incoming RPR field. It rejects unknown, duplicate, unmapped,
  identity-owned and type-incompatible mappings by signal name.
- `plan_from_bundle`: build a plan from an extracted FMU directory, using
  `wire.json` and cross-checking `<Model>.proto`.
- `pyfmi_rpr.frames`: local WGS84/ECEF/ENU and body-frame conversions with an
  explicit origin and no runtime `pysos_interop` dependency.
- `pyfmi_rpr.codec`: `to_rpr(plan, values, t)` and `from_rpr(plan, payload)`;
  deterministic bytes, no clock reads, documented Euler/body-rate conventions.
- `pyfmi_rpr.generic`: dynamic `<Model>Payload` descriptor from the packaged
  `wire.json`, generic frame encode/decode through `pyfmi_interop.wire`, and
  `encode_generic_inputs` for the A3 reverse seam.
- `pyfmi_rpr.bridge` and `python -m pyfmi_rpr plan|bridge`: one-direction
  generic-wire -> RPR UDP bridge with `--dry-run`.
- `pyfmi_rpr.bridge.Bridge` (A3): one object owning the publish and subscribe
  paths with a single `start`/`step`/`close` lifecycle (or synchronous
  `run(duration, timestamp_ns=...)`). Both directions use separate sockets and
  endpoints; `step` drains queued datagrams, `run` waits at most 1 ms per poll,
  and no thread is created.
- Subscribe path: RPR payloads are decoded, projected onto the plan's input
  signals and re-encoded as a generic wire frame whose envelope carries the
  packaged `wire.json` model id, the caller's instance id, a monotonically
  increasing per-bridge sequence and the caller's timestamp. The bridge never
  reads a clock to fill a frame.
- Anti-loop construction: a frame received as RPR can only leave as generic
  wire and a frame received as generic wire can only leave as RPR; aliased
  self-echo endpoints are rejected when the bridge is constructed.
- `BridgeStats` reports counters per direction and a tuple of `FrameFailure`
  records (direction, peer endpoint, error). Malformed frames are reported
  there, in `last_error`, through `on_error`, or raised with
  `raise_on_bad_frame=True`; bind and send errors raise `BridgeError` naming
  the direction and endpoint.
- `python -m pyfmi_rpr bridge` now takes `--generic-listen`, `--rpr-listen`,
  `--rpr-send`, `--generic-send`, `--instance`, `--duration`, `--timestamp-ns`
  and `--strict`, and prints per-direction counters plus every failure.
- Tests: two bridge instances over real UDP loopback sockets exchange RPR in
  both directions and assert each side's projected values within tolerance;
  no-echo both ways; monotonic sequence and caller timestamp; malformed-frame
  and bind-error reporting with direction and endpoint.
- Tests for manifest identity ownership, full projection round trip, ENU/ECEF
  parity with `pysos_interop.geo` (dev-only), rejection cases, determinism, the
  generic wire round trip, the bridge and an end-to-end
  schema-bundle -> frame -> RPR `PhysicalEntity` path.

### Changed

- The `tests` workflow no longer carries a `PYSSP_READ_TOKEN` branch:
  `pysos-rpr` is public, both pinned wheels install anonymously from their
  release URLs, and the RPR-dependent tests run on Python 3.11, 3.12 and 3.13.

### Packaging

- Package `pyfmi_rpr` with `__version__ = "0.1.0"`, a `src/` layout and the
  `python -m pyfmi_rpr` entry point.
- Exact release-wheel pins for `pyfmi-interop` 0.3.0 and `pysos-rpr` 0.1.0,
  plus the `protobuf>=5.29,<6` runtime; `allow-direct-references = true`.
- Package contract tests for the version, the pinned sibling distribution
  versions, the IR and wire imports, the vocabulary import, and the seam.
- `tests` and `wheels` workflows adapted from `pysos_interop`; the `wheels`
  workflow attaches the wheel and sdist to the tag release.

### Not proven

- No exchange between two real models: the bridge is exercised with synthetic
  frames on both sides.
- No full FMU step loop: `Bridge.step`/`Bridge.run` are driven synchronously by
  the tests.
- Transport tested over UDP loopback only; no network, loss, reordering or
  federation transport is covered.

### Compatibility

- Python >= 3.11, required by the `pysos-rpr` generated bindings.
- `import pyfmi_rpr` imports the IR through `pyfmi_interop`; it imports no
  `pysos_rpr` module and decodes or encodes nothing.
