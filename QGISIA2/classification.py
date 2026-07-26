# -*- coding: utf-8 -*-
"""
Classification thematique raster (QML discret) pour indices et analyses terrain.

Module pur Python (testable sans QGIS). Genere des QML singlebandpseudocolor
avec colorRampType="DISCRETE" (1 item par classe, sans interpolation entre classes).
"""
from __future__ import annotations

from typing import List

SCHEMES = {
    "ndvi_vegetation": {
        "name": "NDVI — Classes de vegetation",
        "classes": [
            {"max": 0.0, "label": "Eau / Ombre", "color": "#1E90FF"},
            {"max": 0.2, "label": "Sol nu / Urbain", "color": "#D2B48C"},
            {"max": 0.4, "label": "Vegetation faible", "color": "#FFD700"},
            {"max": 0.6, "label": "Vegetation moyenne", "color": "#9ACD32"},
            {"max": 1.0, "label": "Vegetation dense", "color": "#006400"},
        ],
    },
    "dnbr_severite": {
        "name": "dNBR — Severite du feu",
        "classes": [
            {"max": 0.1, "label": "Regain / Non brule", "color": "#006400"},
            {"max": 0.27, "label": "Faible severite", "color": "#9ACD32"},
            {"max": 0.44, "label": "Severite moderée", "color": "#FFA500"},
            {"max": 0.66, "label": "Severite forte", "color": "#FF4500"},
            {"max": 1.0, "label": "Severite tres forte", "color": "#8B0000"},
        ],
    },
    "pente_degres": {
        "name": "Pente — Classes de degres",
        "classes": [
            {"max": 2.0, "label": "Plat", "color": "#2E8B57"},
            {"max": 5.0, "label": "Faible", "color": "#9ACD32"},
            {"max": 15.0, "label": "Moyenne", "color": "#FFD700"},
            {"max": 30.0, "label": "Forte", "color": "#FF8C00"},
            {"max": 90.0, "label": "Tres forte", "color": "#DC143C"},
        ],
    },
}


def list_schemes() -> List[dict]:
    return [{"id": k, "name": v["name"], "classes": len(v["classes"])} for k, v in SCHEMES.items()]


def get_scheme(scheme_id: str) -> dict | None:
    meta = SCHEMES.get(scheme_id)
    if meta is None:
        return None
    return {"id": scheme_id, "name": meta["name"], "classes": meta["classes"]}


def build_discrete_pseudocolor_qml(scheme_id: str, band: int = 1) -> str:
    """
    Genere un QML raster singlebandpseudocolor DISCRETE pour un scheme de classification.

    Args:
        scheme_id: identifiant du scheme (voir SCHEMES).
        band: numero de bande (1-based).

    Raises:
        ValueError: si le scheme est inconnu.
    """
    scheme = SCHEMES.get(scheme_id)
    if scheme is None:
        raise ValueError(f"Scheme inconnu: {scheme_id}")

    classes = scheme["classes"]
    items_xml = []
    for cls in classes:
        items_xml.append(
            f'<item alpha="255" value="{cls["max"]}" label="{cls["label"]}" color="{cls["color"]}"/>'
        )

    vmin = 0.0  # bornes par defaut pour rasterrenderer
    vmax = classes[-1]["max"]

    return (
        '<!DOCTYPE qgis>\n'
        '<qgis version="3.34">\n'
        '  <pipe>\n'
        f'    <rasterrenderer type="singlebandpseudocolor" band="{band}" '
        f'classificationMin="{vmin}" classificationMax="{vmax}">\n'
        '      <rastershader>\n'
        '        <colorrampshader classificationMode="2" clip="0" '
        'colorRampType="DISCRETE">\n'
        '          ' + '\n          '.join(items_xml) + '\n'
        '        </colorrampshader>\n'
        '      </rastershader>\n'
        '    </rasterrenderer>\n'
        '  </pipe>\n'
        '</qgis>\n'
    )
