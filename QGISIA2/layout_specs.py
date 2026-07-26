# -*- coding: utf-8 -*-
"""
Templates de mise en page declaratifs pour QGIS (A4/A3, portrait/paysage).

Module pur Python (testable sans QGIS). Definit la composition d'une page avec
positions/types d'elements (carte, legende, titre, echelle, etc.).
"""
from __future__ import annotations

from typing import List, Tuple

PAGE_SIZES = {"A4": (210, 297), "A3": (297, 420)}
VALID_ELEMENT_TYPES = {"map", "title", "legend", "scalebar", "north", "text", "image"}

TEMPLATES = {
    "a4_portrait_simple": {
        "name": "A4 Portrait — Simple",
        "page_size": "A4",
        "orientation": "portrait",
        "elements": [
            {"type": "map", "x": 10, "y": 40, "width": 190, "height": 240},
            {"type": "title", "x": 10, "y": 10, "width": 190, "height": 15},
            {"type": "scalebar", "x": 10, "y": 287, "width": 60, "height": 5},
            {"type": "north", "x": 180, "y": 280, "width": 15, "height": 15},
        ],
    },
    "a4_paysage_pro": {
        "name": "A4 Paysage — Professionnel",
        "page_size": "A4",
        "orientation": "landscape",
        "elements": [
            {"type": "map", "x": 10, "y": 20, "width": 180, "height": 170},
            {"type": "title", "x": 200, "y": 10, "width": 87, "height": 15},
            {"type": "legend", "x": 200, "y": 30, "width": 87, "height": 80},
            {"type": "scalebar", "x": 200, "y": 115, "width": 60, "height": 5},
            {"type": "north", "x": 270, "y": 115, "width": 15, "height": 15},
            {"type": "text", "x": 200, "y": 135, "width": 87, "height": 55, "content": "Notes"},
        ],
    },
    "a3_paysage_atlas": {
        "name": "A3 Paysage — Atlas",
        "page_size": "A3",
        "orientation": "landscape",
        "elements": [
            {"type": "map", "x": 10, "y": 15, "width": 300, "height": 260},
            {"type": "title", "x": 320, "y": 15, "width": 90, "height": 20},
            {"type": "legend", "x": 320, "y": 40, "width": 90, "height": 120},
            {"type": "scalebar", "x": 320, "y": 165, "width": 80, "height": 8},
            {"type": "north", "x": 380, "y": 180, "width": 25, "height": 25},
            {"type": "image", "x": 320, "y": 215, "width": 90, "height": 55, "source": "logo.png"},
        ],
    },
}


def list_templates() -> List[dict]:
    return [
        {"id": k, "name": v["name"], "page_size": v["page_size"], "orientation": v["orientation"]}
        for k, v in TEMPLATES.items()
    ]


def get_template(template_id: str) -> dict | None:
    tmpl = TEMPLATES.get(template_id)
    if tmpl is None:
        return None
    return {"id": template_id, **tmpl}


def page_dimensions_mm(size: str, orientation: str) -> Tuple[int, int]:
    """Renvoie (largeur, hauteur) en mm. Swap si landscape."""
    w, h = PAGE_SIZES.get(size, (210, 297))
    if orientation == "landscape":
        return h, w
    return w, h


def validate_template(t: dict) -> List[str]:
    """Valide un template : types d'elements valides et coords dans la page."""
    errors: List[str] = []
    size = t.get("page_size", "A4")
    orientation = t.get("orientation", "portrait")
    page_w, page_h = page_dimensions_mm(size, orientation)
    for idx, elem in enumerate(t.get("elements", [])):
        etype = elem.get("type")
        if etype not in VALID_ELEMENT_TYPES:
            errors.append(f"element {idx}: type invalide '{etype}'")
            continue
        x, y = elem.get("x", 0), elem.get("y", 0)
        w, h = elem.get("width", 0), elem.get("height", 0)
        if x < 0 or y < 0 or (x + w) > page_w or (y + h) > page_h:
            errors.append(
                f"element {idx} ({etype}): hors page ({x},{y},{w},{h}) "
                f"vs page ({page_w},{page_h})"
            )
    return errors
