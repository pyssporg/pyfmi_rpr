"""Build the RPR entity definition into a standalone CS FMU."""

from __future__ import annotations

import argparse
from pathlib import Path

from pyfmi_rpr import rpr_entity

DEFAULT_OUT = Path("build") / "examples" / "entity"


def build(out_dir: Path) -> Path:
    """Generate, build and package the entity FMU into ``out_dir``."""
    from pysos_rpr.projection import generate_entity_adapter

    return generate_entity_adapter(rpr_entity(), out_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output directory (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args(argv)

    print(f"FMU: {build(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
