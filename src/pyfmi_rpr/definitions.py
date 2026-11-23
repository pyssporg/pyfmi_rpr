"""Locate the RPR SysML definition shipped as package data.

The definition is an ordinary SysML file, not a parser. A consumer gets a real
filesystem path and hands it to its own loader as an include root; this package
never imports a dialect or a parser.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

__all__ = ["ENTITY_FILE", "rpr_entity"]

#: Name of the RPR entity definition inside the package.
ENTITY_FILE = "rpr_entity.sysml"


def rpr_entity() -> Path:
    """Return the bundled RPR entity definition as a real file path.

    An unpacked install (editable checkout or wheel) yields a real ``Path``; a
    zipped install cannot expose one and is refused rather than handing a
    non-path to the loader.

    Raises:
        RuntimeError: The package is not installed as an unpacked directory.
        FileNotFoundError: The bundled definition file is absent.
    """

    path = resources.files(__package__).joinpath("sysml", ENTITY_FILE)
    if not isinstance(path, Path):
        raise RuntimeError(
            "pyfmi-rpr must be installed as an unpacked directory "
            "so the bundled entity definition has a real file path"
        )
    if not path.is_file():
        raise FileNotFoundError(
            f"no entity definition found at {path}; reinstall pyfmi-rpr"
        )
    return path
