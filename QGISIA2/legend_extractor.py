"""Extracteur robuste de legende VLM -> format map_repro.

Module pur Python (testable sans QGIS). Blinde le pipeline image->QML
contre les sorties bruitees du VLM (markdown, virgules trainantes,
cles synonymes, couleurs en mots).
"""
from __future__ import annotations

import json
import re
from typing import Optional

# Imports doubles
try:
    from . import legend_normalizer as ln
except ImportError:
    import legend_normalizer as ln

# ---------------------------------------------------------------------------
# Palette de couleurs FR/EN avec nuances (cartographie)
# ---------------------------------------------------------------------------
_COLOR_WORDS: dict[str, str] = {
    # --- Vert ---
    "vert fonce": "#1B5E20",
    "vert foncé": "#1B5E20",
    "vert": "#008000",
    "vert clair": "#81C784",
    "vert pale": "#C8E6C9",
    "vert pâle": "#C8E6C9",
    "vert citron": "#00FF00",
    # --- Bleu ---
    "bleu fonce": "#0D47A1",
    "bleu foncé": "#0D47A1",
    "bleu": "#0000FF",
    "bleu clair": "#81D4FA",
    "bleu pale": "#B3E5FC",
    "bleu pâle": "#B3E5FC",
    "bleu marine": "#000080",
    "bleu canard": "#008080",
    "cyan": "#00FFFF",
    # --- Rouge ---
    "rouge fonce": "#B71C1C",
    "rouge foncé": "#B71C1C",
    "rouge": "#FF0000",
    "rouge clair": "#EF9A9A",
    "rouge pale": "#FFCDD2",
    "rouge pâle": "#FFCDD2",
    "bordeaux": "#800000",
    "corail": "#FF7F50",
    "saumon": "#FA8072",
    # --- Jaune / Orange ---
    "jaune fonce": "#F9A825",
    "jaune foncé": "#F9A825",
    "jaune": "#FFFF00",
    "jaune clair": "#FFF59D",
    "orange": "#FFA500",
    "orange fonce": "#E65100",
    "orange foncé": "#E65100",
    "or": "#FFD700",
    "kaki": "#F0E68C",
    # --- Violet / Rose ---
    "violet fonce": "#4A148C",
    "violet foncé": "#4A148C",
    "violet": "#800080",
    "violet clair": "#CE93D8",
    "pourpre": "#800080",
    "rose": "#FFC0CB",
    "rose fonce": "#C2185B",
    "rose foncé": "#C2185B",
    "magenta": "#FF00FF",
    "orchidée": "#DA70D6",
    "prune": "#DDA0DD",
    # --- Marron / Gris / Noir / Blanc ---
    "marron": "#A52A2A",
    "brun": "#8B4513",
    "brun fonce": "#5D4037",
    "brun foncé": "#5D4037",
    "gris fonce": "#424242",
    "gris foncé": "#424242",
    "gris": "#808080",
    "gris clair": "#E0E0E0",
    "noir": "#000000",
    "blanc": "#FFFFFF",
    "beige": "#F5F5DC",
    "ivoire": "#FFFFF0",
    # --- Anglais ---
    "dark green": "#1B5E20",
    "green": "#008000",
    "light green": "#81C784",
    "pale green": "#C8E6C9",
    "dark blue": "#0D47A1",
    "blue": "#0000FF",
    "light blue": "#81D4FA",
    "pale blue": "#B3E5FC",
    "dark red": "#B71C1C",
    "red": "#FF0000",
    "light red": "#EF9A9A",
    "pale red": "#FFCDD2",
    "dark yellow": "#F9A825",
    "yellow": "#FFFF00",
    "light yellow": "#FFF59D",
    "dark orange": "#E65100",
    "orange": "#FFA500",
    "dark purple": "#4A148C",
    "purple": "#800080",
    "light purple": "#CE93D8",
    "pink": "#FFC0CB",
    "dark pink": "#C2185B",
    "dark grey": "#424242",
    "gray": "#808080",
    "grey": "#808080",
    "light grey": "#E0E0E0",
    "light gray": "#E0E0E0",
    "black": "#000000",
    "white": "#FFFFFF",
}

# ---------------------------------------------------------------------------
# Prompt VLM
# ---------------------------------------------------------------------------
_VLM_PROMPT_TEMPLATE = (
    "Analyse la legende de cette carte thematique. "
    "Pour CHAQUE entree de legende visible, renvoie un objet JSON strict "
    "avec exactement les cles suivantes : 'label' (texte de la legende), "
    "'color' (code hex #rrggbb ou nom de couleur), 'geometry' (polygon, line ou point). "
    "Reponds UNIQUEMENT par un tableau JSON valide, sans markdown, sans explications. "
    "Intent : {map_intent}"
)


def build_vlm_legend_prompt(map_intent: str) -> str:
    """Genere un prompt strict FR pour le VLM."""
    return _VLM_PROMPT_TEMPLATE.format(map_intent=map_intent)


# ---------------------------------------------------------------------------
# Resolution de couleurs en mots
# ---------------------------------------------------------------------------
def resolve_color_words(text: str) -> Optional[str]:
    """Resout une description de couleur FR/EN en #rrggbb.

    Accepte des nuances : 'vert fonce', 'bleu clair', 'rouge pale'.
    Renvoie None si non reconnu.
    """
    if not text:
        return None
    raw = text.strip().lower()
    # Essaye les expressions les plus longues d'abord (nuances avant couleurs de base)
    candidates = sorted(_COLOR_WORDS.keys(), key=len, reverse=True)
    for cand in candidates:
        if cand in raw:
            return _COLOR_WORDS[cand]
    return None


# ---------------------------------------------------------------------------
# Extraction JSON robuste
# ---------------------------------------------------------------------------
def _clean_json_blob(blob: str) -> str:
    """Nettoie les defauts courants du VLM."""
    # Retire les fences markdown
    blob = re.sub(r"^```(?:json)?\s*", "", blob, flags=re.IGNORECASE)
    blob = re.sub(r"\s*```$", "", blob)
    # Virgules trainantes avant ] ou }
    blob = re.sub(r",(\s*[}\]])", r"\1", blob)
    # Simples quotes -> doubles quotes
    blob = blob.replace("'", '"')
    return blob.strip()


def _extract_fenced_json(text: str) -> Optional[list]:
    """Extrait un tableau JSON a l'interieur d'une fence markdown."""
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    cleaned = _clean_json_blob(m.group(1))
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, list) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_raw_json_array(text: str) -> Optional[list]:
    """Extrait le premier tableau JSON brut du texte."""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end <= start:
        return None
    cleaned = _clean_json_blob(text[start:end + 1])
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, list) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_bullet_list(text: str) -> list[dict]:
    """Parse une liste a puces FR du type '- Label : couleur' ou '• Label : couleur'."""
    items = []
    # Format : marqueur + espaces + label + separateur + couleur
    pattern = re.compile(
        r"^[\s]*(?:[-•–—*]|\+)\s*(.+?)\s*[:\-–]\s*(.+)$",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        label = match.group(1).strip()
        color_raw = match.group(2).strip()
        # Ignore les lignes sans couleur exploitable
        color = ln.normalize_color(color_raw) or resolve_color_words(color_raw)
        if color:
            items.append({"label": label, "color": color, "geometry": ""})
    return items


def _normalize_keys(item: dict) -> dict:
    """Mappe les cles synonymes FR/EN vers {label, color, geometry}."""
    label = str(
        item.get("label")
        or item.get("nom")
        or item.get("classe")
        or item.get("name")
        or item.get("libelle")
        or ""
    ).strip()

    color_raw = str(
        item.get("color")
        or item.get("couleur")
        or item.get("hex")
        or item.get("couleur_hex")
        or ""
    ).strip()

    geometry = str(
        item.get("geometry")
        or item.get("geom")
        or item.get("type_geometrie")
        or item.get("geometrie")
        or ""
    ).strip().lower()

    return {"label": label, "color": color_raw, "geometry": geometry}


def extract_legend_json(vlm_text: str) -> list[dict]:
    """Extrait la legende depuis le texte brut du VLM.

    Tolere : fences markdown, JSON brut, liste a puces FR,
    virgules trainantes, simples quotes, cles synonymes.
    """
    if not vlm_text:
        return []

    # 1. Fence markdown JSON
    data = _extract_fenced_json(vlm_text)
    if data is not None:
        return [_normalize_keys(it) for it in data if isinstance(it, dict)]

    # 2. Tableau JSON brut
    data = _extract_raw_json_array(vlm_text)
    if data is not None:
        return [_normalize_keys(it) for it in data if isinstance(it, dict)]

    # 3. Liste a puces FR/EN
    items = _extract_bullet_list(vlm_text)
    if items:
        return items

    return []


# ---------------------------------------------------------------------------
# Inference de geometry
# ---------------------------------------------------------------------------
_GEOMETRY_HINTS: list[tuple[str, str]] = [
    ("zone|parcelle|surface|aire|polygone|bassin|masse", "polygon"),
    ("route|rue|chemin|voie|ligne|riviere|cours d'eau|fleuve|cours", "line"),
    ("point|station|site|noeud|sommet|centre", "point"),
]


def _infer_geometry(label: str) -> str:
    label_lower = label.lower()
    for pattern, geom in _GEOMETRY_HINTS:
        if re.search(pattern, label_lower):
            return geom
    return "polygon"


# ---------------------------------------------------------------------------
# Pipeline reparation
# ---------------------------------------------------------------------------
def repair_legend(raw_legend: list[dict]) -> dict:
    """Pipeline complet : normalise, deduplique, infere geometry.

    Returns:
        {legend: list[dict], warnings: list[str]}
    """
    warnings: list[str] = []

    if not raw_legend:
        return {"legend": [], "warnings": ["Aucune legende extraite"]}

    # 1. Resolution des couleurs en mots
    resolved = []
    for item in raw_legend:
        label = item.get("label", "")
        color = item.get("color", "")
        geometry = item.get("geometry", "")

        if color and not ln.normalize_color(color):
            resolved_color = resolve_color_words(color)
            if resolved_color:
                color = resolved_color
                warnings.append(f"Couleur '{item['color']}' resolue en {resolved_color}")
            else:
                warnings.append(f"Couleur non reconnue : {item['color']}")
                continue

        resolved.append({"label": label, "color": color, "geometry": geometry})

    # 2. Normalisation via legend_normalizer
    normalized = ln.normalize_legend(resolved)

    # 3. Inference de geometry manquante
    final = []
    for item in normalized:
        geom = item.get("geometry", "")
        if not geom:
            inferred = _infer_geometry(item["label"])
            item = {**item, "geometry": inferred}
            warnings.append(
                f"Geometry manquante pour '{item['label']}' -> inferée {inferred}"
            )
        final.append(item)

    # 4. Dedup par label
    seen_labels: set[str] = set()
    deduped = []
    for item in final:
        lbl = item["label"]
        if lbl in seen_labels:
            warnings.append(f"Label duplique supprime : {lbl}")
            continue
        seen_labels.add(lbl)
        deduped.append(item)

    if not deduped:
        warnings.append("Legende vide apres nettoyage")

    return {"legend": deduped, "warnings": warnings}
