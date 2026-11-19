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

- Modules: `projection` (the IR-to-vocabulary mapping) and, from A3, the
  runtime glue that drives it from the FMU step loop.
- It depends on exactly two sibling releases and the protobuf runtime.

## Hard constraints

- **Translation only.** This package does not own the IR, the vocabulary, or
  the wire envelope. A change to a payload shape belongs upstream, in
  `pyfmi_interop` or `pysos_rpr`.
- **No second vocabulary.** Do not define message-shaped dataclasses that
  mirror the protobuf messages; construct and consume the generated messages.
- **Identity comes from the federation manifest.** Never read site,
  application, entity or marking out of a model definition, and never add them
  to the IR.
- **Sibling pins are immutable release-wheel URLs.** Do not relax them to PyPI
  names or version ranges; a sibling rebuild must not silently change this
  package.
- **The seam stays honest.** A placeholder raises; it never returns an empty or
  partial plan that a caller could mistake for a complete one.
- **No scheduling and no I/O policy.** The adapter converts values at the step
  boundary. Sockets, threads, clocks and run control belong to the runtime and
  its orchestrator.

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
