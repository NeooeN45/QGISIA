# -*- coding: utf-8 -*-
"""
Utilitaires d'emprise (bbox) pour cadrer une recherche/analyse autour d'un point.

Module pur Python (testable sans QGIS). Sert a transformer un geocodage (lat/lon)
en emprise pour une recherche STAC (search_satellite_imagery) ou un export.
"""
from __future__ import annotations

import math
from typing import Tuple

_KM_PER_DEG_LAT = 111.0


def bbox_from_point(lat: float, lon: float, radius_km: float = 5.0) -> Tuple[float, float, float, float]:
    """Emprise (minlon, minlat, maxlon, maxlat) autour d'un point (degres WGS84)."""
    lat = float(lat)
    lon = float(lon)
    radius_km = float(radius_km)
    dlat = radius_km / _KM_PER_DEG_LAT
    dlon = radius_km / (_KM_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6))
    minlat = max(lat - dlat, -90.0)
    maxlat = min(lat + dlat, 90.0)
    return (lon - dlon, minlat, lon + dlon, maxlat)


def bbox_to_string(bbox: Tuple[float, float, float, float]) -> str:
    """'minlon,minlat,maxlon,maxlat' (format STAC)."""
    return ",".join(f"{x:g}" for x in bbox)


def bbox_center(bbox: Tuple[float, float, float, float]) -> Tuple[float, float]:
    """Centre (lat, lon) d'une emprise."""
    minlon, minlat, maxlon, maxlat = bbox
    return ((minlat + maxlat) / 2.0, (minlon + maxlon) / 2.0)
