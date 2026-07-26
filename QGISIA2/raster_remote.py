# -*- coding: utf-8 -*-
"""
Résolution de chemins raster distants pour GDAL/QGIS.

Transforme une URL (COG https, S3...) en chemin virtuel GDAL chargeable par
QgsRasterLayer. Module pur Python (testable sans QGIS), utilisé par le slot
bridge `addRemoteRaster` (chargement satellite Sentinel/Landsat en COG — P3-S2).
"""
from __future__ import annotations


def to_gdal_remote_path(url: str) -> str:
    """
    URL distante -> chemin virtuel GDAL.
    - http(s)://...    -> /vsicurl/https://...
    - s3://bucket/key  -> /vsis3/bucket/key
    - chemin local     -> inchangé
    - déjà /vsi...      -> inchangé
    """
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("/vsi"):
        return u
    if u.startswith(("http://", "https://")):
        return f"/vsicurl/{u}"
    if u.startswith("s3://"):
        return f"/vsis3/{u[len('s3://'):]}"
    return u
