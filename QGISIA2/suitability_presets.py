"""Presets de critères pondérés pour analyses d'aptitude territoriale."""

from __future__ import annotations

_PRESETS: dict[str, dict] = {
    "panneaux_solaires": {
        "name": "Panneaux solaires",
        "criteria": [
            {"criterion": "pente", "weight": 0.30, "invert": True},
            {"criterion": "ensoleillement", "weight": 0.40, "invert": False},
            {"criterion": "proximite_reseau", "weight": 0.30, "invert": False},
        ],
    },
    "zone_constructible": {
        "name": "Zone constructible",
        "criteria": [
            {"criterion": "pente", "weight": 0.25, "invert": True},
            {"criterion": "distance_routes", "weight": 0.35, "invert": False},
            {"criterion": "hors_zone_inondable", "weight": 0.40, "invert": True},
        ],
    },
    "risque_erosion": {
        "name": "Risque d'érosion",
        "criteria": [
            {"criterion": "pente", "weight": 0.40, "invert": False},
            {"criterion": "couvert_vegetal", "weight": 0.35, "invert": True},
            {"criterion": "pluviometrie", "weight": 0.25, "invert": False},
        ],
    },
}


def list_presets() -> list[str]:
    """Retourne les identifiants des presets disponibles."""
    return list(_PRESETS.keys())


def get_preset(preset_id: str) -> dict | None:
    """Retourne le preset complet ou None si inconnu."""
    return _PRESETS.get(preset_id)


def total_weight(preset_id: str) -> float:
    """Somme des poids d'un preset ; 0.0 si inconnu."""
    preset = get_preset(preset_id)
    if preset is None:
        return 0.0
    return sum(c["weight"] for c in preset["criteria"])
