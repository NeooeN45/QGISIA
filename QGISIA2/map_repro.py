# -*- coding: utf-8 -*-
"""
Reproduction de carte : legende (extraite par un VLM) -> style QGIS (.qml).

Pipeline cible : image de carte -> VLM renvoie un JSON de legende
[{label, color, geometry}] -> on genere un renderer categorise QML applicable
a une couche QGIS. Ce module est 100% pur Python (testable sans QGIS).
"""
from __future__ import annotations

import json
import re
from typing import List, Optional
from xml.sax.saxutils import escape

# Prompt pour demander au VLM une legende structuree (utilise par l'agent vision).
LEGEND_EXTRACTION_PROMPT = (
    "Analyse la legende de cette carte. Pour CHAQUE entree de legende, renvoie un "
    "objet JSON avec: 'label' (texte), 'color' (hex #rrggbb du figure), 'geometry' "
    "(polygon, line ou point). Reponds UNIQUEMENT par un tableau JSON, sans markdown."
)


def _extract_json_array(text: str) -> Optional[list]:
    """Extrait le premier tableau JSON d'un texte (tolere fences markdown / prose)."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1).strip() if fenced else text.strip()
    start, end = candidate.find("["), candidate.rfind("]")
    if start != -1 and end > start:
        candidate = candidate[start:end + 1]
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return None


def parse_legend(text: str) -> List[dict]:
    """Normalise la legende renvoyee par le VLM en [{label, color, geometry}]."""
    data = _extract_json_array(text)
    if not isinstance(data, list):
        return []
    legend: List[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("classe") or item.get("name") or "").strip()
        color = str(item.get("color") or item.get("couleur") or item.get("hex") or "").strip()
        geometry = str(item.get("geometry") or item.get("geom") or "polygon").strip().lower()
        if label and color:
            legend.append({"label": label, "color": color, "geometry": geometry})
    return legend


def hex_to_qgis_color(hexstr: str) -> str:
    """'#228B22' -> '34,139,34,255' (format couleur QGIS r,g,b,a)."""
    h = (hexstr or "").lstrip("#").strip()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return "0,0,0,255"
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return "0,0,0,255"
    return f"{r},{g},{b},255"


def _symbol_xml(index: int, geometry: str, qgis_color: str) -> str:
    geom = (geometry or "polygon").lower()
    if geom.startswith("line") or geom in ("ligne", "linestring"):
        return (
            f'<symbol type="line" name="{index}">'
            f'<layer class="SimpleLine"><Option type="Map">'
            f'<Option name="line_color" type="QString" value="{qgis_color}"/>'
            f'<Option name="line_width" type="QString" value="0.5"/>'
            f'</Option></layer></symbol>'
        )
    if geom.startswith("point") or geom in ("marker", "node"):
        return (
            f'<symbol type="marker" name="{index}">'
            f'<layer class="SimpleMarker"><Option type="Map">'
            f'<Option name="color" type="QString" value="{qgis_color}"/>'
            f'<Option name="size" type="QString" value="2"/>'
            f'</Option></layer></symbol>'
        )
    return (
        f'<symbol type="fill" name="{index}">'
        f'<layer class="SimpleFill"><Option type="Map">'
        f'<Option name="color" type="QString" value="{qgis_color}"/>'
        f'<Option name="outline_color" type="QString" value="35,35,35,255"/>'
        f'<Option name="outline_width" type="QString" value="0.26"/>'
        f'<Option name="style" type="QString" value="solid"/>'
        f'</Option></layer></symbol>'
    )


def legend_to_qml(legend: List[dict], field: str = "classe",
                  geometry: Optional[str] = None) -> str:
    """Genere un renderer categorise QML a partir d'une legende normalisee."""
    geom = (geometry or (legend[0]["geometry"] if legend else "polygon")).lower()
    categories, symbols = [], []
    for i, item in enumerate(legend):
        color = hex_to_qgis_color(item["color"])
        label = escape(item["label"])
        # 'value' = valeur du champ a matcher (presets) ; defaut = label (vision).
        value = escape(str(item.get("value", item["label"])))
        categories.append(
            f'<category value="{value}" symbol="{i}" label="{label}" render="true"/>')
        symbols.append(_symbol_xml(i, item.get("geometry", geom), color))
    return (
        '<!DOCTYPE qgis>\n'
        '<qgis version="3.34" styleCategories="Symbology">\n'
        f'  <renderer-v2 type="categorizedSymbol" attr="{escape(field)}" '
        'forceraster="0" enableorderby="0" symbollevels="0">\n'
        '    <categories>\n      ' + '\n      '.join(categories) + '\n    </categories>\n'
        '    <symbols>\n    ' + '\n    '.join(symbols) + '\n    </symbols>\n'
        '  </renderer-v2>\n'
        '</qgis>\n'
    )
