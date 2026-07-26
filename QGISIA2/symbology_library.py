"""Bibliotheque de symbologies institutionnelles FR.

Repose sur symbology_presets (JSON) pour fournir des fonctions de recherche et
regroupement. Module pur Python (testable sans QGIS).
"""
from __future__ import annotations

import unicodedata

from symbology_presets import get_preset, list_presets, load_presets


def _normalize(text: str) -> str:
    """NFKD + lower pour recherche insensible aux accents/casse."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.lower())
        if unicodedata.category(c) != "Mn"
    )


def list_by_institution() -> dict[str, list[str]]:
    """Groupe les preset IDs par institution."""
    groups: dict[str, list[str]] = {}
    for preset in load_presets():
        inst = preset.get("institution", "Autre")
        groups.setdefault(inst, []).append(preset["id"])
    return {k: sorted(v) for k, v in sorted(groups.items())}


def list_categories() -> list[str]:
    """Retourne les categories uniques presentes dans le catalogue."""
    cats = {preset.get("institution", "Autre") for preset in load_presets()}
    return sorted(cats)


def search_presets(query: str) -> list[dict]:
    """
    Recherche textuelle sur name/institution/field (insensible casse/accents).
    """
    q = _normalize(query)
    results = []
    for preset in load_presets():
        haystack = _normalize(
            f"{preset.get('name', '')} {preset.get('institution', '')} {preset.get('field', '')}"
        )
        if q in haystack:
            results.append(preset)
    return results


def get_preset_summary(preset_id: str) -> dict | None:
    """Resume synthetique d'un preset ; None si inconnu."""
    preset = get_preset(preset_id)
    if preset is None:
        return None
    return {
        "id": preset["id"],
        "name": preset.get("name", ""),
        "institution": preset.get("institution", ""),
        "field": preset.get("field", ""),
        "n_categories": len(preset.get("categories", [])),
    }
