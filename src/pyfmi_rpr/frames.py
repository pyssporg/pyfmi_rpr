"""Local WGS84, ECEF, ENU and body-frame conversions.

This is a small, dependency-free implementation of the frame arithmetic the
adapter needs at the wire boundary.  It deliberately does not import
``pysos_interop``: that package is a development parity oracle in the test
suite, never a runtime dependency.

Conventions, matching ``pysos_interop.EntityState`` and ``rpr/v2/spatial.proto``:

* Position is geocentric ECEF metres.
* Orientation is WGS84 geodetic ``(latitude, longitude, altitude)`` at the
  manifest origin.
* The local frame is east-north-up (ENU).
* Body axes are x forward, y right, z down.
* Euler attitude is Z-Y-X ``(roll, pitch, yaw)`` in radians, where yaw is about
  the local vertical, then pitch, then roll.
* Body angular velocity is radians per second about the body axes.

Every conversion takes an explicit :class:`~pyfmi_rpr.manifest.Origin`; there
is no global origin.
"""

from __future__ import annotations

import math

from .manifest import Origin

__all__ = [
    "WGS84_A",
    "WGS84_E2",
    "WGS84_F",
    "body_to_enu_rotation",
    "body_vector_to_enu",
    "ecef_to_enu",
    "ecef_vector_to_enu",
    "enu_to_ecef",
    "enu_vector_to_body",
    "enu_vector_to_ecef",
    "geodetic_to_ecef",
]

Vec3 = tuple[float, float, float]
Vec3Matrix = tuple[Vec3, Vec3, Vec3]

WGS84_A = 6_378_137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)


def geodetic_to_ecef(latitude_deg: float, longitude_deg: float, altitude_m: float) -> Vec3:
    """Convert WGS84 geodetic coordinates to ECEF metres."""

    lat = math.radians(float(latitude_deg))
    lon = math.radians(float(longitude_deg))
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)
    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (n + altitude_m) * cos_lat * cos_lon
    y = (n + altitude_m) * cos_lat * sin_lon
    z = (n * (1.0 - WGS84_E2) + altitude_m) * sin_lat
    return (x, y, z)


def enu_basis(origin: Origin) -> tuple[Vec3, Vec3, Vec3]:
    """Return the east, north and up unit vectors of ``origin`` in ECEF axes."""

    lat = math.radians(origin.latitude_deg)
    lon = math.radians(origin.longitude_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    east = (-sin_lon, cos_lon, 0.0)
    north = (-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat)
    up = (cos_lat * cos_lon, cos_lat * sin_lon, sin_lat)
    return (east, north, up)


def enu_to_ecef(enu_m: Vec3, origin: Origin) -> Vec3:
    """Convert local ENU metres to ECEF metres."""

    east, north, up = enu_basis(origin)
    ref = geodetic_to_ecef(origin.latitude_deg, origin.longitude_deg, origin.altitude_m)
    e, n, u = (float(value) for value in enu_m)
    return tuple(  # type: ignore[return-value]
        ref[i] + east[i] * e + north[i] * n + up[i] * u for i in range(3)
    )


def ecef_to_enu(ecef_m: Vec3, origin: Origin) -> Vec3:
    """Convert ECEF metres to local ENU metres."""

    east, north, up = enu_basis(origin)
    ref = geodetic_to_ecef(origin.latitude_deg, origin.longitude_deg, origin.altitude_m)
    delta = (
        float(ecef_m[0]) - ref[0],
        float(ecef_m[1]) - ref[1],
        float(ecef_m[2]) - ref[2],
    )
    return (_dot(east, delta), _dot(north, delta), _dot(up, delta))


def enu_vector_to_ecef(vector_enu: Vec3, origin: Origin) -> Vec3:
    """Rotate an ENU vector into ECEF axes (no translation)."""

    east, north, up = enu_basis(origin)
    e, n, u = (float(value) for value in vector_enu)
    return tuple(  # type: ignore[return-value]
        east[i] * e + north[i] * n + up[i] * u for i in range(3)
    )


def ecef_vector_to_enu(vector_ecef: Vec3, origin: Origin) -> Vec3:
    """Rotate an ECEF vector into ENU axes (no translation)."""

    east, north, up = enu_basis(origin)
    v = tuple(float(value) for value in vector_ecef)
    return (_dot(east, v), _dot(north, v), _dot(up, v))


def body_to_enu_rotation(roll: float, pitch: float, yaw: float) -> Vec3Matrix:
    """Return the body-to-ENU rotation as rows east, north and up.

    This is the Z-Y-X convention documented on ``pysos_interop.EntityState``;
    the test suite pins numerical agreement with that package when installed.
    """

    cr, sr = math.cos(float(roll)), math.sin(float(roll))
    cp, sp = math.cos(float(pitch)), math.sin(float(pitch))
    cy, sy = math.cos(float(yaw)), math.sin(float(yaw))

    north = (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr)
    east = (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr)
    down = (-sp, cp * sr, cp * cr)
    return (east, north, tuple(-value for value in down))


def enu_vector_to_body(vector_enu: Vec3, orientation_rps: Vec3) -> Vec3:
    """Rotate an ENU vector into body axes for ``orientation_rps``."""

    roll, pitch, yaw = orientation_rps
    matrix = body_to_enu_rotation(roll, pitch, yaw)
    return _apply_transpose(matrix, vector_enu)


def body_vector_to_enu(vector_body: Vec3, orientation_rps: Vec3) -> Vec3:
    """Rotate a body vector into ENU axes for ``orientation_rps``."""

    roll, pitch, yaw = orientation_rps
    return _apply(body_to_enu_rotation(roll, pitch, yaw), vector_body)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _apply(matrix: Vec3Matrix, vector: Vec3) -> Vec3:
    return tuple(  # type: ignore[return-value]
        row[0] * vector[0] + row[1] * vector[1] + row[2] * vector[2]
        for row in matrix
    )


def _apply_transpose(matrix: Vec3Matrix, vector: Vec3) -> Vec3:
    return tuple(  # type: ignore[return-value]
        matrix[0][i] * vector[0] + matrix[1][i] * vector[1] + matrix[2][i] * vector[2]
        for i in range(3)
    )

