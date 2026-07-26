# -*- coding: utf-8 -*-
"""
QGISIA+ MCP Server.

Expose les outils QGIS du plugin via le protocole Model Context Protocol
(https://modelcontextprotocol.io) pour permettre a des clients externes
(Claude Desktop, Cursor, Cline, Continue) d'appeler les outils SIG.

Architecture :
    Client MCP (Claude Desktop)  <-- stdio JSON-RPC -->  Ce serveur
                                                                |
                                                     HTTP POST  v
                                                  /api/qgis/* du plugin QGIS
                                                  (dev_server.py port 8157)

Dependances :
    pip install mcp httpx

Usage CLI (stdio) :
    python -m QGISIA2.mcp_server

Configuration Claude Desktop (`claude_desktop_config.json`) :
    {
      "mcpServers": {
        "qgisia-plus": {
          "command": "python",
          "args": ["-m", "QGISIA2.mcp_server"],
          "env": { "QGISIA_BRIDGE_URL": "http://localhost:8157" }
        }
      }
    }
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

# Default bridge URL (overridable via env var)
DEFAULT_BRIDGE_URL = os.environ.get("QGISIA_BRIDGE_URL", "http://localhost:8157")


# ─── Catalogue des outils exposes en MCP ──────────────────────────────────────


@dataclass
class McpToolSpec:
    """
    Descripteur d'outil MCP. Le mapping `endpoint` indique l'endpoint HTTP
    correspondant cote bridge QGIS, et `payload_builder` transforme les
    arguments MCP vers le payload attendu par le bridge.
    """
    name: str
    description: str
    input_schema: dict[str, Any]
    endpoint: str
    payload_builder: Callable[[dict[str, Any]], dict[str, Any]]


def _options_payload(args: dict[str, Any]) -> dict[str, Any]:
    """La majorite des slots @BridgeSlot acceptent un seul JSON 'options'."""
    return {"options": json.dumps(args)}


def _direct_payload(args: dict[str, Any]) -> dict[str, Any]:
    """Endpoints de mutation carto : les champs sont lus directement dans le body."""
    return dict(args)


TOOL_CATALOG: list[McpToolSpec] = [
    McpToolSpec(
        name="loadHubEauStations",
        description=(
            "Charger des stations Hub'Eau (qualite eau, hydrometrie, piezometrie) "
            "comme couche QGIS. Departement FR ou code commune."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "station_type": {"type": "string", "enum": ["quality", "hydro", "piezo"]},
                "department": {"type": "string", "description": "Code dept FR (ex: '31')"},
                "commune": {"type": "string"},
                "limit": {"type": "integer", "default": 100},
                "layerName": {"type": "string"},
            },
            "required": ["station_type"],
        },
        endpoint="/api/qgis/loadHubEauStations",
        payload_builder=_options_payload,
    ),
    McpToolSpec(
        name="loadGbifOccurrences",
        description=(
            "Charger des occurrences d'especes GBIF (biodiversite mondiale) "
            "comme couche QGIS de points."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "scientificName": {"type": "string"},
                "country": {"type": "string", "default": "FR"},
                "limit": {"type": "integer", "default": 100},
                "layerName": {"type": "string"},
            },
            "required": ["scientificName"],
        },
        endpoint="/api/qgis/loadGbifOccurrences",
        payload_builder=_options_payload,
    ),
    McpToolSpec(
        name="loadDvfTransactions",
        description=(
            "Charger des transactions immobilieres DVF (Demandes de Valeurs "
            "Foncieres) comme couche QGIS."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "commune": {"type": "string"},
                "department": {"type": "string"},
                "year": {"type": "integer"},
                "mutationType": {"type": "string"},
                "layerName": {"type": "string"},
            },
        },
        endpoint="/api/qgis/loadDvfTransactions",
        payload_builder=_options_payload,
    ),
    McpToolSpec(
        name="segmentRasterWithSAM",
        description=(
            "Segmenter un raster (orthophoto, image satellite) avec Segment "
            "Anything (SAM). Mode 'automatic' ou 'text_prompt' (ex: 'trees', "
            "'buildings', 'water'). Necessite samgeo + torch cote backend."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "rasterPath": {"type": "string"},
                "outputGeojson": {"type": "string"},
                "mode": {"type": "string", "enum": ["automatic", "text_prompt"]},
                "textPrompt": {"type": "string"},
                "model": {"type": "string", "enum": ["vit_h", "vit_l", "vit_b"]},
            },
            "required": ["rasterPath", "outputGeojson"],
        },
        endpoint="/api/qgis/segmentRasterWithSAM",
        payload_builder=_options_payload,
    ),
    McpToolSpec(
        name="forecastWeatherWithEarth2",
        description=(
            "Prevision meteo globale via NVIDIA Earth-2 Studio (FourCastNet, "
            "Pangu, AIFS, GraphCast). Sortie GeoTIFF par variable."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "outputDir": {"type": "string"},
                "model": {"type": "string", "enum": ["fcn", "pangu", "aifs", "graphcast"]},
                "initTime": {"type": "string"},
                "leadHours": {"type": "integer"},
                "variables": {"type": "array", "items": {"type": "string"}},
                "layerPrefix": {"type": "string"},
            },
            "required": ["outputDir"],
        },
        endpoint="/api/qgis/forecastWeatherWithEarth2",
        payload_builder=_options_payload,
    ),
    McpToolSpec(
        name="exportProjectReport",
        description=(
            "Exporter un rapport SIG du projet QGIS courant en PDF ou DOCX, "
            "incluant snapshot carte, tableau couches et sections personnalisees."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "outputPath": {"type": "string"},
                "format": {"type": "string", "enum": ["pdf", "docx"]},
                "author": {"type": "string"},
                "subtitle": {"type": "string"},
                "includeLayers": {"type": "boolean"},
                "includeMap": {"type": "boolean"},
            },
            "required": ["title", "outputPath"],
        },
        endpoint="/api/qgis/exportProjectReport",
        payload_builder=_options_payload,
    ),
    McpToolSpec(
        name="getLayersList",
        description="Lister les couches du projet QGIS courant.",
        input_schema={"type": "object", "properties": {}},
        endpoint="/api/qgis/getLayersList",
        payload_builder=lambda _args: {},
    ),
    McpToolSpec(
        name="runScript",
        description=(
            "Executer un script PyQGIS arbitraire dans le contexte du projet. "
            "DANGER : aucune validation. Reserve aux power users."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "Code PyQGIS a executer"},
            },
            "required": ["script"],
        },
        endpoint="/api/qgis/runScript",
        payload_builder=lambda args: {"script": args.get("script", "")},
    ),
    McpToolSpec(
        name="setLayerVisibility",
        description="Afficher ou masquer une couche du projet QGIS.",
        input_schema={
            "type": "object",
            "properties": {
                "layerId": {"type": "string"},
                "visible": {"type": "boolean", "default": True},
            },
            "required": ["layerId", "visible"],
        },
        endpoint="/api/qgis/setLayerVisibility",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="setLayerOpacity",
        description="Regler l'opacite d'une couche (0.0 transparent a 1.0 opaque).",
        input_schema={
            "type": "object",
            "properties": {
                "layerId": {"type": "string"},
                "opacity": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["layerId", "opacity"],
        },
        endpoint="/api/qgis/setLayerOpacity",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="zoomToLayer",
        description="Zoomer le canvas sur l'emprise d'une couche. NE PAS utiliser sur un fond de carte mondial (OSM) : cela affiche le monde entier. Pour cadrer sur un lieu, utilise setMapExtent avec la bbox du géocodage.",
        input_schema={
            "type": "object",
            "properties": {"layerId": {"type": "string"}},
            "required": ["layerId"],
        },
        endpoint="/api/qgis/zoomToLayer",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="setMapExtent",
        description="Cadrer la vue sur une emprise géographique WGS84. INDISPENSABLE après un géocodage pour centrer la carte sur un lieu (ville, commune). Passe la bbox renvoyée par geocode.",
        input_schema={
            "type": "object",
            "properties": {
                "bbox": {
                    "type": "string",
                    "description": "Emprise 'minlon,minlat,maxlon,maxlat' ou point 'lon,lat' (WGS84). Utilise la valeur 'bbox' renvoyée par l'outil geocode.",
                },
            },
            "required": ["bbox"],
        },
        endpoint="/api/qgis/setMapExtent",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="renameLayer",
        description="Renommer une couche avec un nom clair et descriptif (ex: 'Fond OpenStreetMap', 'NDVI 2024'). Ne nomme PAS une couche d'après le lieu seul.",
        input_schema={
            "type": "object",
            "properties": {
                "layerId": {"type": "string"},
                "name": {"type": "string", "description": "Nouveau nom descriptif"},
            },
            "required": ["layerId", "name"],
        },
        endpoint="/api/qgis/renameLayer",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="setLayerGroup",
        description="Ranger une couche dans un groupe nommé du panneau (créé si absent). Organise l'arbre des couches de façon pro : ex. groupes 'Fonds de carte', 'Données', 'Analyses', 'Résultats'.",
        input_schema={
            "type": "object",
            "properties": {
                "layerId": {"type": "string"},
                "groupName": {"type": "string", "description": "Nom du groupe (ex: 'Fonds de carte')"},
            },
            "required": ["layerId", "groupName"],
        },
        endpoint="/api/qgis/setLayerGroup",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="filterLayer",
        description="Appliquer un filtre attributaire (subset string SQL) sur une couche vectorielle.",
        input_schema={
            "type": "object",
            "properties": {
                "layerId": {"type": "string"},
                "subsetString": {"type": "string", "description": "Expression SQL, ex: \"type = 'foret'\""},
            },
            "required": ["layerId", "subsetString"],
        },
        endpoint="/api/qgis/filterLayer",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="reprojectLayer",
        description="Reprojeter une couche vers un CRS cible (ex: 'EPSG:2154').",
        input_schema={
            "type": "object",
            "properties": {
                "layerId": {"type": "string"},
                "targetCrs": {"type": "string", "description": "Code EPSG, ex: 'EPSG:2154'"},
            },
            "required": ["layerId", "targetCrs"],
        },
        endpoint="/api/qgis/reprojectLayer",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="applyQmlStyle",
        description=(
            "Appliquer un style QGIS (.qml fourni en chaine XML) a une couche. "
            "Utilise pour reproduire la symbologie d'une carte (legende -> QML)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "layerId": {"type": "string"},
                "qml": {"type": "string", "description": "Contenu XML du style QML categorise"},
            },
            "required": ["layerId", "qml"],
        },
        endpoint="/api/qgis/applyQmlStyle",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="applySymbologyPreset",
        description=(
            "Appliquer une symbologie institutionnelle francaise (preset) a une couche : "
            "ONF, IGN BD Foret, PLU, Cadastre, Corine Land Cover, PPRi, Natura 2000. "
            "Voir list_symbology_presets pour les id disponibles. 'field' surcharge le "
            "champ a categoriser (defaut = champ du preset)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "layerId": {"type": "string"},
                "presetId": {"type": "string", "description": "ex: 'onf-peuplements', 'plu-zonage'"},
                "field": {"type": "string", "description": "Champ a categoriser (optionnel)"},
            },
            "required": ["layerId", "presetId"],
        },
        endpoint="/api/qgis/applySymbologyPreset",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="list_data_sources",
        description=(
            "Lister les sources cartographiques mondiales gratuites du catalogue "
            "(fonds, satellite, occupation du sol, IGN/Cadastre France...). "
            "Filtre optionnel 'category'."
        ),
        input_schema={
            "type": "object",
            "properties": {"category": {"type": "string"}},
        },
        endpoint="/api/qgis/listDataSources",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="addDataSource",
        description=(
            "Charger une source du catalogue mondial dans QGIS (fond OSM/CARTO/ESRI, "
            "satellite, ESA WorldCover, IGN/Cadastre...). Voir list_data_sources pour les id."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "sourceId": {"type": "string", "description": "ex: 'osm-standard', 'esri-world-imagery', 'ign-cadastre'"},
                "name": {"type": "string", "description": "Nom de couche optionnel"},
            },
            "required": ["sourceId"],
        },
        endpoint="/api/qgis/addDataSource",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="addRemoteRaster",
        description=(
            "Charger un raster distant (COG https/S3) dans QGIS, ex: une image satellite "
            "Sentinel/Landsat trouvee via search_satellite_imagery (href d'asset .tif)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL du COG (https://....tif) ou s3://..."},
                "layerName": {"type": "string"},
            },
            "required": ["url"],
        },
        endpoint="/api/qgis/addRemoteRaster",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="loadSatelliteBands",
        description=(
            "Charger des bandes d'une image satellite Sentinel-2 (STAC Earth Search) sur "
            "une emprise bbox, image la moins nuageuse. bands ex ['RED','NIR']. A enchainer "
            "avec computeSpectralIndex pour un NDVI sur vrai Sentinel."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bbox": {"type": "string", "description": "minlon,minlat,maxlon,maxlat (WGS84)"},
                "collection": {"type": "string", "default": "sentinel-2-l2a"},
                "bands": {"type": "array", "items": {"type": "string"}},
                "datetime": {"type": "string", "description": "Periode ISO ex 2025-06-01/2025-06-30"},
            },
            "required": ["bbox"],
        },
        endpoint="/api/qgis/loadSatelliteBands",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="list_dossiers",
        description=(
            "Lister les dossiers territoriaux pre-assembles (urbanisme, risques, foret, "
            "environnement). Chacun charge un jeu de couches + symbologies via runDossier."
        ),
        input_schema={"type": "object", "properties": {}},
        endpoint="/api/qgis/listDossiers",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="runDossier",
        description=(
            "Derouler un dossier territorial en 1 appel : charge les couches du catalogue "
            "et applique les symbologies institutionnelles. id via list_dossiers "
            "(ex: 'urbanisme', 'risques', 'foret', 'environnement')."
        ),
        input_schema={
            "type": "object",
            "properties": {"dossierId": {"type": "string"}},
            "required": ["dossierId"],
        },
        endpoint="/api/qgis/runDossier",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="computeSpectralIndex",
        description=(
            "Calculer un indice spectral (ndvi, ndwi, ndbi, nbr, evi) sur un raster "
            "multibande (Sentinel/Landsat) et le styliser automatiquement. 'bandMap' "
            "mappe les bandes vers les refs QgsRasterCalculator (ex: {\"NIR\":\"couche@8\","
            "\"RED\":\"couche@4\"})."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "layerId": {"type": "string"},
                "indexId": {"type": "string", "enum": ["ndvi", "ndwi", "ndbi", "nbr", "evi"]},
                "bandMap": {"type": "object"},
                "outputPath": {"type": "string"},
            },
            "required": ["layerId", "indexId", "bandMap"],
        },
        endpoint="/api/qgis/computeSpectralIndex",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="computeRasterDifference",
        description=(
            "Difference de deux rasters mono-bande (ex: NDVI_t2 - NDVI_t1) pour la "
            "detection de changement / le monitoring temporel. Auto-style diverging."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "layerA": {"type": "string", "description": "Raster recent (t2)"},
                "layerB": {"type": "string", "description": "Raster ancien (t1)"},
                "outputPath": {"type": "string"},
            },
            "required": ["layerA", "layerB"],
        },
        endpoint="/api/qgis/computeRasterDifference",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="zonalStatistics",
        description=(
            "Statistiques zonales d'un raster par entite d'une couche de polygones "
            "(ex: NDVI moyen par parcelle). Ajoute des champs mean/min/max/count a la couche."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "rasterId": {"type": "string"},
                "polygonId": {"type": "string"},
                "prefix": {"type": "string", "description": "Prefixe des champs (defaut zs_)"},
            },
            "required": ["rasterId", "polygonId"],
        },
        endpoint="/api/qgis/zonalStatistics",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="bufferLayer",
        description=(
            "Creer une zone tampon (buffer) autour des entites d'une couche vectorielle "
            "(ex: buffer de 500 m autour des ecoles). Distance dans l'unite du CRS."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "layerId": {"type": "string"},
                "distance": {"type": "number"},
                "outputName": {"type": "string"},
            },
            "required": ["layerId", "distance"],
        },
        endpoint="/api/qgis/bufferLayer",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="saveVectorLayer",
        description=(
            "Exporter une couche vectorielle vers un fichier livrable : GeoPackage (GPKG), "
            "GeoJSON ou ESRI Shapefile."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "layerId": {"type": "string"},
                "outputPath": {"type": "string"},
                "driver": {"type": "string", "enum": ["GPKG", "GeoJSON", "ESRI Shapefile"]},
            },
            "required": ["layerId", "outputPath"],
        },
        endpoint="/api/qgis/saveVectorLayer",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="exportPrintLayout",
        description=(
            "Generer une planche cartographique professionnelle (titre, carte, legende, "
            "echelle) des couches affichees et l'exporter en PNG ou PDF."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "outputPath": {"type": "string"},
                "format": {"type": "string", "enum": ["png", "pdf"]},
                "template": {
                    "type": "string",
                    "enum": ["a4_portrait_simple", "a4_paysage_pro", "a3_paysage_atlas"],
                    "description": "Gabarit de mise en page (optionnel)",
                },
            },
            "required": ["outputPath"],
        },
        endpoint="/api/qgis/exportPrintLayout",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="exportLayoutSpec",
        description=(
            "Exporter une planche depuis une specification explicite d'elements positionnes "
            "(mm) : spec = {page_size, orientation, elements:[{type,x,y,width,height}]}. "
            "type in map/title/legend/scalebar/north/text/image."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "outputPath": {"type": "string"},
                "format": {"type": "string", "enum": ["png", "pdf"]},
                "spec": {"type": "object"},
            },
            "required": ["outputPath", "spec"],
        },
        endpoint="/api/qgis/exportLayoutSpec",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="classifyRaster",
        description=(
            "Appliquer une classification thematique a un raster continu : "
            "'ndvi_vegetation', 'dnbr_severite', 'pente_degres' (style discret colore)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "layerId": {"type": "string"},
                "schemeId": {"type": "string", "enum": ["ndvi_vegetation", "dnbr_severite", "pente_degres"]},
            },
            "required": ["layerId", "schemeId"],
        },
        endpoint="/api/qgis/classifyRaster",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="classifyChange",
        description=(
            "Styliser une carte de changement (dNDVI/dNBR de computeRasterDifference) en "
            "classes de severite : 'dndvi' (perte/gain de vegetation) ou 'dnbr_feu' (USGS)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "layerId": {"type": "string"},
                "schemeId": {"type": "string", "enum": ["dndvi", "dnbr_feu"]},
            },
            "required": ["layerId", "schemeId"],
        },
        endpoint="/api/qgis/classifyChange",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="exportAtlas",
        description=(
            "Generer un atlas PDF multi-pages (1 page par entite d'une couche de couverture). "
            "atlasId optionnel ('communes_atlas','parcelles_atlas'); pageField nomme les pages."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "coverageId": {"type": "string", "description": "couche vecteur de couverture"},
                "outputPath": {"type": "string"},
                "atlasId": {"type": "string"},
                "pageField": {"type": "string"},
            },
            "required": ["coverageId", "outputPath"],
        },
        endpoint="/api/qgis/exportAtlas",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="suitabilityAnalysis",
        description=(
            "Carte d'aptitude (site selection) : somme ponderee de rasters criteres. "
            "criteria = [{layer, weight, invert?}] (invert pour les criteres defavorables)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "criteria": {"type": "array", "items": {"type": "object"}},
                "outputPath": {"type": "string"},
            },
            "required": ["criteria"],
        },
        endpoint="/api/qgis/suitabilityAnalysis",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="hotspotAnalysis",
        description=(
            "Carte de chaleur (densite de noyau) d'une couche de points = hotspots. "
            "radius dans l'unite du CRS (auto si 0)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "pointId": {"type": "string"},
                "radius": {"type": "number"},
                "outputPath": {"type": "string"},
            },
            "required": ["pointId"],
        },
        endpoint="/api/qgis/hotspotAnalysis",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="computeTerrain",
        description=(
            "Analyse de terrain depuis un MNT : 'slope' (pente), 'aspect' (exposition), "
            "'hillshade' (ombrage), 'ruggedness' (rugosite). Filtres QGIS natifs."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "demId": {"type": "string"},
                "analysis": {"type": "string", "enum": ["slope", "aspect", "hillshade", "ruggedness"]},
                "outputPath": {"type": "string"},
            },
            "required": ["demId", "analysis"],
        },
        endpoint="/api/qgis/computeTerrain",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="clusterPoints",
        description=(
            "Clustering DBSCAN d'une couche de points (ajoute un champ 'cluster', -1=bruit). "
            "eps en unite du CRS (auto si 0), minPts taille minimale d'un cluster."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "pointId": {"type": "string"},
                "eps": {"type": "number"},
                "minPts": {"type": "integer"},
            },
            "required": ["pointId"],
        },
        endpoint="/api/qgis/clusterPoints",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="renderMapView",
        description=(
            "Rendre la vue carte courante en image PNG (pour la boucle vision : faire "
            "critiquer le rendu par un VLM puis auto-corriger)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "outputPath": {"type": "string"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
            },
            "required": ["outputPath"],
        },
        endpoint="/api/qgis/renderMapView",
        payload_builder=_direct_payload,
    ),
    # ── Outils natifs (en-process, sans bridge QGIS) ──────────────────────────
    # IMPLÉMENTÉ PAR DEVIN CLI (Cognition AI) — Superviseur : Claude Code 4.8 — 2026-06-08
    McpToolSpec(
        name="predictTrend",
        description=(
            "Projeter une tendance temporelle sur une série d'indices (ex: dNDVI). "
            "points=[[t,valeur],...]. Renvoie pente, r², projection et classification "
            "(degradation/stable/amelioration). Utile pour anticiper déforestation, "
            "artificialisation, inondation."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "points": {
                    "type": "array",
                    "items": {"type": "array"},
                    "description": "Série [[t, valeur], ...] (t=indice temps, ex: 0,1,2,...)",
                },
                "horizon": {
                    "type": "integer",
                    "default": 3,
                    "description": "Nombre de pas de temps à projeter",
                },
            },
            "required": ["points"],
        },
        endpoint="/api/native/predict_trend",
        payload_builder=_direct_payload,
    ),
    McpToolSpec(
        name="parseVoiceIntent",
        description=(
            "Interpréter une phrase utilisateur en action cartographique structurée. "
            "Ex: 'Ajoute un fond de carte' → {action: add_basemap}. "
            "Actions reconnues: add_basemap, compute_ndvi, buffer, load_satellite, "
            "export_layout. À enchaîner avec l'outil correspondant."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Phrase utilisateur en français ou anglais",
                },
            },
            "required": ["text"],
        },
        endpoint="/api/native/parse_voice_intent",
        payload_builder=_direct_payload,
    ),
]


def get_tool(name: str) -> Optional[McpToolSpec]:
    return next((t for t in TOOL_CATALOG if t.name == name), None)


# ─── Pont HTTP vers le bridge QGIS ────────────────────────────────────────────


class BridgeUnavailableError(RuntimeError):
    """Levee si le bridge QGIS HTTP est inaccessible."""


async def call_bridge(
    endpoint: str,
    payload: dict[str, Any],
    *,
    bridge_url: str = DEFAULT_BRIDGE_URL,
    timeout: float = 60.0,
    http_client: Any = None,
) -> str:
    """
    Appelle le bridge HTTP QGIS et retourne le texte de reponse.

    `http_client` permet l'injection de dependance pour les tests (un mock
    avec methode async post()).
    """
    url = f"{bridge_url.rstrip('/')}{endpoint}"
    if http_client is not None:
        client = http_client
        owns_client = False
    else:
        try:
            import httpx  # type: ignore
        except ImportError as e:
            raise BridgeUnavailableError(
                f"httpx requis pour le serveur MCP : {e}. "
                "Installe via 'pip install httpx mcp'.",
            ) from e
        client = httpx.AsyncClient(timeout=timeout)
        owns_client = True

    try:
        resp = await client.post(url, json=payload)
        if hasattr(resp, "raise_for_status"):
            resp.raise_for_status()
        return resp.text if hasattr(resp, "text") else str(resp)
    finally:
        if owns_client:
            close = getattr(client, "aclose", None)
            if close is not None:
                await close()


# ─── Dispatch MCP ─────────────────────────────────────────────────────────────


async def dispatch_tool_call(
    name: str,
    arguments: dict[str, Any],
    *,
    bridge_url: str = DEFAULT_BRIDGE_URL,
    http_client: Any = None,
) -> str:
    """
    Resout un appel d'outil MCP : valide le nom, construit le payload,
    appelle le bridge HTTP, retourne le texte resultat.

    Pure fonction testable sans le SDK MCP.
    """
    spec = get_tool(name)
    if spec is None:
        raise ValueError(f"Outil MCP inconnu : {name}")

    payload = spec.payload_builder(arguments or {})
    return await call_bridge(
        spec.endpoint,
        payload,
        bridge_url=bridge_url,
        http_client=http_client,
    )


def list_tool_specs() -> list[dict[str, Any]]:
    """Format JSON serialisable du catalogue (pour debug et tests)."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.input_schema,
            "endpoint": t.endpoint,
        }
        for t in TOOL_CATALOG
    ]


# ─── Lancement du serveur MCP stdio ───────────────────────────────────────────


def run_stdio_server() -> None:
    """
    Boucle principale : initialise le serveur MCP officiel et le lance
    en stdio. Bloquant. Importe le SDK 'mcp' uniquement ici pour ne pas
    casser l'import du module quand le SDK n'est pas installe (tests).
    """
    try:
        import asyncio
        from mcp.server import Server  # type: ignore
        from mcp.server.stdio import stdio_server  # type: ignore
        from mcp.types import TextContent, Tool  # type: ignore
    except ImportError as e:
        raise BridgeUnavailableError(
            f"SDK 'mcp' non installe : {e}. Installe via 'pip install mcp'.",
        ) from e

    server: Any = Server("qgisia-plus")

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name=spec.name,
                description=spec.description,
                inputSchema=spec.input_schema,
            )
            for spec in TOOL_CATALOG
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            text = await dispatch_tool_call(name, arguments or {})
            return [TextContent(type="text", text=text)]
        except Exception as e:  # noqa: BLE001
            return [TextContent(type="text", text=f"Erreur : {e}")]

    async def _main() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    run_stdio_server()
