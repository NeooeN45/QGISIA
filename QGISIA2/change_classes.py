# -*- coding: utf-8 -*-
"""
Classes de severite de changement pour indices delta (dNDVI, dNBR, etc.).

Module pur Python (testable sans QGIS). Associe une valeur numerique a une
classe qualitative selon des bornes definies.
"""
from __future__ import annotations

from typing import List, Optional

SCHEMES = {
    "dndvi": {
        "name": "dNDVI — Changement de vegetation",
        "classes": [
            {"min": None, "max": -0.2, "label": "perte_forte", "color": "#8B0000"},
            {"min": -0.2, "max": -0.05, "label": "perte", "color": "#FF4500"},
            {"min": -0.05, "max": 0.05, "label": "stable", "color": "#D3D3D3"},
            {"min": 0.05, "max": 0.2, "label": "gain", "color": "#9ACD32"},
            {"min": 0.2, "max": None, "label": "gain_fort", "color": "#006400"},
        ],
    },
    "dnbr_feu": {
        "name": "dNBR — Severite du feu (USGS)",
        "classes": [
            {"min": None, "max": 0.1, "label": "non_brule", "color": "#2E8B57"},
            {"min": 0.1, "max": 0.27, "label": "faible", "color": "#9ACD32"},
            {"min": 0.27, "max": 0.44, "label": "modere", "color": "#FFD700"},
            {"min": 0.44, "max": 0.66, "label": "fort", "color": "#FF4500"},
            {"min": 0.66, "max": None, "label": "tres_fort", "color": "#8B0000"},
        ],
    },
}


def list_schemes() -> List[dict]:
    return [{"id": k, "name": v["name"], "classes": len(v["classes"])} for k, v in SCHEMES.items()]


def get_scheme(scheme_id: str) -> Optional[dict]:
    meta = SCHEMES.get(scheme_id)
    if meta is None:
        return None
    return {"id": scheme_id, "name": meta["name"], "classes": meta["classes"]}


def classify_value(scheme_id: str, value: float) -> Optional[str]:
    """
    Classe une valeur selon un scheme de severite.

    Args:
        scheme_id: identifiant du scheme.
        value: valeur a classifier.

    Returns:
        Le label de la classe ou None si hors bornes.

    Raises:
        ValueError: si le scheme est inconnu.
    """
    scheme = SCHEMES.get(scheme_id)
    if scheme is None:
        raise ValueError(f"Scheme inconnu: {scheme_id}")
    for cls in scheme["classes"]:
        low = cls["min"] if cls["min"] is not None else float("-inf")
        high = cls["max"] if cls["max"] is not None else float("inf")
        if low <= value < high:
            return cls["label"]
    return None
