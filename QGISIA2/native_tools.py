# -*- coding: utf-8 -*-
"""
Outils NATIFS de l'agent (web/geo-grounding) — executes en-process, sans QGIS
et sans cle API. Permettent au LLM de completer ses requetes avec des donnees
live : geocodage (Nominatim/OSM), meteo et elevation (Open-Meteo).

Toutes les sources sont gratuites et ouvertes. Le getter HTTP est injectable
pour les tests (`get_json`).
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OPENMETEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPENMETEO_ELEVATION = "https://api.open-meteo.com/v1/elevation"
EARTH_SEARCH_STAC = "https://earth-search.aws.element84.com/v1/search"
WIKIPEDIA_SUMMARY = "https://fr.wikipedia.org/api/rest_v1/page/summary/"

_USER_AGENT = "QGISIA-Plus/3.4 (assistant SIG ; contact qgisai.plus@gmail.com)"


def _default_get_json(url: str, params: dict, timeout: float = 20.0) -> Any:
    """GET JSON via la stdlib (pas de dependance externe). Respecte un User-Agent."""
    query = urllib.parse.urlencode(params or {})
    full = f"{url}?{query}" if query else url
    req = urllib.request.Request(full, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (URLs fixes/https)
        return json.loads(resp.read().decode("utf-8"))


@dataclass
class NativeTool:
    name: str
    description: str
    input_schema: dict
    executor: Callable[[dict, Callable], Any]


def _geocode(args: dict, get_json: Callable) -> dict:
    query = args.get("query") or args.get("address") or ""
    limit = int(args.get("limit", 5))
    params = {"q": query, "format": "json", "limit": limit}
    country = args.get("country")
    if country:
        params["countrycodes"] = country
    data = get_json(NOMINATIM_URL, params)
    results = []
    for d in (data or [])[:limit]:
        if "lat" not in d or "lon" not in d:
            continue
        entry = {
            "name": d.get("display_name"),
            "lat": float(d["lat"]),
            "lon": float(d["lon"]),
            "type": d.get("type"),
        }
        # bbox prête pour setMapExtent : 'minlon,minlat,maxlon,maxlat' (WGS84).
        # Nominatim renvoie boundingbox = [minlat, maxlat, minlon, maxlon].
        bb = d.get("boundingbox")
        if isinstance(bb, (list, tuple)) and len(bb) == 4:
            try:
                minlat, maxlat, minlon, maxlon = (float(x) for x in bb)
                entry["bbox"] = f"{minlon},{minlat},{maxlon},{maxlat}"
            except (TypeError, ValueError):
                entry["bbox"] = f"{entry['lon']},{entry['lat']}"
        else:
            entry["bbox"] = f"{entry['lon']},{entry['lat']}"
        results.append(entry)
    return {"query": query, "count": len(results), "results": results}


def _weather(args: dict, get_json: Callable) -> dict:
    lat = float(args["lat"])
    lon = float(args["lon"])
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,precipitation,wind_speed_10m,weather_code",
    }
    data = get_json(OPENMETEO_FORECAST, params)
    return {"lat": lat, "lon": lon, "current": data.get("current", {}),
            "units": data.get("current_units", {})}


def _elevation(args: dict, get_json: Callable) -> dict:
    lat = float(args["lat"])
    lon = float(args["lon"])
    data = get_json(OPENMETEO_ELEVATION, {"latitude": lat, "longitude": lon})
    elevations = data.get("elevation") or []
    return {"lat": lat, "lon": lon,
            "elevation_m": elevations[0] if elevations else None}


def _search_satellite(args: dict, get_json: Callable) -> dict:
    collection = args.get("collection", "sentinel-2-l2a")
    limit = int(args.get("limit", 5))
    params = {"collections": collection, "limit": limit}
    bbox = args.get("bbox")
    if isinstance(bbox, (list, tuple)):
        bbox = ",".join(str(x) for x in bbox)
    if bbox:
        params["bbox"] = bbox
    if args.get("datetime"):
        params["datetime"] = args["datetime"]
    data = get_json(EARTH_SEARCH_STAC, params)
    feats = (data or {}).get("features", []) or []
    items = []
    for f in feats[:limit]:
        props = f.get("properties", {}) or {}
        assets = f.get("assets", {}) or {}
        items.append({
            "id": f.get("id"),
            "datetime": props.get("datetime"),
            "cloud_cover": props.get("eo:cloud_cover"),
            "thumbnail": (assets.get("thumbnail", {}) or {}).get("href"),
            "visual": (assets.get("visual", {}) or {}).get("href"),
            "asset_keys": list(assets.keys()),
        })
    return {"collection": collection, "count": len(items), "items": items}


def _list_symbology_presets(args: dict, get_json: Callable) -> dict:
    try:
        from symbology_presets import list_presets  # type: ignore
    except ImportError:
        from .symbology_presets import list_presets  # type: ignore
    return {"presets": list_presets()}


def _list_data_sources(args: dict, get_json: Callable) -> dict:
    try:
        from data_catalog import list_sources  # type: ignore
    except ImportError:
        from .data_catalog import list_sources  # type: ignore
    sources = list_sources(args.get("category"))
    return {"count": len(sources), "sources": sources}


def _list_dossiers(args: dict, get_json: Callable) -> dict:
    try:
        from dossier_blueprint import list_dossiers  # type: ignore
    except ImportError:
        from .dossier_blueprint import list_dossiers  # type: ignore
    dossiers = list_dossiers()
    return {"count": len(dossiers), "dossiers": dossiers}


def _list_report_templates(args: dict, get_json: Callable) -> dict:
    try:
        from report_templates import list_templates  # type: ignore
    except ImportError:
        from .report_templates import list_templates  # type: ignore
    return {"templates": list_templates()}


def _generate_report(args: dict, get_json: Callable) -> dict:
    try:
        from report_templates import render_report, required_keys  # type: ignore
    except ImportError:
        from .report_templates import render_report, required_keys  # type: ignore
    template_id = args.get("template_id") or args.get("template") or ""
    context = args.get("context") or {}
    return {
        "template": template_id,
        "required_keys": sorted(required_keys(template_id)),
        "markdown": render_report(template_id, context),
    }


def _critique_layout(args: dict, get_json: Callable) -> dict:
    try:
        from vision_critique import (  # type: ignore
            build_critique_prompt, completeness_score, suggest_fixes)
    except ImportError:
        from .vision_critique import (  # type: ignore
            build_critique_prompt, completeness_score, suggest_fixes)
    intent = args.get("intent", "")
    layout_meta = args.get("layout_meta") or {}
    score = completeness_score(layout_meta)
    return {
        "score": score["score"],
        "missing": score["missing"],
        "fixes": suggest_fixes(layout_meta),
        "vlm_prompt": build_critique_prompt(intent, layout_meta),
    }


def _predict_trend(args: dict, get_json: Callable) -> dict:
    try:
        from predict_trend import linear_trend, project, classify_trend  # type: ignore
    except ImportError:
        from .predict_trend import linear_trend, project, classify_trend  # type: ignore
    points = [tuple(p) for p in (args.get("points") or [])]
    horizon = int(args.get("horizon", 3))
    tr = linear_trend(points)
    return {
        "trend": tr,
        "projection": project(points, horizon),
        "classification": classify_trend(tr["slope"]),
    }


def _parse_voice_intent(args: dict, get_json: Callable) -> dict:
    try:
        from voice_intents import parse_intent  # type: ignore
    except ImportError:
        from .voice_intents import parse_intent  # type: ignore
    return parse_intent(args.get("text", ""))


def _list_suitability_presets(args: dict, get_json: Callable) -> dict:
    try:
        from suitability_presets import list_presets  # type: ignore
    except ImportError:
        from .suitability_presets import list_presets  # type: ignore
    return {"presets": list_presets()}


def _generate_layer_style(args: dict, get_json: Callable) -> dict:
    """Genere un style QGIS (.qml) a partir d'une legende [{label,color,geometry}]."""
    try:
        from map_repro import legend_to_qml  # type: ignore
    except ImportError:
        from .map_repro import legend_to_qml  # type: ignore
    legend = args.get("legend") or []
    field = args.get("field", "classe")
    geometry = args.get("geometry")
    qml = legend_to_qml(legend, field=field, geometry=geometry)
    return {"qml": qml, "categories": len(legend), "field": field}


def _search_symbology(args: dict, get_json: Callable) -> dict:
    """Recherche dans la bibliotheque de symbologies institutionnelles (Kimi)."""
    try:
        import symbology_library as sl  # type: ignore
    except ImportError:
        from . import symbology_library as sl  # type: ignore
    query = (args.get("query") or "").strip()
    if query:
        return {"query": query, "results": sl.search_presets(query)}
    return {
        "by_institution": sl.list_by_institution(),
        "categories": sl.list_categories(),
    }


def _list_palettes(args: dict, get_json: Callable) -> dict:
    """Liste les palettes de couleurs + verifie l'accessibilite d'un couple (Kimi)."""
    try:
        import palettes as p  # type: ignore
    except ImportError:
        from . import palettes as p  # type: ignore
    palette_id = args.get("palette_id")
    if palette_id:
        return {"palette_id": palette_id, "colors": p.get_palette(palette_id)}
    pair = args.get("contrast_pair")
    if isinstance(pair, (list, tuple)) and len(pair) == 2:
        ratio = p.contrast_ratio(pair[0], pair[1])
        return {"pair": list(pair), "ratio": round(ratio, 2),
                "accessible": p.is_accessible(pair[0], pair[1])}
    return {"palettes": p.list_palettes()}


def _normalize_legend(args: dict, get_json: Callable) -> dict:
    """Normalise une legende heterogene (couleurs en hex #rrggbb) avant un style (Kimi)."""
    try:
        import legend_normalizer as ln  # type: ignore
    except ImportError:
        from . import legend_normalizer as ln  # type: ignore
    raw = args.get("legend") or []
    return {"legend": ln.normalize_legend(raw), "count": len(raw)}


def _validate_pipeline(args: dict, get_json: Callable) -> dict:
    """Valide un pipeline geospatial (cycles, IO, ordre, cout estime) (Kimi)."""
    try:
        import pipeline_engine as pe  # type: ignore
    except ImportError:
        from . import pipeline_engine as pe  # type: ignore
    pipeline = args.get("pipeline") or {}
    errors = pe.validate_pipeline(pipeline)
    out = {"valid": not errors, "errors": errors}
    if not errors:
        out["order"] = pe.topological_order(pipeline)
        out["cost"] = pe.estimate_cost(pipeline)
    return out


def _wikipedia(args: dict, get_json: Callable) -> dict:
    title = args.get("query") or args.get("title") or ""
    data = get_json(WIKIPEDIA_SUMMARY + urllib.parse.quote(title), {})
    urls = (data or {}).get("content_urls", {}) or {}
    return {
        "title": data.get("title"),
        "extract": data.get("extract"),
        "url": (urls.get("desktop", {}) or {}).get("page"),
    }




def _ask_user(args: dict, get_json: Callable) -> dict:
    """Outil natif : pose une question a l'utilisateur avec des options.

    Retourne un dict avec le flag `_ask_user_pause` pour que la boucle agentique
    s'interrompe et affiche un modal QCM au frontend.
    """
    question = str(args.get("question", "")).strip()
    options_raw = args.get("options", [])
    options = [str(o).strip() for o in options_raw if str(o).strip()]
    if not question:
        return {"error": "question manquante"}
    if not options or len(options) < 2:
        return {"error": "options doit contenir au moins 2 choix"}
    return {
        "_ask_user_pause": True,
        "question": question,
        "options": options,
    }

NATIVE_TOOLS: List[NativeTool] = [
    NativeTool(
        name="geocode",
        description=(
            "Geocoder une adresse ou un lieu en coordonnees (lat/lon) via "
            "OpenStreetMap/Nominatim. Utile pour localiser avant une analyse SIG."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Adresse ou lieu, ex: 'Toulouse, France'"},
                "country": {"type": "string", "description": "Code pays ISO2 optionnel, ex: 'fr'"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        executor=_geocode,
    ),
    NativeTool(
        name="weather",
        description="Meteo actuelle (temperature, precipitations, vent) a une position lat/lon via Open-Meteo.",
        input_schema={
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lon": {"type": "number"},
            },
            "required": ["lat", "lon"],
        },
        executor=_weather,
    ),
    NativeTool(
        name="elevation",
        description="Altitude (m) du terrain a une position lat/lon via Open-Meteo (Copernicus DEM).",
        input_schema={
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lon": {"type": "number"},
            },
            "required": ["lat", "lon"],
        },
        executor=_elevation,
    ),
    NativeTool(
        name="search_satellite_imagery",
        description=(
            "Rechercher des images satellite ouvertes via le catalogue STAC Earth "
            "Search (sans cle). Collections: 'sentinel-2-l2a' (optique), "
            "'sentinel-1-grd' (radar), 'landsat-c2-l2'. Filtrer par emprise (bbox) "
            "et periode (datetime). Renvoie id, date, couverture nuageuse, apercu."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "enum": ["sentinel-2-l2a", "sentinel-1-grd", "landsat-c2-l2"],
                    "default": "sentinel-2-l2a",
                },
                "bbox": {
                    "type": "string",
                    "description": "Emprise 'minlon,minlat,maxlon,maxlat' (WGS84)",
                },
                "datetime": {
                    "type": "string",
                    "description": "Periode ISO, ex: '2025-06-01/2025-06-30'",
                },
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["bbox"],
        },
        executor=_search_satellite,
    ),
    NativeTool(
        name="list_data_sources",
        description=(
            "Lister les sources cartographiques mondiales gratuites chargeables "
            "(fonds OSM/CARTO/ESRI, satellite, occupation du sol ESA WorldCover, "
            "IGN/Cadastre France...). Filtrer par 'category'. Enchainer avec "
            "addDataSource pour charger une source dans QGIS."
        ),
        input_schema={
            "type": "object",
            "properties": {"category": {"type": "string", "description": "ex: basemap, satellite, france, occupation_sol, relief"}},
        },
        executor=_list_data_sources,
    ),
    NativeTool(
        name="list_dossiers",
        description=(
            "Lister les dossiers territoriaux pre-assembles (urbanisme, risques, foret, "
            "environnement...). Chaque dossier charge un jeu de couches + symbologies en 1 appel "
            "via runDossier. Renvoie id, nom, description, nb d'etapes."
        ),
        input_schema={"type": "object", "properties": {}},
        executor=_list_dossiers,
    ),
    NativeTool(
        name="list_report_templates",
        description=(
            "Lister les gabarits de rapport de diagnostic territorial (vegetation, risques, "
            "urbanisme). A utiliser avec generate_report."
        ),
        input_schema={"type": "object", "properties": {}},
        executor=_list_report_templates,
    ),
    NativeTool(
        name="generate_report",
        description=(
            "Generer un rapport markdown de diagnostic a partir d'un gabarit et d'un contexte "
            "(ex: {commune, date, ndvi_moyen}). Renvoie le markdown + les cles requises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "template_id": {"type": "string", "description": "ex: diagnostic_vegetation"},
                "context": {"type": "object", "description": "valeurs des placeholders"},
            },
            "required": ["template_id"],
        },
        executor=_generate_report,
    ),
    NativeTool(
        name="critique_layout",
        description=(
            "Boucle vision : evaluer une mise en page (score de completude + elements "
            "manquants + correctifs) et obtenir le prompt a envoyer a un VLM pour critiquer "
            "le rendu. layout_meta ex: {title, map:{extent:[...]}, legend, scalebar, north}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "intent": {"type": "string", "description": "intention de la carte"},
                "layout_meta": {"type": "object"},
            },
            "required": ["layout_meta"],
        },
        executor=_critique_layout,
    ),
    NativeTool(
        name="predict_trend",
        description=(
            "Projeter une tendance a partir d'une serie temporelle d'indice (ex: dNDVI). "
            "points=[[t,valeur],...]. Renvoie pente/r2, projection et classification "
            "(degradation/stable/amelioration)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "points": {"type": "array", "items": {"type": "array"}},
                "horizon": {"type": "integer"},
            },
            "required": ["points"],
        },
        executor=_predict_trend,
    ),
    NativeTool(
        name="parse_voice_intent",
        description=(
            "Interpreter une phrase utilisateur en action cartographique structuree "
            "(add_basemap, compute_ndvi, buffer, load_satellite, export_layout...)."
        ),
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        executor=_parse_voice_intent,
    ),
    NativeTool(
        name="list_suitability_presets",
        description=(
            "Lister les presets de criteres ponderes pour l'analyse de site "
            "(panneaux_solaires, zone_constructible, risque_erosion)."
        ),
        input_schema={"type": "object", "properties": {}},
        executor=_list_suitability_presets,
    ),
    NativeTool(
        name="list_symbology_presets",
        description=(
            "Lister les symbologies institutionnelles francaises disponibles (ONF, "
            "IGN BD Foret, PLU, Cadastre, Corine Land Cover, PPRi, Natura 2000). "
            "Renvoie id, institution, champ attendu et nb de categories. A enchainer "
            "avec applySymbologyPreset pour appliquer."
        ),
        input_schema={"type": "object", "properties": {}},
        executor=_list_symbology_presets,
    ),
    NativeTool(
        name="generate_layer_style",
        description=(
            "Generer un style QGIS (.qml categorise) a partir d'une legende. "
            "A enchainer avec applyQmlStyle pour reproduire la symbologie d'une carte. "
            "Chaque entree de legende: {label, color (hex), geometry (polygon|line|point)}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "legend": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "color": {"type": "string"},
                            "geometry": {"type": "string"},
                        },
                        "required": ["label", "color"],
                    },
                },
                "field": {"type": "string", "default": "classe"},
                "geometry": {"type": "string"},
            },
            "required": ["legend"],
        },
        executor=_generate_layer_style,
    ),
    NativeTool(
        name="search_symbology",
        description=(
            "Rechercher dans la bibliotheque etendue de symbologies institutionnelles "
            "(>40 presets ONF, IGN, PLU, Cadastre...). Sans 'query' renvoie le catalogue "
            "groupe par institution + categories. A enchainer avec applySymbologyPreset."
        ),
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "mot-cle, ex: 'foret', 'risque', 'plu'"}},
        },
        executor=_search_symbology,
    ),
    NativeTool(
        name="list_palettes",
        description=(
            "Lister les palettes de couleurs cartographiques. Avec 'palette_id' renvoie "
            "les couleurs hex. Avec 'contrast_pair' [hex1,hex2] verifie le ratio de "
            "contraste WCAG (accessibilite des cartes)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "palette_id": {"type": "string"},
                "contrast_pair": {"type": "array", "items": {"type": "string"}},
            },
        },
        executor=_list_palettes,
    ),
    NativeTool(
        name="normalize_legend",
        description=(
            "Normaliser une legende heterogene (noms de couleurs, rgb(), #abc) en hex "
            "#rrggbb propres. A utiliser AVANT generate_layer_style pour fiabiliser le style."
        ),
        input_schema={
            "type": "object",
            "properties": {"legend": {"type": "array", "items": {"type": "object"}}},
            "required": ["legend"],
        },
        executor=_normalize_legend,
    ),
    NativeTool(
        name="validate_pipeline",
        description=(
            "Valider un pipeline geospatial (detecte cycles, entrees/sorties manquantes), "
            "calculer l'ordre topologique d'execution et estimer le cout. pipeline = "
            "{steps: [{id, op, inputs, outputs}, ...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {"pipeline": {"type": "object"}},
            "required": ["pipeline"],
        },
        executor=_validate_pipeline,
    ),
    NativeTool(
        name="ask_user",
        description=(
            "Poser une question a l'utilisateur avec plusieurs options de reponse. "
            "Le systeme affiche un modal QCM et attend le choix. Utile pour clarifier "
            "une intention (ex: PSG simple vs complet) ou confirmer une action. "
            'question="..." options=["A", "B", "C"].'
        ),
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Question a poser a l'utilisateur"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Liste des options de reponse (min 2)",
                },
            },
            "required": ["question", "options"],
        },
        executor=_ask_user,
    ),
    NativeTool(
        name="wikipedia",
        description="Rechercher un resume factuel sur Wikipedia (FR) pour ancrer une reponse.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Sujet ou titre d'article"}},
            "required": ["query"],
        },
        executor=_wikipedia,
    ),
]


def get_native_tool(name: str) -> Optional[NativeTool]:
    return next((t for t in NATIVE_TOOLS if t.name == name), None)


def native_tool_names() -> List[str]:
    return [t.name for t in NATIVE_TOOLS]


def to_openai_tools() -> List[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in NATIVE_TOOLS
    ]


def execute_native_tool(name: str, arguments: dict, get_json: Callable = None) -> str:
    """Execute un outil natif et retourne un texte JSON. `get_json` injectable (tests)."""
    tool = get_native_tool(name)
    if tool is None:
        raise ValueError(f"Outil natif inconnu : {name}")
    result = tool.executor(arguments or {}, get_json or _default_get_json)
    return json.dumps(result, ensure_ascii=False)
