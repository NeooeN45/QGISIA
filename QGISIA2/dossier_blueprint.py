# -*- coding: utf-8 -*-
"""
Blueprints de dossiers territoriaux pre-assembles pour l'agent.

Module pur Python (testable sans QGIS). Lit QGISIA2/config/dossiers.json et valide
chaque step contre le catalogue de sources (data_catalog) et les presets de symbologie
(symbology_presets).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

DOSSIERS_PATH = Path(__file__).parent / "config" / "dossiers.json"
VALID_ACTIONS = {"addDataSource", "applySymbologyPreset"}


def load_dossiers() -> List[dict]:
    if not DOSSIERS_PATH.exists():
        return []
    try:
        return json.loads(DOSSIERS_PATH.read_text(encoding="utf-8")).get("dossiers", [])
    except (json.JSONDecodeError, OSError):
        return []


def get_dossier(dossier_id: str) -> Optional[dict]:
    return next((d for d in load_dossiers() if d.get("id") == dossier_id), None)


def list_dossiers() -> List[dict]:
    """Resume des dossiers disponibles (pour l'agent / l'UI)."""
    return [
        {
            "id": d.get("id"),
            "name": d.get("name"),
            "description": d.get("description"),
            "steps": len(d.get("steps", [])),
        }
        for d in load_dossiers()
    ]


def expand_dossier(dossier_id: str) -> List[dict]:
    """Renvoie la liste ordonnee des steps d'un dossier."""
    dossier = get_dossier(dossier_id)
    if dossier is None:
        return []
    return list(dossier.get("steps", []))


def validate_dossier(dossier: dict) -> List[str]:
    """Valide un dossier contre les catalogues sources et presets. Renvoie les erreurs."""
    errors: List[str] = []
    try:
        from data_catalog import get_source  # type: ignore
    except ImportError:
        from .data_catalog import get_source  # type: ignore
    try:
        from symbology_presets import get_preset  # type: ignore
    except ImportError:
        from .symbology_presets import get_preset  # type: ignore

    for idx, step in enumerate(dossier.get("steps", [])):
        action = step.get("action")
        if action not in VALID_ACTIONS:
            errors.append(
                f"[{dossier.get('id')}] step {idx}: action invalide '{action}'"
            )
            continue
        if action == "addDataSource":
            sid = step.get("sourceId")
            if not sid or get_source(sid) is None:
                errors.append(
                    f"[{dossier.get('id')}] step {idx}: sourceId inconnu '{sid}'"
                )
        elif action == "applySymbologyPreset":
            pid = step.get("presetId")
            if not pid or get_preset(pid) is None:
                errors.append(
                    f"[{dossier.get('id')}] step {idx}: presetId inconnu '{pid}'"
                )
    return errors
