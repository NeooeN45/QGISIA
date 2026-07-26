# -*- coding: utf-8 -*-
"""
Registre de collections STAC multi-capteurs et mapping logique bande -> asset_key.

Module pur Python (testable sans QGIS). Normalise les noms de bandes (BLUE, GREEN,
RED, NIR, SWIR, SWIR2, VV, VH) vers les cles d'assets utilisees par les catalogues STAC.
"""
from __future__ import annotations

from typing import List, Optional

COLLECTIONS = {
    "sentinel-2-l2a": {
        "name": "Sentinel-2 L2A (optique, 10-20 m)",
        "sensor": "optique",
        "description": "Sentinel-2 niveau 2A (reflectances de surface)",
        "bands": {
            "BLUE": "blue",
            "GREEN": "green",
            "RED": "red",
            "NIR": "nir",
            "SWIR": "swir16",
            "SWIR2": "swir22",
        },
    },
    "sentinel-1-grd": {
        "name": "Sentinel-1 GRD (radar)",
        "sensor": "radar",
        "description": "Sentinel-1 Ground Range Detected (VV/VH)",
        "bands": {
            "VV": "vv",
            "VH": "vh",
        },
    },
    "landsat-c2-l2": {
        "name": "Landsat Collection 2 Level-2",
        "sensor": "optique",
        "description": "Landsat 8/9 Collection 2 Level-2 (surface reflectance)",
        "bands": {
            "BLUE": "blue",
            "GREEN": "green",
            "RED": "red",
            "NIR": "nir08",
            "SWIR": "swir16",
        },
    },
}


def list_collections() -> List[dict]:
    return [
        {"id": k, "name": v["name"], "sensor": v["sensor"]}
        for k, v in COLLECTIONS.items()
    ]


def get_collection(collection_id: str) -> Optional[dict]:
    meta = COLLECTIONS.get(collection_id)
    if meta is None:
        return None
    return {"id": collection_id, **meta}


def asset_key_for(collection_id: str, band: str) -> Optional[str]:
    """
    Renvoie la cle d'asset STAC pour une bande logique donnee.

    Args:
        collection_id: identifiant de la collection.
        band: nom logique de la bande (ex: 'RED', 'VV').

    Returns:
        La cle d'asset (ex: 'red', 'vv') ou None si non trouvee.
    """
    meta = COLLECTIONS.get(collection_id)
    if meta is None:
        return None
    return meta["bands"].get(band)
