"""Normaliseur de légende OCR/VLM -> format map_repro ({value, label, color}).

Module pur Python (testable sans QGIS). Accepte une grande variété d'entrées
brutes et les transforme en légende structurée.
"""
from __future__ import annotations

import re
from typing import Optional

_COLOR_NAMES = {
    # Anglais
    "black": "#000000",
    "white": "#ffffff",
    "red": "#ff0000",
    "green": "#008000",
    "blue": "#0000ff",
    "yellow": "#ffff00",
    "cyan": "#00ffff",
    "magenta": "#ff00ff",
    "orange": "#ffa500",
    "purple": "#800080",
    "brown": "#a52a2a",
    "grey": "#808080",
    "gray": "#808080",
    "pink": "#ffc0cb",
    "lime": "#00ff00",
    "navy": "#000080",
    "teal": "#008080",
    "olive": "#808000",
    "maroon": "#800000",
    "silver": "#c0c0c0",
    "gold": "#ffd700",
    "coral": "#ff7f50",
    "salmon": "#fa8072",
    "beige": "#f5f5dc",
    "ivory": "#fffff0",
    "khaki": "#f0e68c",
    "plum": "#dda0dd",
    "orchid": "#da70d6",
    "tan": "#d2b48c",
    # Français
    "noir": "#000000",
    "blanc": "#ffffff",
    "rouge": "#ff0000",
    "vert": "#008000",
    "bleu": "#0000ff",
    "jaune": "#ffff00",
    "cyan": "#00ffff",
    "magenta": "#ff00ff",
    "orange": "#ffa500",
    "violet": "#800080",
    "pourpre": "#800080",
    "marron": "#a52a2a",
    "gris": "#808080",
    "rose": "#ffc0cb",
    "vert citron": "#00ff00",
    "bleu marine": "#000080",
    "bleu canard": "#008080",
    "olive": "#808000",
    "bordeaux": "#800000",
    "argent": "#c0c0c0",
    "or": "#ffd700",
    "corail": "#ff7f50",
    "saumon": "#fa8072",
    "beige": "#f5f5dc",
    "ivoire": "#fffff0",
    "kaki": "#f0e68c",
    "prune": "#dda0dd",
    "orchidée": "#da70d6",
}


def _expand_short_hex(hexstr: str) -> str:
    """#fff -> #ffffff."""
    h = hexstr.lstrip("#")
    if len(h) == 3 and all(c in "0123456789abcdefABCDEF" for c in h):
        return "#" + "".join(c * 2 for c in h)
    return hexstr


def _parse_rgb_triple(text: str) -> Optional[str]:
    """Interprète '255,0,0' ou 'rgb(255, 0, 0)' -> #ff0000."""
    # rgb(r,g,b)
    m = re.search(r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)", text, re.IGNORECASE)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if all(0 <= c <= 255 for c in (r, g, b)):
            return f"#{r:02x}{g:02x}{b:02x}"
    # 255,0,0
    parts = text.split(",")
    if len(parts) == 3:
        try:
            r, g, b = int(parts[0].strip()), int(parts[1].strip()), int(parts[2].strip())
            if all(0 <= c <= 255 for c in (r, g, b)):
                return f"#{r:02x}{g:02x}{b:02x}"
        except ValueError:
            pass
    return None


def normalize_color(s: str) -> Optional[str]:
    """Normalise une couleur brute en #rrggbb ; renvoie None si non interprétable."""
    if not s:
        return None

    raw = s.strip().lower()

    # Nom de couleur
    if raw in _COLOR_NAMES:
        return _COLOR_NAMES[raw]

    # Hex court / long
    if raw.startswith("#"):
        h = raw.lstrip("#")
        if len(h) == 3 and all(c in "0123456789abcdef" for c in h):
            return _expand_short_hex(raw)
        if len(h) == 6 and all(c in "0123456789abcdef" for c in h):
            return raw
        return None

    # rgb() ou triple CSV
    parsed = _parse_rgb_triple(s)
    if parsed:
        return parsed

    return None


def normalize_legend(raw: list[dict]) -> list[dict]:
    """Transforme une légende brute (VLM/OCR) en [{value, label, color}]."""
    normalized = []
    for item in raw:
        if not isinstance(item, dict):
            continue

        label = str(
            item.get("label")
            or item.get("nom")
            or item.get("classe")
            or item.get("name")
            or ""
        ).strip()

        color_raw = str(
            item.get("color")
            or item.get("couleur")
            or item.get("hex")
            or ""
        ).strip()
        color = normalize_color(color_raw)
        if color is None:
            continue

        value = str(
            item.get("value")
            or item.get("valeur")
            or label
            or ""
        ).strip()

        normalized.append({"value": value, "label": label, "color": color})

    return normalized
