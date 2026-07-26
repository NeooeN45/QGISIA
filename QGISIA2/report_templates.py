# -*- coding: utf-8 -*-
"""
Gabarits de rapports markdown narratifs pour l'agent QGISIA.

Module pur Python (testable sans QGIS). Chaque template contient des sections
avec placeholders {cle} remplaces par un contexte fourni.
"""
from __future__ import annotations

import re
from typing import List, Set

TEMPLATES = {
    "diagnostic_vegetation": {
        "name": "Diagnostic vegetation",
        "sections": [
            {
                "title": "Diagnostic vegetation — {commune}",
                "body": (
                    "**Date :** {date}\n\n"
                    "## Synthese\n\n"
                    "L'indice NDVI moyen sur la zone est de **{ndvi_moyen}**.\n\n"
                    "## Recommandations\n\n"
                    "- Zones de faible vegetation a surveiller.\n"
                    "- Corridors ecologiques a renforcer.\n"
                ),
            },
        ],
    },
    "diagnostic_risques": {
        "name": "Diagnostic risques (inondation / feu)",
        "sections": [
            {
                "title": "Diagnostic risques — {commune}",
                "body": (
                    "**Date :** {date}\n\n"
                    "## Risque inondation\n\n"
                    "Zones inondables identifiees sur la commune.\n\n"
                    "## Risque incendie\n\n"
                    "Indice NBR moyen : **{nbr_moyen}**.\n\n"
                    "- Zones rouges : restriction estivale.\n"
                ),
            },
        ],
    },
    "diagnostic_urbanisme": {
        "name": "Diagnostic urbanisme",
        "sections": [
            {
                "title": "Diagnostic urbanisme — {commune}",
                "body": (
                    "**Date :** {date}\n\n"
                    "## Occupation du sol\n\n"
                    "Repartition des zones :\n\n"
                    "- Urbain : {pct_urbain}%\n"
                    "- Agricole : {pct_agricole}%\n"
                    "- Naturel : {pct_naturel}%\n\n"
                    "## Conformite PLU\n\n"
                    "Analyse des conformites a valider.\n"
                ),
            },
        ],
    },
}


def list_templates() -> List[dict]:
    return [{"id": k, "name": v["name"], "sections": len(v["sections"])} for k, v in TEMPLATES.items()]


def get_template(template_id: str) -> dict | None:
    tmpl = TEMPLATES.get(template_id)
    if tmpl is None:
        return None
    return {"id": template_id, **tmpl}


def required_keys(template_id: str) -> Set[str]:
    """Extrait toutes les cles de placeholders d'un template."""
    tmpl = TEMPLATES.get(template_id)
    if tmpl is None:
        return set()
    keys: Set[str] = set()
    pattern = re.compile(r"\{(\w+)\}")
    for section in tmpl.get("sections", []):
        for text in (section.get("title", ""), section.get("body", "")):
            keys.update(pattern.findall(text))
    return keys


def render_report(template_id: str, context: dict) -> str:
    """
    Rend un template en markdown avec un contexte. Les cles manquantes
    sont remplacees par '[?]'.
    """
    tmpl = TEMPLATES.get(template_id)
    if tmpl is None:
        raise ValueError(f"Template inconnu: {template_id}")

    parts = []
    for section in tmpl.get("sections", []):
        title = _replace_placeholders(section.get("title", ""), context)
        body = _replace_placeholders(section.get("body", ""), context)
        parts.append(f"# {title}\n\n{body}")
    return "\n\n".join(parts)


def _replace_placeholders(text: str, context: dict) -> str:
    pattern = re.compile(r"\{(\w+)\}")

    def replacer(match: re.Match) -> str:
        key = match.group(1)
        return str(context.get(key, "[?]"))

    return pattern.sub(replacer, text)
