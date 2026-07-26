"""Palettes de couleurs accessibles (daltonien-safe) + contraste WCAG.

Module pur Python (testable sans QGIS).
"""
from __future__ import annotations

import math
from typing import Optional

_PALETTES: dict[str, list[str]] = {
    "okabe_ito": [
        "#000000", "#E69F00", "#56B4E9", "#009E73",
        "#F0E442", "#0072B2", "#D55E00", "#CC79A7",
    ],
    "viridis6": [
        "#440154", "#31688E", "#35B779",
        "#FDE725", "#21918C", "#443983",
    ],
    "cividis6": [
        "#00204D", "#404387", "#7D7C9C",
        "#B8A390", "#F2C965", "#FFE945",
    ],
    "colorbrewer_set2": [
        "#66C2A5", "#FC8D62", "#8DA0CB", "#E78AC3",
        "#A6D854", "#FFD92F", "#E5C494", "#B3B3B3",
    ],
    "tol_muted": [
        "#332288", "#88CCEE", "#44AA99", "#117733",
        "#999933", "#DDCC77", "#CC6677", "#882255",
    ],
}


def list_palettes() -> list[str]:
    """Retourne les identifiants des palettes disponibles."""
    return list(_PALETTES.keys())


def get_palette(palette_id: str) -> Optional[list[str]]:
    """Retourne la liste de couleurs d'une palette ou None si inconnu."""
    return _PALETTES.get(palette_id)


def _hex_to_rgb(hexstr: str) -> tuple[float, float, float]:
    """#rrggbb -> (R, G, B) normalisés 0..1."""
    h = hexstr.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (0.0, 0.0, 0.0)
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return (r, g, b)


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    """Calcule la luminance relative WCAG 2.1 pour un RGB normalisé."""
    def _c(c: float) -> float:
        if c <= 0.03928:
            return c / 12.92
        return math.pow((c + 0.055) / 1.055, 2.4)

    r, g, b = rgb
    return 0.2126 * _c(r) + 0.7152 * _c(g) + 0.0722 * _c(b)


def contrast_ratio(hex1: str, hex2: str) -> float:
    """Calcule le ratio de contraste WCAG entre deux couleurs hex."""
    l1 = _relative_luminance(_hex_to_rgb(hex1))
    l2 = _relative_luminance(_hex_to_rgb(hex2))
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def is_accessible(hex1: str, hex2: str, threshold: float = 4.5) -> bool:
    """Vérifie si le contraste atteint le seuil WCAG (4.5 par défaut, AA normal)."""
    return contrast_ratio(hex1, hex2) >= threshold
