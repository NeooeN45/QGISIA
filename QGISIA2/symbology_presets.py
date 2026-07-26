# -*- coding: utf-8 -*-
"""
Base de symbologies institutionnelles francaises (ONF, IGN, PLU, Cadastre,
Corine Land Cover, PPRi, Natura 2000...). Chaque preset genere un renderer
categorise QGIS (.qml) que l'agent peut appliquer a la demande.

Source de donnees : QGISIA2/config/symbology_presets.json. Module pur Python
(testable sans QGIS) ; la generation QML reutilise map_repro.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

PRESETS_PATH = Path(__file__).parent / "config" / "symbology_presets.json"


def load_presets() -> List[dict]:
    if not PRESETS_PATH.exists():
        return []
    try:
        return json.loads(PRESETS_PATH.read_text(encoding="utf-8")).get("presets", [])
    except (json.JSONDecodeError, OSError):
        return []


def get_preset(preset_id: str) -> Optional[dict]:
    return next((p for p in load_presets() if p.get("id") == preset_id), None)


def list_presets() -> List[dict]:
    """Resume des presets disponibles (pour l'agent / l'UI)."""
    return [
        {
            "id": p.get("id"),
            "institution": p.get("institution"),
            "name": p.get("name"),
            "field": p.get("field"),
            "geometry": p.get("geometry"),
            "categories": len(p.get("categories", [])),
        }
        for p in load_presets()
    ]


def preset_to_qml(preset_id: str, field: Optional[str] = None) -> Optional[str]:
    """Genere le QML categorise d'un preset (champ surchargable)."""
    preset = get_preset(preset_id)
    if preset is None:
        return None
    try:
        from map_repro import legend_to_qml  # type: ignore
    except ImportError:
        from .map_repro import legend_to_qml  # type: ignore

    geometry = preset.get("geometry", "polygon")
    legend = [
        {
            "value": cat.get("value", cat.get("label")),
            "label": cat.get("label", cat.get("value")),
            "color": cat.get("color", "#888888"),
            "geometry": geometry,
        }
        for cat in preset.get("categories", [])
    ]
    return legend_to_qml(legend, field=field or preset.get("field", "classe"),
                         geometry=geometry)
