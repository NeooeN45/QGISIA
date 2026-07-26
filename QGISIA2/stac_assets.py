# -*- coding: utf-8 -*-
"""
Resolution des href d'assets COG d'un item STAC (Earth Search sentinel-2-l2a).

Module pur Python (testable sans QGIS). Permet a l'agent, apres une recherche
satellite (search_satellite_imagery), de recuperer l'URL COG d'une bande pour la
charger via addRemoteRaster puis calculer un indice (computeSpectralIndex).
"""
from __future__ import annotations

from typing import List, Optional

# Bande logique -> cle d'asset Earth Search (sentinel-2-l2a)
SENTINEL2_ASSETS = {
    "BLUE": "blue",
    "GREEN": "green",
    "RED": "red",
    "NIR": "nir",
    "SWIR": "swir16",
    "SWIR2": "swir22",
}


def resolve_asset_href(item: dict, band: str) -> Optional[str]:
    """Href COG d'une bande logique (RED, NIR...) dans un item STAC. None si absent."""
    assets = (item or {}).get("assets", {}) or {}
    band = str(band or "").strip()
    if not band:
        return None
    candidates: List[str] = []
    mapped = SENTINEL2_ASSETS.get(band.upper())
    if mapped:
        candidates.append(mapped)
    candidates += [band, band.upper(), band.lower()]
    for key in candidates:
        asset = assets.get(key)
        if isinstance(asset, dict) and asset.get("href"):
            return asset["href"]
    return None


def normalize_datetime(dt: Optional[str]) -> Optional[str]:
    """Normalise un datetime STAC en RFC3339 (Earth Search rejette les dates seules).

    '2024-01-01/2024-12-31' -> '2024-01-01T00:00:00Z/2024-12-31T23:59:59Z'
    '2024-06-15' -> '2024-06-15T00:00:00Z' ; '..' et les bornes ouvertes preserves.
    """
    if not dt:
        return None
    dt = str(dt).strip()

    def _fix(part: str, end: bool = False) -> str:
        part = part.strip()
        if not part or part == "..":
            return part
        if "T" in part:
            return part
        return part + ("T23:59:59Z" if end else "T00:00:00Z")

    if "/" in dt:
        start, _, stop = dt.partition("/")
        return f"{_fix(start)}/{_fix(stop, end=True)}"
    return _fix(dt)


def band_assets(item: dict, bands: List[str]) -> dict:
    """{band: href} pour les bandes resolues (ignore celles sans asset)."""
    out = {}
    for band in bands:
        href = resolve_asset_href(item, band)
        if href:
            out[band] = href
    return out
