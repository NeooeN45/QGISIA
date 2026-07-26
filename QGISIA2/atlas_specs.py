# -*- coding: utf-8 -*-
"""
Specifications d'atlas multi-pages pour QGIS (1 page par entite).

Module pur Python (testable sans QGIS). Chaque atlas reference un template de
mise en page (layout_specs) et definit une expression de nommage de page.
"""
from __future__ import annotations

from typing import List

TEMPLATES = {
    "communes_atlas": {
        "name": "Atlas par communes",
        "base_layout": "a4_portrait_simple",
        "coverage_hint": "communes",
        "page_name_expression": "{nom_commune} ({code_insee})",
    },
    "parcelles_atlas": {
        "name": "Atlas par parcelles cadastrales",
        "base_layout": "a4_paysage_pro",
        "coverage_hint": "parcelles",
        "page_name_expression": "Section {section} — Parcelle {numero}",
    },
}


def list_atlas() -> List[dict]:
    return [
        {"id": k, "name": v["name"], "base_layout": v["base_layout"]}
        for k, v in TEMPLATES.items()
    ]


def get_atlas(atlas_id: str) -> dict | None:
    tmpl = TEMPLATES.get(atlas_id)
    if tmpl is None:
        return None
    return {"id": atlas_id, **tmpl}


def validate_atlas(a: dict) -> List[str]:
    """Valide un atlas : base_layout et page_name_expression non vides."""
    errors: List[str] = []
    if not a.get("base_layout"):
        errors.append("base_layout vide")
    if not a.get("page_name_expression"):
        errors.append("page_name_expression vide")
    return errors
