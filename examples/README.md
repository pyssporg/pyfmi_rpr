# pyfmi_rpr examples

Build the RPR entity definition shipped with `pyfmi_rpr`
(`pyfmi_rpr.rpr_entity()`) into a standalone FMI 2.0 CoSimulation FMU, then
insert that FMU as one component in a generated `.ssp`.

## Run

From the workspace root, in the workspace venv:

```bash
python repos/pyfmi_rpr/examples/assemble_system.py
```

That is the whole example: it builds the FMU, stages it as
`resources/RprEntity.fmu`, and packages `System.ssp`. Everything lands under the
gitignored `build/examples/system/`:

| Path | What |
| --- | --- |
| `RprEntity.fmu` | the standalone FMU |
| `resources/RprEntity.fmu` | the FMU as the SSP resource |
| `System.ssp` | the entity composed into `System` |

Expected output:

```text
FMU: build/examples/system/RprEntity.fmu
SSP: build/examples/system/System.ssp
```

FMU only:

```bash
python repos/pyfmi_rpr/examples/build_entity_fmu.py
```

Expected output:

```text
FMU: build/examples/entity/RprEntity.fmu
```

Both scripts accept `--out DIR`.

## Setup

Needs `cmake`, `ninja`, `g++` and `protoc` on `PATH`, and the workspace venv:

```bash
python -m venv .venv-experimental
source .venv-experimental/bin/activate
pip install --no-deps -r requirements-experimental.txt
pip install -r requirements-thirdparty.txt
pip install --no-deps -e repos/pyssp_sysml
```

`pyssp_sysml` is the one consumer package `requirements-experimental.txt` does
not list, so the FMU build and the SSP assembly share one environment.

The built FMU declares its `parameters` port, so a master configures the
endpoint through SSV/SSM parameters.

## What the definition encodes

`pyfmi_rpr.rpr_entity()` resolves the definition owned by this repo at
`src/pyfmi_rpr/sysml/rpr_entity.sysml`; it follows the three roles in
`pyssp_sysml_definitions/docs/roles.md`:

- **Build metadata.** `RprEntityMetadata :> FmuMetadata` carries
  `source = "RprEntity.fmu"` and `implementation = "CoSimulation"`. The SSP
  packager reads it; it never becomes an FMI variable or a connector. The FMU
  builder derives the model name from the package.
- **Runtime signals.** `in port entityState : EntityState` is the state this
  entity publishes, supplied by the model and encoded onto the wire; `out port
  peerState : EntityState` is the peer state received from the wire and exposed
  to the simulation. Both usages carry the same 30 flat attributes, so the FMI
  interface has 30 inputs `entityState.<flat-name>` and 30 outputs
  `peerState.<flat-name>`.
- **Deployment configuration.** `in port parameters : RprDeployment` carries
  the UDP endpoint as initialization configuration: `transport`
  (`loopback`/`udp`/`tcp`), `bind_address` and `peer_address`, defaulting to
  loopback. A master sets them per instance before initialization with an
  SSV/SSM parameter set; they never become wire fields. Identity, entity type,
  marking and force remain payload fields, not configuration.

### Wire contract

`pysos_rpr.projection.generate_entity_adapter` reduces the definition to one
payload message, `rpr.v2.PhysicalEntity`. The 30 flat attributes of
`EntityState` are exactly the leaves pinned by `pysos_rpr.schema_paths` and
appear as `entityState.<flat-name>` and `peerState.<flat-name>` on the FMI
interface. A leaf carried in both directions is encoded from its input member
(published) and decoded into its output member (subscribed), so one payload
field never has two sources.
`bytes` fields are not representable in the dialect, so
`spatial.dead_reckoning.parameters` is omitted and the codec defaults it to
empty.

### Frame and unit contract

The dialect states names but not physical meaning, so the definition documents
it in comments:

| Group | Contract |
| --- | --- |
| `spatial.world_location.*` | geocentric ECEF, metres |
| `spatial.orientation.psi/theta/phi` | Euler yaw/pitch/roll, radians |
| `spatial.velocity.*` | body frame, m/s |
| `spatial.acceleration.*` | body frame, m/s² |
| `spatial.angular_velocity.*` | body frame, rad/s |
| `spatial.dead_reckoning.algorithm` | enum 0..9; `parameters` omitted |

`frame_mode` belongs to the projection, not this definition:
`generate_entity_adapter` defaults to `identity`, an interop stand-in that does
not convert frames and is not RPR conformance.

### System composition

`assemble_system.py` loads `rpr_system.sysml` with two include roots,
`pyfmi_rpr.rpr_entity()` and `pycps_sysml.core_definitions()`, then packages:

```sysml
part def System :> SspModel {
    part entity : RprEntity;
}
```

`System` is the exportable SSP boundary and is not an `FmuModel`; `RprEntity`
is the FMU component it composes.

The entity's `source = "RprEntity.fmu"` resolves under `resources/`, which is
where the script stages the built FMU.
