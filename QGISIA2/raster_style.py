# -*- coding: utf-8 -*-
"""
Styles raster pseudocolor (QML) pour indices spectraux et analyses mono-bande.

Module pur Python (testable sans QGIS). Genere des QML compatibles
singlebandpseudocolor avec rampe de couleurs interpolable.
"""
from __future__ import annotations

from typing import List

RAMPS = {
    "ndvi": [
        (0.0, "#8B4513"),   # brun (vegetation faible)
        (0.5, "#FFD700"),   # jaune (intermediaire)
        (1.0, "#006400"),   # vert fonce (vegetation dense)
    ],
    "ndwi": [
        (0.0, "#FFFFFF"),   # blanc (eau absente)
        (0.5, "#87CEEB"),   # bleu clair (intermediaire)
        (1.0, "#0000CD"),   # bleu (eau)
    ],
    "thermal": [
        (0.0, "#0000FF"),   # bleu (froid)
        (0.5, "#FF8C00"),   # orange (intermediaire)
        (1.0, "#DC143C"),   # rouge (chaud)
    ],
    "greyscale": [
        (0.0, "#000000"),   # noir
        (0.5, "#808080"),   # gris
        (1.0, "#FFFFFF"),   # blanc
    ],
    "ndmi": [
        (0.0, "#FFFFFF"),   # blanc (sec)
        (0.5, "#87CEEB"),   # bleu clair (intermediaire)
        (1.0, "#0000CD"),   # bleu (humide)
    ],
    "savi": [
        (0.0, "#8B4513"),   # brun (sol nu)
        (0.5, "#9ACD32"),   # vert jaune (intermediaire)
        (1.0, "#006400"),   # vert fonce (vegetation)
    ],
    "rdylgn": [
        (0.0, "#E31A1C"),   # rouge (faible)
        (0.5, "#FFEDA0"),   # jaune (intermediaire)
        (1.0, "#31A354"),   # vert (fort)
    ],
    "spectral": [
        (0.0, "#8B00FF"),   # violet
        (0.25, "#0000FF"),  # bleu
        (0.5, "#00FF00"),   # vert
        (0.75, "#FFFF00"),  # jaune
        (1.0, "#FF0000"),   # rouge
    ],
}


def list_ramps() -> List[str]:
    return list(RAMPS.keys())


def build_pseudocolor_qml(ramp_id: str, vmin: float, vmax: float, band: int = 1) -> str:
    """
    Genere un QML raster singlebandpseudocolor pour une rampe donnee.

    Args:
        ramp_id: identifiant de la rampe (voir RAMPS).
        vmin: valeur min de classification.
        vmax: valeur max de classification.
        band: numero de bande (1-based).

    Raises:
        ValueError: si la rampe est inconnue.
    """
    stops = RAMPS.get(ramp_id)
    if stops is None:
        raise ValueError(f"Rampe inconnue: {ramp_id}")

    span = vmax - vmin
    items_xml = []
    for pos, color in stops:
        val = vmin + pos * span
        items_xml.append(
            f'<item alpha="255" value="{val}" label="{val:.4f}" color="{color}"/>'
        )

    return (
        '<!DOCTYPE qgis>\n'
        '<qgis version="3.34">\n'
        '  <pipe>\n'
        f'    <rasterrenderer type="singlebandpseudocolor" band="{band}" '
        f'classificationMin="{vmin}" classificationMax="{vmax}">\n'
        '      <rastershader>\n'
        '        <colorrampshader classificationMode="2" clip="0" '
        'colorRampType="INTERPOLATED">\n'
        '          ' + '\n          '.join(items_xml) + '\n'
        '        </colorrampshader>\n'
        '      </rastershader>\n'
        '    </rasterrenderer>\n'
        '  </pipe>\n'
        '</qgis>\n'
    )
