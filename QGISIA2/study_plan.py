"""Générateur de plan d'étude territoriale ordonné pour l'agent autonome."""

from __future__ import annotations

_LOADING_ACTIONS = {"add_basemap", "load_satellite"}

_THEMES: dict[str, list[dict]] = {
    "vegetation": [
        {"action": "add_basemap", "params": {}},
        {"action": "load_satellite", "params": {}},
        {"action": "compute_index", "params": {"index": "ndvi"}},
        {"action": "zonal_stats", "params": {}},
        {"action": "classify", "params": {}},
        {"action": "layout", "params": {}},
        {"action": "report", "params": {}},
    ],
    "urbanisme": [
        {"action": "add_basemap", "params": {}},
        {"action": "load_satellite", "params": {}},
        {"action": "detect_change", "params": {}},
        {"action": "zonal_stats", "params": {}},
        {"action": "classify", "params": {}},
        {"action": "layout", "params": {}},
        {"action": "report", "params": {}},
    ],
    "risques": [
        {"action": "add_basemap", "params": {}},
        {"action": "load_satellite", "params": {}},
        {"action": "compute_index", "params": {"index": "mndwi"}},
        {"action": "detect_change", "params": {}},
        {"action": "zonal_stats", "params": {}},
        {"action": "layout", "params": {}},
        {"action": "report", "params": {}},
    ],
}


def list_themes() -> list[str]:
    """Retourne les identifiants de thèmes disponibles."""
    return list(_THEMES.keys())


def build_plan(theme_id: str, context: dict) -> list[dict]:
    """Génère un plan d'étude pour un thème en injectant le contexte utilisateur."""
    if theme_id not in _THEMES:
        return []

    plan = [dict(step) for step in _THEMES[theme_id]]
    for step in plan:
        step["params"] = {**step["params"], **context}
    return plan
