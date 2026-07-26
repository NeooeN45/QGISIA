"""Parsing d'intentions cartographiques à partir de phrases en langage naturel."""

from __future__ import annotations

import re


VALID_ACTIONS = {
    "add_basemap",
    "compute_ndvi",
    "buffer",
    "load_satellite",
    "export_layout",
}


def _extract_distance(text: str) -> int | None:
    match = re.search(r"(\d+)\s*m", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def parse_intent(text: str) -> dict[str, str | int | None]:
    """Mappe une phrase utilisateur vers une action structurée avec paramètres."""
    lowered = text.lower().strip()
    params: dict[str, str | int | None] = {}

    if not lowered:
        return {"action": "unknown", "params": params}

    if "buffer" in lowered:
        distance = _extract_distance(text)
        if distance is not None:
            params["distance"] = distance
        return {"action": "buffer", "params": params}

    if any(k in lowered for k in ("ndvi", "indice de végétation")):
        return {"action": "compute_ndvi", "params": params}

    if any(k in lowered for k in ("basemap", "fond de carte", "fond")):
        return {"action": "add_basemap", "params": params}

    if any(k in lowered for k in ("satellite", "image satellite", "ortho")):
        return {"action": "load_satellite", "params": params}

    if any(k in lowered for k in ("export", "pdf", "layout", "mise en page")):
        return {"action": "export_layout", "params": params}

    return {"action": "unknown", "params": params}


def list_actions() -> list[str]:
    """Liste les actions cartographiques reconnues."""
    return sorted([*VALID_ACTIONS, "unknown"])
