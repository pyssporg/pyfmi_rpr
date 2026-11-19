# AGENTS

## Vision first (required)

Before you read code, edit files, or plan a change, read:

**`docs/breakdown/00-intent/intent.md`**

It states why this repository exists, what it commits to, and what it refuses
to become. Judge every change against it. If a change conflicts with the
intent, stop and surface the conflict; do not implement it silently.

## Repository focus

`pyfmi_rpr` is the FMU-side adapter that projects the realtime IR from
`pyfmi_interop.ir` onto the RPR-derived vocabulary in `pysos_rpr.messages`. It
publishes FMU outputs and subscribes FMU inputs; it owns neither side.

Translation happens at the **wire boundary**, not in generated code.

- `manifest` — identity, explicit WGS84 origin, model-side frame, signal map.
- `projection` — the pure plan: signal -> canonical RPR attribute.
- `frames` — local WGS84/ECEF/ENU/body conversions; no `pysos_interop`.
- `codec` — values -> RPR payload and back, with frame conversion.
- `generic` — decode/encode the `pyfmi_interop` envelope and `<Model>Payload`
  dynamically from the packaged `wire.json`; no `protoc` at runtime.
- `bridge` — `Bridge`: two-way generic-wire <-> RPR UDP, one lifecycle,
  caller-supplied timestamps, no threads.
- `cli` — `python -m pyfmi_rpr plan|bridge`.
- It depends on exactly two sibling releases and the protobuf runtime.

## Hard constraints

- **Translation only.** This package does not own the IR, the vocabulary, or
  the wire envelope. A change to a payload shape belongs upstream, in
  `pyfmi_interop` or `pysos_rpr`. Do not change generated model code.
- **No second vocabulary.** Do not define message-shaped dataclasses that
  mirror the protobuf messages; construct and consume the generated messages.
- **Identity comes from the federation manifest.** Never read site,
  application, entity or marking out of a model definition, and never add them
  to the IR. `entity_identifier.*` is not a legal mapping target.
- **No hidden origin.** Every frame conversion takes the manifest origin.
  There is no global or process-wide default.
- **Sibling pins are immutable release-wheel URLs.** Do not relax them to PyPI
  names or version ranges; a sibling rebuild must not silently change this
  package.
- **`pysos_interop` is dev-only.** Never import it at runtime; it is only a
  parity oracle in tests.
- **The seam stays honest.** A placeholder raises; it never returns an empty or
  partial plan that a caller could mistake for a complete one.
- **No scheduling.** The adapter converts values at the step boundary. The
  bridge drains both directions synchronously from caller-driven `step`/`run`;
  threads, clocks and run control belong to the runtime and its orchestrator.
  Frame content never comes from a clock read.
- **No echo.** Publish and subscribe are separate paths with separate sockets
  and encoders: RPR in can only leave as generic wire, generic wire in can only
  leave as RPR.
- **Deterministic bytes.** No clock reads. Every timestamp, sequence and
  instance id is caller-supplied.

## Code guidelines

- `src/` layout, Python >= 3.11, line length 100, ruff `E`, `F`, `I`, `B`.
- Frozen dataclasses and explicit arguments; no hidden global state and no
  process-wide identity.
- Tests pin the package contract: version, the exact sibling distribution
  versions, and the imports the adapter promises.

## Environment

- Install: `pip install -e .` (or `--no-deps` inside a workspace where the
  pinned sibling wheels are already present).
- Tests: `python -m pytest`; lint: `python -m ruff check src tests`.
- Tests that need the `pysos_rpr` release wheel skip when it is not installed;
  CI installs it anonymously and runs them on every supported Python.
