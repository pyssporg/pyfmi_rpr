"""Build the entity FMU and package it into an SSP whose composition is System.

The FMU is staged as ``resources/RprEntity.fmu`` so the entity's
``fmu_meta.source = "RprEntity.fmu"`` resolves against that resource directory
while the archive uses the SSP convention ``resources/<PartDef>.fmu``.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pycps_sysml2
from build_entity_fmu import REPO, build
from pyssp_sysml2 import generate_ssp

SYSTEM_SYSML = Path(__file__).resolve().parent / "rpr_system.sysml"
DEFAULT_OUT = Path("build") / "examples" / "system"
COMPOSITION = "System"


def assemble(out_dir: Path) -> tuple[Path, Path]:
    """Build the FMU, stage it under ``resources/``, and write the SSP."""
    fmu = build(out_dir)
    resources = out_dir / "resources"
    resources.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fmu, resources / fmu.name)

    output = out_dir / f"{COMPOSITION}.ssp"
    generate_ssp(
        SYSTEM_SYSML,
        output,
        COMPOSITION,
        includes=[REPO / "sysml", pycps_sysml2.core_definitions()],
        fmu_root=resources,
    )
    return fmu, output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output directory (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args(argv)

    fmu, ssp = assemble(args.out)
    print(f"FMU: {fmu}")
    print(f"SSP: {ssp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
