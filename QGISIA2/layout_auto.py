# -*- coding: utf-8 -*-
"""
Auto-selection de mise en page pour la boucle d'auto-amelioration de l'agent.

Module pur Python (testable sans QGIS). Derive un layout_meta d'un gabarit
(layout_specs) et choisit le gabarit le plus complet (vision_critique).
"""
from __future__ import annotations

from typing import Optional


def layout_meta_from_template(template: dict) -> dict:
    """Construit un layout_meta (pour vision_critique) a partir d'un gabarit layout_specs.

    L'extent reel n'est connu qu'au rendu : on place un extent fictif non vide pour que
    le score de completude reflete la presence d'une carte.
    """
    types = {e.get("type") for e in (template.get("elements") or [])}
    return {
        "title": ("title" in types or "text" in types),
        "map": {"extent": [0, 0, 1, 1]} if "map" in types else None,
        "legend": "legend" in types,
        "scalebar": "scalebar" in types,
        "north": "north" in types,
    }


# Elements requis pour une mise en page complete + positions par defaut (mm, A4-ish)
_REQUIRED = ["title", "map", "legend", "scalebar", "north"]
_DEFAULTS = {
    "title": {"type": "title", "x": 10, "y": 8, "width": 180, "height": 12},
    "map": {"type": "map", "x": 10, "y": 24, "width": 180, "height": 160},
    "legend": {"type": "legend", "x": 150, "y": 188, "width": 50, "height": 55},
    "scalebar": {"type": "scalebar", "x": 10, "y": 196, "width": 80, "height": 12},
    "north": {"type": "north", "x": 175, "y": 26, "width": 16, "height": 16},
}


def score_elements(elements: list) -> dict:
    """Score de completude d'une liste d'elements (via vision_critique)."""
    from vision_critique import completeness_score
    return completeness_score(layout_meta_from_template({"elements": elements}))


def augment_to_complete(elements: list) -> list:
    """Retourne une nouvelle liste d'elements complétée des elements requis manquants."""
    types = {e.get("type") for e in elements}
    out = [dict(e) for e in elements]
    for etype in _REQUIRED:
        present = etype in types or (etype == "title" and "text" in types)
        if not present:
            out.append(dict(_DEFAULTS[etype]))
            types.add(etype)
    return out


def pick_best_template(prefer: Optional[str] = None) -> dict:
    """Choisit le gabarit le plus complet. Renvoie {template, score}.

    `prefer` (optionnel) est privilegie a score egal.
    """
    from layout_specs import list_templates, get_template
    from vision_critique import completeness_score

    best_id = None
    best_score = -1.0
    for entry in list_templates():
        tid = entry["id"]
        meta = layout_meta_from_template(get_template(tid))
        score = completeness_score(meta)["score"]
        if score > best_score or (score == best_score and tid == prefer):
            best_score = score
            best_id = tid
    return {"template": best_id, "score": best_score}
