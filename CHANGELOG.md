# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-19

Scaffold release. The package declares its scope and its two sibling
dependencies, and exposes the seam the projection will fill. No projection or
wire behaviour is implemented.

### Added

- Package `pyfmi_rpr` with `__version__ = "0.1.0"` and a documented scope: the
  FMU-side IR to RPR projection, with entity identity taken from the federation
  manifest rather than from the model.
- `projection_plan`, `ProjectionPlan` and `ProjectionEntry`: a typed,
  documented seam for the A2 projection. The call raises
  `NotImplementedError("A2")` instead of returning a partial plan.
- Exact release-wheel pins for `pyfmi-interop` 0.3.0 and `pysos-rpr` 0.1.0,
  plus the `protobuf>=5.29,<6` runtime.
- Package contract tests for the version, the pinned sibling distribution
  versions, the IR and wire imports, the vocabulary import, and the seam.
- `tests` and `wheels` workflows adapted from `pysos_interop`.

### Compatibility

- Python >= 3.11, required by the `pysos-rpr` generated bindings.
- `import pyfmi_rpr` imports the IR through `pyfmi_interop`; it imports no
  `pysos_rpr` module and decodes or encodes nothing.
