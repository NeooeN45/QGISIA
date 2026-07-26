"""Formules QgsRasterCalculator pour analyses de terrain 3D/relief (MNT)."""

from __future__ import annotations


def slope_expression(dem_ref: str, cellsize: float) -> str:
    """Expression de pente en degrés à partir d'un MNT."""
    dx = f"({dem_ref}[+1,0] - {dem_ref}[-1,0]) / (2 * {cellsize})"
    dy = f"({dem_ref}[0,+1] - {dem_ref}[0,-1]) / (2 * {cellsize})"
    return f"atan(sqrt(({dx})^2 + ({dy})^2)) * 180 / 3.14159265359"


def aspect_expression(dem_ref: str, cellsize: float) -> str:
    """Expression d'aspect (orientation) à partir d'un MNT."""
    dx = f"({dem_ref}[+1,0] - {dem_ref}[-1,0]) / (2 * {cellsize})"
    dy = f"({dem_ref}[0,+1] - {dem_ref}[0,-1]) / (2 * {cellsize})"
    return (
        f"180 / 3.14159265359 * atan2({dy}, -{dx}) + "
        f"if({dy} > 0, -90, 90) + 180"
    )


def hillshade_expression(
    dem_ref: str,
    azimuth: float = 315.0,
    altitude: float = 45.0,
    cellsize: float = 1.0,
) -> str:
    """Expression d'ombrage (hillshade) à partir d'un MNT."""
    dx = f"({dem_ref}[+1,0] - {dem_ref}[-1,0]) / (2 * {cellsize})"
    dy = f"({dem_ref}[0,+1] - {dem_ref}[0,-1]) / (2 * {cellsize})"
    zenith = 90.0 - altitude
    return (
        f"255 * ("
        f"cos({zenith} * 3.14159265359 / 180) * cos(atan(sqrt(({dx})^2 + ({dy})^2))) + "
        f"sin({zenith} * 3.14159265359 / 180) * sin(atan(sqrt(({dx})^2 + ({dy})^2))) * "
        f"cos({azimuth} * 3.14159265359 / 180 - atan2({dy}, -{dx}))"
        f")"
    )


def ruggedness_expression(dem_ref: str) -> str:
    """Expression de rugosité terrain (TRI, Terrain Ruggedness Index)."""
    neighbors = [
        f"{dem_ref}[-1,-1]", f"{dem_ref}[0,-1]", f"{dem_ref}[+1,-1]",
        f"{dem_ref}[-1,0]",                       f"{dem_ref}[+1,0]",
        f"{dem_ref}[-1,+1]", f"{dem_ref}[0,+1]", f"{dem_ref}[+1,+1]",
    ]
    diffs = [f"({n} - {dem_ref})^2" for n in neighbors]
    return f"sqrt(({' + '.join(diffs)}) / 8)"


def list_terrain() -> list[str]:
    """Liste les analyses de terrain disponibles."""
    return ["slope", "aspect", "hillshade", "ruggedness"]
