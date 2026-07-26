# -*- coding: utf-8 -*-
"""
Outils de critique et scoring pour la boucle d'auto-correction visuelle de l'agent.

Module pur Python (testable sans QGIS). Evalue la qualite d'une mise en page
selon des criteres heuristiques et genere des prompts pour un VLM critique.
"""
from __future__ import annotations

from typing import List


def build_critique_prompt(intent: str, layout_meta: dict) -> str:
    """
    Genere un prompt demandant a un VLM de juger le rendu cartographique.

    Args:
        intent: intention de la carte (ex: 'analyse vegetation').
        layout_meta: metadonnees de la mise en page (titre, legende, etc.).
    """
    elements = ", ".join(k for k in layout_meta if k != "map") or "aucun"
    return (
        f"Tu es un expert en cartographie. Voici une carte destinee a : {intent}.\n"
        f"Elements presents : {elements}.\n"
        "Evalue selon ces criteres :\n"
        "1. Cadrage : la zone d'interet est-elle bien centree et visible ?\n"
        "2. Lisibilite : les etiquettes, couleurs et contrastes sont-ils adequats ?\n"
        "3. Legende : est-elle complete et coherente avec les donnees affichees ?\n"
        "4. Equilibre visuel : la page est-elle bien composee (titre, echelle, nord) ?\n"
        "Liste les defauts trouves et suggere des corrections concretes."
    )


def completeness_score(layout_meta: dict) -> dict:
    """
    Heuristique de completion d'une mise en page. Renvoie {score, missing}.

    Criteres (poids egal, 0.2 chacun) :
    - titre present
    - carte presente avec extent non vide
    - legende presente
    - echelle presente
    - fleche nord presente
    """
    checks = {
        "title": bool(layout_meta.get("title")),
        "map": bool(layout_meta.get("map") and layout_meta["map"].get("extent")),
        "legend": bool(layout_meta.get("legend")),
        "scalebar": bool(layout_meta.get("scalebar")),
        "north": bool(layout_meta.get("north")),
    }
    missing = [k for k, v in checks.items() if not v]
    score = round((len(checks) - len(missing)) / len(checks), 2)
    return {"score": score, "missing": missing}


def suggest_fixes(layout_meta: dict) -> List[str]:
    """Conseils textuels selon les elements manquants de la mise en page."""
    out = completeness_score(layout_meta)
    fixes = []
    mapping = {
        "title": "Ajouter un titre explicite a la carte.",
        "map": "Ajouter ou verifier la couche cartographique principale (extent non vide).",
        "legend": "Ajouter une legende pour interpreter les symboles et couleurs.",
        "scalebar": "Ajouter une barre d'echelle pour situer les distances.",
        "north": "Ajouter une fleche de nord pour l'orientation.",
    }
    for m in out["missing"]:
        fixes.append(mapping.get(m, f"Element manquant : {m}"))
    return fixes
