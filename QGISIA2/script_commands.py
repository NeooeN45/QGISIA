# -*- coding: utf-8 -*-
"""
script_commands — API de commandes autorisées pour agir sur le projet QGIS.

Module PUR (aucune dépendance Qt/QGIS), testable en CI.

Raison d'être : l'exécution de code généré par un LLM a quitté le processus
QGIS (`script_sandbox`), et le bac à sable n'a — par construction — aucun
accès au projet. Les mutations passent donc désormais par une table figée de
commandes déclaratives :

    {"command": "setLayerVisibility", "params": {"layerId": "L1", "visible": false}}

Chaque commande est résolue vers une méthode du bridge déjà existante, et
chaque paramètre est validé en **nom** et en **type**. Il n'existe aucun
chemin depuis ce module vers `exec`, `eval` ou une méthode d'exécution de
script : `tests/test_script_commands.py` le vérifie explicitement.

Principes de validation :
- allowlist stricte : commande inconnue -> refus ;
- clé de paramètre inconnue -> refus (jamais d'ignorance silencieuse, qui
  masquerait une faute de frappe ou une tentative d'injection) ;
- typage strict : `bool` n'est pas accepté pour un nombre, `str` n'est pas
  coercé depuis un entier ;
- lot « tout ou rien » : une commande invalide invalide le lot entier, pour
  qu'aucune mutation partielle ne soit appliquée.
"""
from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

# Longueur maximale d'un paramètre texte (WKT, QML et GeoJSON peuvent être longs).
MAX_STRING_LENGTH = 64 * 1024

# Nombre maximal de commandes dans un lot (anti-boucle d'agent runaway).
MAX_BATCH_COMMANDS = 50


class Param(NamedTuple):
    """Spécification d'un paramètre de commande."""

    name: str
    kind: str          # "str" | "bool" | "float"
    required: bool = True
    default: Any = None


class Command(NamedTuple):
    """Spécification d'une commande autorisée."""

    bridge_method: str
    params: Tuple[Param, ...]
    writes_filesystem: bool = False


def _s(name: str, required: bool = True, default: str = "") -> Param:
    return Param(name, "str", required, default)


def _b(name: str, default: bool = True) -> Param:
    return Param(name, "bool", False, default)


def _f(name: str, required: bool = True, default: float = 0.0) -> Param:
    return Param(name, "float", required, default)


# ── Table des commandes autorisées ────────────────────────────────────────────
# Les signatures reproduisent exactement celles des slots du bridge existants
# (ordre des arguments compris) : cette table ne crée aucune capacité neuve,
# elle rend explicite et vérifiable ce qui était atteint par du code arbitraire.
COMMAND_SPECS: Dict[str, Command] = {
    # Affichage et navigation
    "setLayerVisibility": Command("setLayerVisibility", (_s("layerId"), _b("visible", True))),
    "setLayerOpacity": Command("setLayerOpacity", (_s("layerId"), _f("opacity"))),
    "zoomToLayer": Command("zoomToLayer", (_s("layerId"),)),
    "setMapExtent": Command("setMapExtent", (_s("bbox"),)),

    # Organisation des couches
    "renameLayer": Command("renameLayer", (_s("layerId"), _s("name"))),
    "setLayerGroup": Command("setLayerGroup", (_s("layerId"), _s("groupName"))),
    "filterLayer": Command("filterLayer", (_s("layerId"), _s("subsetString"))),
    "reprojectLayer": Command("reprojectLayer", (_s("layerId"), _s("targetCrs"))),

    # Symbologie et étiquettes
    "applyQmlStyle": Command("applyQmlStyle", (_s("layerId"), _s("qml"))),
    "applySymbologyPreset": Command(
        "applySymbologyPreset",
        (_s("layerId"), _s("presetId"), _s("field", required=False)),
    ),
    "applyParcelStylePreset": Command("applyParcelStylePreset", (_s("layerId"), _s("presetId"))),
    "setLayerLabels": Command(
        "setLayerLabels", (_s("layerId"), _s("fieldName"), _b("enabled", True))
    ),

    # Ajout de données
    "addGeoJsonLayer": Command("addGeoJsonLayer", (_s("geojson"), _s("layerName"))),
    "addRemoteRaster": Command("addRemoteRaster", (_s("url"), _s("layerName"))),
    "addDataSource": Command("addDataSource", (_s("sourceId"), _s("name"))),

    # Analyse
    "bufferLayer": Command(
        "bufferLayer", (_s("layerId"), _s("distance"), _s("outputName"))
    ),
    "zonalStatistics": Command(
        "zonalStatistics", (_s("rasterId"), _s("polygonId"), _s("prefix"))
    ),
    "classifyRaster": Command("classifyRaster", (_s("layerId"), _s("schemeId"))),
    "classifyChange": Command("classifyChange", (_s("layerId"), _s("schemeId"))),
    "computeTerrain": Command(
        "computeTerrain",
        (_s("demId"), _s("analysis", required=False, default="slope"),
         _s("outputPath", required=False)),
        writes_filesystem=True,
    ),
    "clusterPoints": Command(
        "clusterPoints", (_s("pointId"), _s("eps"), _s("minPts"))
    ),
    "splitSelectedLayerByLine": Command(
        "splitSelectedLayerByLine", (_s("layerId"), _s("lineWkt"), _s("outputName"))
    ),

    # Écriture disque (déclarée explicitement, traitée à part par l'UI)
    "saveVectorLayer": Command(
        "saveVectorLayer",
        (_s("layerId"), _s("outputPath"), _s("driver", required=False, default="GPKG")),
        writes_filesystem=True,
    ),
}


def list_commands() -> List[str]:
    """Noms des commandes autorisées, triés."""
    return sorted(COMMAND_SPECS)


def bridge_method_for(name: str) -> Optional[str]:
    """Méthode du bridge appelée par une commande, ou None si inconnue."""
    spec = COMMAND_SPECS.get(name)
    return spec.bridge_method if spec else None


def filesystem_writing_commands() -> List[str]:
    """Commandes qui écrivent sur le disque (revue de sécurité, UI)."""
    return sorted(n for n, s in COMMAND_SPECS.items() if s.writes_filesystem)


def _coerce(param: Param, value: Any) -> Tuple[bool, str, Any]:
    """Contrôle le type d'un paramètre. Aucune coercition depuis str."""
    if param.kind == "str":
        if not isinstance(value, str):
            return False, f"paramètre '{param.name}' : chaîne attendue", None
        if len(value) > MAX_STRING_LENGTH:
            return False, (
                f"paramètre '{param.name}' trop long "
                f"({len(value)} > {MAX_STRING_LENGTH})"
            ), None
        return True, "", value

    if param.kind == "bool":
        if not isinstance(value, bool):
            return False, f"paramètre '{param.name}' : booléen attendu", None
        return True, "", value

    if param.kind == "float":
        # bool est un sous-type de int : l'exclure explicitement.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False, f"paramètre '{param.name}' : nombre attendu", None
        return True, "", float(value)

    return False, f"paramètre '{param.name}' : type non supporté", None  # pragma: no cover


def validate_command(
    name: Any, params: Any
) -> Tuple[bool, str, Optional[Tuple[str, Tuple[Any, ...]]]]:
    """Valide une commande. Retourne (ok, erreur, (méthode_bridge, arguments))."""
    if not isinstance(name, str) or name not in COMMAND_SPECS:
        return False, f"Commande non autorisée : {name!r}", None

    if params is None:
        params = {}
    if not isinstance(params, dict):
        return False, f"Commande '{name}' : 'params' doit être un objet", None

    spec = COMMAND_SPECS[name]
    known = {p.name for p in spec.params}
    unknown = sorted(set(params) - known)
    if unknown:
        return False, (
            f"Commande '{name}' : paramètre(s) inconnu(s) {', '.join(unknown)}"
        ), None

    args: List[Any] = []
    for param in spec.params:
        if param.name not in params:
            if param.required:
                return False, f"Commande '{name}' : paramètre '{param.name}' requis", None
            args.append(param.default)
            continue
        ok, error, value = _coerce(param, params[param.name])
        if not ok:
            return False, f"Commande '{name}' : {error}", None
        args.append(value)

    return True, "", (spec.bridge_method, tuple(args))


def validate_command_batch(
    commands: Any,
) -> Tuple[bool, str, Optional[List[Tuple[str, Tuple[Any, ...]]]]]:
    """Valide un lot de commandes. Tout ou rien : un refus invalide le lot."""
    if not isinstance(commands, Sequence) or isinstance(commands, (str, bytes)):
        return False, "Le lot de commandes doit être une liste.", None
    if not commands:
        return False, "Lot de commandes vide.", None
    if len(commands) > MAX_BATCH_COMMANDS:
        return False, (
            f"Lot de {len(commands)} commandes > maximum {MAX_BATCH_COMMANDS}."
        ), None

    calls: List[Tuple[str, Tuple[Any, ...]]] = []
    for index, entry in enumerate(commands):
        if not isinstance(entry, dict):
            return False, f"Commande #{index + 1} : objet attendu.", None
        ok, error, call = validate_command(entry.get("command"), entry.get("params"))
        if not ok:
            return False, f"Commande #{index + 1} refusée — {error}", None
        calls.append(call)

    return True, "", calls
