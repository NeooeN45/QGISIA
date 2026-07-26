"""Generateur de plans d'etude territoriale riches (20 a 100 etapes).

Remplace les plans statiques de study_plan.py sans le supprimer.
Module pur Python, zero import QGIS.
"""
from __future__ import annotations

import copy

# Imports doubles
try:
    from . import pipeline_engine as pe
except ImportError:
    import pipeline_engine as pe

ALLOWED_ACTIONS = frozenset({
    "add_basemap", "load_satellite", "compute_index", "detect_change", "classify",
    "zonal_stats", "layout", "report", "bufferLayer", "computeTerrain",
    "suitabilityAnalysis", "hotspotAnalysis", "clusterPoints", "exportAtlas",
    "applySymbologyPreset", "saveVectorLayer", "renderMapView",
})

# Mapping vers pipeline_engine.ACTION_SCHEMA
_ACTION_TO_PIPELINE: dict[str, str] = {
    "add_basemap": "add_basemap",
    "load_satellite": "load_satellite",
    "compute_index": "compute_index",
    "detect_change": "raster_difference",
    "classify": "classify",
    "zonal_stats": "zonal_stats",
    "bufferLayer": "buffer",
    "computeTerrain": "terrain",
    "suitabilityAnalysis": "suitability",
    "hotspotAnalysis": "hotspot",
    "clusterPoints": "hotspot",
    "exportAtlas": "atlas",
    "applySymbologyPreset": "layout",
    "saveVectorLayer": "report",
    "renderMapView": "layout",
    "layout": "layout",
    "report": "report",
}

# Valeurs par defaut pour les required_params de ACTION_SCHEMA
_DEFAULT_PARAMS: dict[str, dict] = {
    "add_basemap": {"source_id": "osm-standard"},
    "load_satellite": {"source_id": "sentinel-2-l2a"},
    "compute_index": {"index": "ndvi"},
    "raster_difference": {},
    "classify": {"method": "kmeans"},
    "zonal_stats": {"vector_layer": "study_zone"},
    "buffer": {"distance": 100},
    "terrain": {"method": "slope"},
    "suitability": {"preset_id": "default"},
    "hotspot": {},
    "layout": {},
    "atlas": {},
    "report": {},
}

_PHASE_MAP: dict[str, str] = {
    "add_basemap": "data",
    "load_satellite": "data",
    "compute_index": "analyse",
    "detect_change": "analyse",
    "classify": "analyse",
    "zonal_stats": "analyse",
    "bufferLayer": "analyse",
    "computeTerrain": "analyse",
    "suitabilityAnalysis": "analyse",
    "hotspotAnalysis": "analyse",
    "clusterPoints": "analyse",
    "applySymbologyPreset": "symbologie",
    "renderMapView": "symbologie",
    "layout": "layout",
    "exportAtlas": "layout",
    "saveVectorLayer": "livrable",
    "report": "livrable",
}

# Indices recommandes par theme
_THEME_INDICES: dict[str, list[str]] = {
    "vegetation": ["ndvi", "evi", "savi", "ndre", "gndvi"],
    "urbanisme": ["ndbi", "ndvi", "mndwi", "ui", "nbi"],
    "risques": ["mndwi", "ndvi", "ndbi", "ndre", "savi"],
    "foret": ["ndvi", "evi", "ndmi", "savi", "ndre"],
    "hydrologie": ["mndwi", "ndwi", "ndmi", "awei", "wi"],
    "agriculture": ["ndvi", "evi", "gndvi", "savi", "ndre"],
}

_DEPTH_RANGES = {
    "rapide": (18, 22),
    "standard": (45, 55),
    "approfondi": (90, 100),
}


class _PlanBuilder:
    """Accumulateur d'etapes avec IDs uniques et gestion des dependances."""

    def __init__(self, theme: str, depth: str, context: dict) -> None:
        self.theme = theme
        self.depth = depth
        self.context = context
        self.steps: list[dict] = []
        self._id_set: set[str] = set()
        self._action_counts: dict[str, int] = {}

    def _make_id(self, action: str, suffix: str = "") -> str:
        self._action_counts[action] = self._action_counts.get(action, 0) + 1
        count = self._action_counts[action]
        base = f"{self.theme}_{action}"
        if suffix:
            base = f"{base}_{suffix}"
        return f"{base}_{count:03d}"

    def add(
        self,
        action: str,
        params: dict | None = None,
        *,
        phase: str | None = None,
        optional: bool = False,
        depends_on: list[str] | None = None,
        step_id: str | None = None,
        suffix: str = "",
    ) -> str:
        if step_id is None:
            step_id = self._make_id(action, suffix)
        if step_id in self._id_set:
            raise ValueError(f"ID duplique: {step_id}")
        self._id_set.add(step_id)

        # Le contexte utilisateur (bbox, datetime...) sert de base ; les params
        # explicites de l'etape (index, method...) gardent la priorite.
        merged_params = {**self.context, **(params or {})}
        step = {
            "id": step_id,
            "action": action,
            "params": merged_params,
            "depends_on": list(depends_on) if depends_on else [],
            "phase": phase or _PHASE_MAP.get(action, "analyse"),
            "optional": optional,
        }
        self.steps.append(step)
        return step_id


def _build_theme_plan(theme: str, depth: str, context: dict) -> list[dict]:
    """Construit le plan complet pour un theme et une profondeur."""
    builder = _PlanBuilder(theme, depth, context)
    all_indices = _THEME_INDICES.get(theme, ["ndvi"])

    # Nombre de dates et d'indices selon la profondeur
    if depth == "rapide":
        num_dates = 1
        num_indices = min(3, len(all_indices))
    elif depth == "standard":
        num_dates = 2
        num_indices = min(5, len(all_indices))
    else:  # approfondi
        num_dates = 3
        num_indices = min(4, len(all_indices))

    indices = all_indices[:num_indices]

    # Phase data : acquisitions
    sat_ids = []
    builder.add("add_basemap", {"source_id": "osm-standard"}, depends_on=[])
    for d in range(num_dates):
        date_label = f"date{d + 1}"
        sid = builder.add("load_satellite", {"source_id": "sentinel-2-l2a", "date": date_label}, depends_on=[])
        sat_ids.append(sid)

    # Phase analyse : pipeline par indice x date
    for idx in indices:
        for sat_id in sat_ids:
            idx_id = builder.add("compute_index", {"index": idx}, depends_on=[sat_id], suffix=idx)
            builder.add("zonal_stats", {"vector_layer": "study_zone"}, depends_on=[idx_id], suffix=idx)
            builder.add("classify", {"method": "kmeans"}, depends_on=[idx_id], suffix=idx)
            if depth == "approfondi":
                builder.add("classify", {"method": "svm"}, depends_on=[idx_id], optional=True, suffix=f"{idx}_svm")
            builder.add("layout", {}, depends_on=[idx_id], optional=(depth == "approfondi"), suffix=f"{idx}_layout")
            if depth == "approfondi":
                builder.add("applySymbologyPreset", {}, depends_on=[idx_id], optional=True, suffix=f"{idx}_symb")

    # Detection de changement
    if len(sat_ids) >= 2:
        builder.add("detect_change", {}, depends_on=sat_ids[:2], optional=(depth == "approfondi"), suffix="d1d2")
    if depth == "approfondi" and len(sat_ids) >= 3:
        builder.add("detect_change", {}, depends_on=[sat_ids[0], sat_ids[2]], optional=True, suffix="d1d3")
        builder.add("detect_change", {}, depends_on=[sat_ids[1], sat_ids[2]], optional=True, suffix="d2d3")

    # Terrain
    terrain_methods = ["slope"]
    if depth == "approfondi":
        terrain_methods = ["slope", "aspect", "hillshade"]
    elif depth == "standard":
        terrain_methods = ["slope", "aspect"]
    for method in terrain_methods:
        builder.add("computeTerrain", {"method": method}, depends_on=[sat_ids[0]], optional=(depth == "approfondi"), suffix=method)

    # Buffer
    if depth == "approfondi":
        for dist in [100, 250]:
            builder.add("bufferLayer", {"distance": dist}, depends_on=[sat_ids[0]], optional=True, suffix=f"d{dist}")

    # Hotspot / clustering
    if depth in ("standard", "approfondi"):
        builder.add("hotspotAnalysis", {}, depends_on=[sat_ids[0]], optional=True, suffix="hs")
    if depth == "approfondi":
        builder.add("clusterPoints", {}, depends_on=[sat_ids[0]], optional=True, suffix="cl")

    # Suitability
    if depth == "approfondi":
        for preset in ["default", "forestry"]:
            builder.add("suitabilityAnalysis", {"preset_id": preset}, depends_on=[sat_ids[0]], optional=True, suffix=preset)

    # Symbologie et layout globaux
    first_compute = next((s["id"] for s in builder.steps if s["action"] == "compute_index"), sat_ids[0])
    builder.add("applySymbologyPreset", {}, depends_on=[first_compute], optional=(depth == "approfondi"), suffix="global")
    if depth == "approfondi":
        builder.add("renderMapView", {}, depends_on=[first_compute], optional=True, suffix="global")

    builder.add("layout", {}, depends_on=[first_compute], optional=(depth == "approfondi"), suffix="global")
    if depth == "approfondi":
        for layout_type in ["overview", "detail", "comparison"]:
            builder.add("layout", {"type": layout_type}, depends_on=[first_compute], optional=True, suffix=layout_type)

    # Atlas
    if depth == "approfondi":
        layout_ids = [s["id"] for s in builder.steps if s["action"] == "layout"]
        if layout_ids:
            builder.add("exportAtlas", {}, depends_on=[layout_ids[0]], optional=True, suffix="global")

    # Livrables
    zonal_ids = [s["id"] for s in builder.steps if s["action"] == "zonal_stats"]
    dep = [zonal_ids[0]] if zonal_ids else [sat_ids[0]]
    builder.add("report", {}, depends_on=dep, optional=(depth == "approfondi"), suffix="global")
    if depth == "approfondi":
        builder.add("saveVectorLayer", {}, depends_on=[sat_ids[0]], optional=True, suffix="global")
        for report_type in ["executive", "technical", "annex"]:
            builder.add("report", {"type": report_type}, depends_on=dep, optional=True, suffix=report_type)

    return builder.steps


def build_rich_plan(theme: str, context: dict, *, depth: str = "standard") -> list[dict]:
    """Genere un plan d'etude riche pour un theme.

    Args:
        theme: vegetation, urbanisme, risques, foret, hydrologie, agriculture.
        context: parametres utilisateur injectes dans chaque etape.
        depth: rapide (~20), standard (~50), approfondi (~100).

    Returns:
        Liste d'etapes {id, action, params, depends_on, phase, optional}.
    """
    if depth not in _DEPTH_RANGES:
        raise ValueError(f"depth doit etre dans {set(_DEPTH_RANGES.keys())!r}")

    plan = _build_theme_plan(theme, depth, context)
    # Verification de base : pas de reference a un ID inexistant
    id_set = {step["id"] for step in plan}
    for step in plan:
        for dep in step.get("depends_on", []):
            if dep not in id_set:
                raise ValueError(
                    f"Etape {step['id']} depend de {dep!r} qui n'existe pas"
                )
    return plan


def validate_with_pipeline(plan: list[dict]) -> dict:
    """Convertit le plan au format pipeline_engine et valide.

    Returns:
        {valid: bool, errors: list[str], order: list[str], cost: dict}
    """
    steps = []
    for step in plan:
        action = step["action"]
        pipeline_action = _ACTION_TO_PIPELINE.get(action)
        if not pipeline_action:
            return {
                "valid": False,
                "errors": [f"Action inconnue: {action}"],
                "order": [],
                "cost": {},
            }

        # Fusion des params avec les valeurs par defaut requises
        merged_params = copy.deepcopy(_DEFAULT_PARAMS.get(pipeline_action, {}))
        merged_params.update(step.get("params", {}))

        pipeline_step = {
            "id": step["id"],
            "action": pipeline_action,
            "params": merged_params,
            "needs": list(step.get("depends_on", [])),
        }
        steps.append(pipeline_step)

    pipeline = {"steps": steps}
    errors = pe.validate_pipeline(pipeline)
    is_valid = len(errors) == 0

    order: list[str] = []
    if is_valid:
        try:
            order = pe.topological_order(pipeline)
        except ValueError as exc:
            errors.append(str(exc))
            is_valid = False

    cost = pe.estimate_cost(pipeline) if is_valid else {}

    return {
        "valid": is_valid,
        "errors": errors,
        "order": order,
        "cost": cost,
    }


def to_progress_payload(plan: list[dict]) -> dict:
    """Prepare un payload pour la barre de progression UI.

    Returns:
        {total, by_phase: dict, optional_count, mandatory_count}
    """
    total = len(plan)
    by_phase: dict[str, int] = {}
    optional_count = 0
    mandatory_count = 0
    for step in plan:
        phase = step.get("phase", "analyse")
        by_phase[phase] = by_phase.get(phase, 0) + 1
        if step.get("optional"):
            optional_count += 1
        else:
            mandatory_count += 1
    return {
        "total": total,
        "by_phase": by_phase,
        "optional_count": optional_count,
        "mandatory_count": mandatory_count,
    }
