# pyfmi_rpr

`pyfmi_rpr` is the FMU-side adapter between the realtime IR and the
RPR-derived protobuf vocabulary. It takes a model definition from
`pyfmi_interop.ir` and projects its signals onto the messages defined by
`pysos_rpr.messages`, so a real-time FMU speaks the same entity vocabulary as
the rest of a federation.

The adapter sits at the edge of the model. It owns translation and nothing
else: no scenarios, no scheduling, no second schema.

## Two directions

- **Publish.** FMU outputs (`Direction.OUTPUT`) are projected onto RPR
  entity-state fields and encoded with the `pysos_rpr` codec for a protocol
  sink such as `pysos_interop.rpr`.
- **Subscribe.** RPR entity-state payloads are decoded with the `pysos_rpr`
  codec and projected onto FMU inputs (`Direction.INPUT`) before the model is
  stepped.

`Direction.PARAMETER` signals are model configuration and are projected in
neither direction. The IR, not this package, owns the payload schema;
`pyfmi_interop.schema` remains the emitter for a model's own payload.

## Identity

Entity identity — site, application, entity and marking — is **not** part of
the model. It comes from the federation manifest that launches the instance
(see the `pysos_coordinate` manifest schema), because one model may be started
as several entities in one federation. Every entry point that needs an identity
takes it as an explicit argument.

## Status

0.1.0 is the scaffold. `pyfmi_rpr.projection_plan` is the documented seam for
the projection and raises `NotImplementedError("A2")`; the runtime glue lands
in A3. Nothing here decodes or encodes a frame yet, and that is deliberate: a
half-built mapping is a contract callers would depend on.

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
