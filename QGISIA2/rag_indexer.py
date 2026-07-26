# -*- coding: utf-8 -*-
"""
QGISIA+ — Indexeur RAG PyQGIS (Sprint 3).

Indexe automatiquement :
1. Documentation PyQGIS intégrée (base de connaissance statique)
2. Couches du projet QGIS courant (métadonnées + schéma)
3. Pages web / docs externes via URL
4. Notes utilisateur

Compatible Python 3.9+, sans dépendance QGIS directe dans ce module.
L'indexation QGIS se fait via les données passées en paramètre.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .rag_store import RAGStore, get_store

PLUGIN_DIR = Path(__file__).parent


# ── Base de connaissances PyQGIS intégrée ─────────────────────────────────────

PYQGIS_KNOWLEDGE_BASE: List[Dict[str, Any]] = [
    {
        "title": "Accéder aux couches du projet",
        "content": """
Accéder aux couches dans QGIS avec PyQGIS :

# Toutes les couches
layers = QgsProject.instance().mapLayers()

# Couche par nom
layer = QgsProject.instance().mapLayersByName("nom_couche")[0]

# Couche active dans l'interface
layer = iface.activeLayer()

# Itérer sur les entités
for feature in layer.getFeatures():
    geom = feature.geometry()
    attrs = feature.attributes()
    print(feature["champ_nom"])
""",
        "tags": ["couches", "projet", "QgsProject", "layer"],
    },
    {
        "title": "Reprojection et CRS Lambert 93",
        "content": """
Reprojection d'une couche en Lambert 93 (EPSG:2154) — standard France :

from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject

# Définir le CRS cible
crs_lambert = QgsCoordinateReferenceSystem("EPSG:2154")

# Reprojeter via processing
import processing
result = processing.run("native:reprojectlayer", {
    'INPUT': layer,
    'TARGET_CRS': QgsCoordinateReferenceSystem('EPSG:2154'),
    'OUTPUT': 'memory:'
})
reprojected = result['OUTPUT']

# Vérifier le CRS d'une couche
print(layer.crs().authid())  # ex: EPSG:4326
""",
        "tags": ["crs", "reprojection", "lambert93", "EPSG:2154", "france"],
    },
    {
        "title": "Buffer / Zone tampon",
        "content": """
Créer une zone tampon (buffer) avec PyQGIS :

import processing

# Buffer simple en mètres (couche projetée)
result = processing.run("native:buffer", {
    'INPUT': layer,
    'DISTANCE': 100,        # 100 mètres
    'SEGMENTS': 5,
    'END_CAP_STYLE': 0,
    'JOIN_STYLE': 0,
    'MITER_LIMIT': 2,
    'DISSOLVE': False,
    'OUTPUT': 'memory:'
})
buffer_layer = result['OUTPUT']
QgsProject.instance().addMapLayer(buffer_layer)
iface.messageBar().pushMessage("Buffer", "Zone tampon créée", level=0)
""",
        "tags": ["buffer", "zone tampon", "processing", "analyse spatiale"],
    },
    {
        "title": "Intersection et jointure spatiale",
        "content": """
Intersection de deux couches vecteur :

import processing

result = processing.run("native:intersection", {
    'INPUT': layer1,
    'OVERLAY': layer2,
    'INPUT_FIELDS': [],
    'OVERLAY_FIELDS': [],
    'OUTPUT': 'memory:'
})
intersection = result['OUTPUT']

# Jointure spatiale (spatial join)
result_join = processing.run("native:joinattributesbylocation", {
    'INPUT': layer_points,
    'JOIN': layer_polygons,
    'PREDICATE': [0],  # 0=intersects
    'JOIN_FIELDS': [],
    'METHOD': 0,
    'DISCARD_NONMATCHING': False,
    'OUTPUT': 'memory:'
})
""",
        "tags": ["intersection", "jointure", "jointure spatiale", "overlay"],
    },
    {
        "title": "Statistiques zonales raster",
        "content": """
Calculer des statistiques zonales (valeur raster dans des polygones) :

import processing

result = processing.run("native:zonalstatisticsfb", {
    'INPUT': vector_layer,       # couche polygones
    'INPUT_RASTER': raster_layer,
    'RASTER_BAND': 1,
    'COLUMN_PREFIX': 'stat_',
    'STATISTICS': [0, 1, 2, 3, 4, 5, 6],  # count, sum, mean, min, max, std, median
    'OUTPUT': 'memory:'
})
stats_layer = result['OUTPUT']

# Accéder aux valeurs
for f in stats_layer.getFeatures():
    print(f["stat_mean"], f["stat_sum"])
""",
        "tags": ["statistiques", "zonales", "raster", "zonal stats", "mean", "sum"],
    },
    {
        "title": "Export couche vecteur",
        "content": """
Exporter une couche vecteur en différents formats :

from qgis.core import QgsVectorFileWriter, QgsCoordinateTransformContext

# Export GeoPackage
QgsVectorFileWriter.writeAsVectorFormatV3(
    layer,
    "/chemin/sortie.gpkg",
    QgsCoordinateTransformContext(),
    QgsVectorFileWriter.SaveVectorOptions()
)

# Via processing (plus simple)
import processing
processing.run("native:savefeatures", {
    'INPUT': layer,
    'OUTPUT': '/chemin/sortie.geojson'
})

iface.messageBar().pushMessage("Export", "Couche exportée avec succès", level=0)
""",
        "tags": ["export", "GeoPackage", "GeoJSON", "Shapefile", "sauvegarde"],
    },
    {
        "title": "Sélection et filtrage d'entités",
        "content": """
Sélectionner et filtrer des entités dans une couche :

# Par expression
layer.selectByExpression('"surface_ha" > 10 AND "type" = \'forêt\'')
selected = layer.selectedFeatures()

# Itérer avec filtre
request = QgsFeatureRequest()
request.setFilterExpression('"commune" = \'Lyon\'')
for feature in layer.getFeatures(request):
    print(feature["nom"])

# Sélection par rectangle (extent)
rect = QgsRectangle(xmin, ymin, xmax, ymax)
request = QgsFeatureRequest().setFilterRect(rect)

# Compter les entités sélectionnées
print(f"Sélection: {layer.selectedFeatureCount()} entités")
""",
        "tags": ["sélection", "filtre", "expression", "QgsFeatureRequest", "attribut"],
    },
    {
        "title": "Créer une nouvelle couche vecteur",
        "content": """
Créer une nouvelle couche vecteur en mémoire ou sur disque :

from qgis.core import QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY
from PyQt5.QtCore import QVariant

# Couche mémoire
layer = QgsVectorLayer("Point?crs=EPSG:2154", "nouvelle_couche", "memory")
provider = layer.dataProvider()

# Ajouter des champs
provider.addAttributes([
    QgsField("id", QVariant.Int),
    QgsField("nom", QVariant.String),
    QgsField("surface", QVariant.Double),
])
layer.updateFields()

# Ajouter une entité
feature = QgsFeature()
feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(2.3522, 48.8566)))
feature.setAttributes([1, "Paris", 0.0])
provider.addFeatures([feature])

QgsProject.instance().addMapLayer(layer)
""",
        "tags": ["créer", "couche", "mémoire", "QgsVectorLayer", "QgsFeature"],
    },
    {
        "title": "Calculer la surface et le périmètre",
        "content": """
Calculer surfaces et périmètres en Python PyQGIS :

from qgis.core import QgsDistanceArea, QgsProject

da = QgsDistanceArea()
da.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
da.setEllipsoid(QgsProject.instance().ellipsoid())

for feature in layer.getFeatures():
    geom = feature.geometry()
    area_m2 = da.measureArea(geom)
    area_ha = area_m2 / 10000
    perim_m = da.measurePerimeter(geom)
    print(f"Surface: {area_ha:.2f} ha, Périmètre: {perim_m:.0f} m")

# Via calculatrice de champ
layer.startEditing()
layer.addExpressionField('$area / 10000', QgsField('surface_ha', QVariant.Double))
layer.commitChanges()
""",
        "tags": ["surface", "périmètre", "area", "hectares", "mesure", "QgsDistanceArea"],
    },
    {
        "title": "Chargement données WFS / WMS IGN",
        "content": """
Charger des données depuis les services web IGN (Géoportail) :

# WMS IGN - Orthophotos
wms_uri = "crs=EPSG:2154&format=image/png&layers=ORTHOIMAGERY.ORTHOPHOTOS&styles=&url=https://wxs.ign.fr/essentiels/geoportail/r/wms"
raster = QgsRasterLayer(wms_uri, "Ortho IGN", "wms")
QgsProject.instance().addMapLayer(raster)

# WFS IGN - Bâtiments BD TOPO
wfs_uri = "pagingEnabled='true' preferCoordinatesForWfsT11='false' srsname='EPSG:2154' typename='BDTOPO_V3:batiment' url='https://wxs.ign.fr/essentiels/geoportail/wfs' version='2.0.0'"
wfs_layer = QgsVectorLayer(wfs_uri, "Bâtiments IGN", "WFS")
QgsProject.instance().addMapLayer(wfs_layer)

# API Cadastre (cadastre.gouv.fr)
import requests
r = requests.get("https://geocodage.ign.fr/look4/parcel/search?q=44109000BH0012")
print(r.json())
""",
        "tags": ["WMS", "WFS", "IGN", "Géoportail", "orthophoto", "cadastre", "BDTOPO"],
    },
    {
        "title": "Analyse de réseau et itinéraires",
        "content": """
Analyse de réseau routier avec PyQGIS :

import processing

# Distance sur réseau (QNEAT3)
result = processing.run("qneat3:distancematrix", {
    'INPUT': network_layer,
    'STRATEGY': 0,   # distance la plus courte
    'FROM_POINT': start_point,
    'TO_POINTS': destinations_layer,
    'OUTPUT': 'memory:'
})

# Zone isochrone
result = processing.run("qneat3:isoareas", {
    'INPUT': network_layer,
    'START_POINTS': origin_layer,
    'MAX_DIST': 5000,   # 5 km
    'STRATEGY': 0,
    'OUTPUT': 'memory:'
})
""",
        "tags": ["réseau", "itinéraire", "isochrone", "QNEAT3", "distance"],
    },
    {
        "title": "Fusion et dissolution de couches",
        "content": """
Fusionner et dissoudre des couches vecteur :

import processing

# Dissoudre par attribut
result = processing.run("native:dissolve", {
    'INPUT': layer,
    'FIELD': ['commune'],   # dissoudre par commune
    'OUTPUT': 'memory:'
})

# Fusionner plusieurs couches
result = processing.run("native:mergevectorlayers", {
    'LAYERS': [layer1, layer2, layer3],
    'CRS': QgsCoordinateReferenceSystem('EPSG:2154'),
    'OUTPUT': 'memory:'
})

# Clip - découper par un masque
result = processing.run("native:clip", {
    'INPUT': layer_a_decouper,
    'OVERLAY': masque,
    'OUTPUT': 'memory:'
})
""",
        "tags": ["fusionner", "dissoudre", "clip", "découper", "merge", "dissolve"],
    },
]


class RAGIndexer:
    """Indexeur RAG pour QGISIA+."""

    def __init__(self, store: Optional[RAGStore] = None):
        self._store = store or get_store()

    # ── Indexation base PyQGIS ─────────────────────────────────────────────────

    def index_pyqgis_knowledge(self, force: bool = False) -> int:
        """
        Indexe la base de connaissances PyQGIS intégrée.
        Idempotent si force=False (skip si déjà indexé).
        """
        if not force and self._store.count("pyqgis_docs") > 0:
            return 0

        self._store.delete_collection("pyqgis_docs")
        count = 0
        for item in PYQGIS_KNOWLEDGE_BASE:
            self._store.add_document(
                content=item["content"].strip(),
                collection="pyqgis_docs",
                metadata={"title": item["title"], "tags": item["tags"]},
                auto_chunk=False,
            )
            count += 1
        return count

    # ── Indexation couches QGIS ───────────────────────────────────────────────

    def index_project_layers(self, layers_info: List[Dict[str, Any]]) -> int:
        """
        Indexe les métadonnées des couches du projet QGIS courant.
        layers_info : liste de dicts avec keys: name, type, crs, feature_count, fields, extent
        """
        self._store.delete_collection("project_layers")
        count = 0
        for layer in layers_info:
            content = self._format_layer_doc(layer)
            self._store.add_document(
                content=content,
                collection="project_layers",
                metadata={
                    "title": f"Couche: {layer.get('name', 'inconnue')}",
                    "layer_name": layer.get("name", ""),
                    "layer_type": layer.get("type", ""),
                    "crs": layer.get("crs", ""),
                    "feature_count": layer.get("feature_count", 0),
                },
                auto_chunk=False,
            )
            count += 1
        return count

    def _format_layer_doc(self, layer: Dict[str, Any]) -> str:
        lines = [
            f"Couche QGIS: {layer.get('name', 'inconnue')}",
            f"Type: {layer.get('type', 'vecteur')}",
            f"CRS: {layer.get('crs', 'inconnu')}",
            f"Entités: {layer.get('feature_count', '?')}",
        ]
        if layer.get("extent"):
            lines.append(f"Emprise: {layer['extent']}")
        if layer.get("fields"):
            fields_str = ", ".join(
                f"{f.get('name','?')} ({f.get('type','?')})"
                for f in layer["fields"][:20]
            )
            lines.append(f"Champs: {fields_str}")
        if layer.get("geometry_type"):
            lines.append(f"Géométrie: {layer['geometry_type']}")
        return "\n".join(lines)

    # ── Indexation notes utilisateur ──────────────────────────────────────────

    def add_user_note(self, content: str, title: str = "", tags: Optional[List[str]] = None) -> List[str]:
        """Ajoute une note utilisateur à l'index RAG."""
        return self._store.add_document(
            content=content,
            collection="user_notes",
            metadata={"title": title or "Note utilisateur", "tags": tags or []},
        )

    # ── Indexation URL / documentation externe ────────────────────────────────

    def index_url(self, url: str, title: str = "") -> List[str]:
        """
        Télécharge et indexe le contenu d'une URL.
        Utilise requests si disponible, sinon urllib.
        """
        content = self._fetch_url(url)
        if not content:
            return []
        clean = self._clean_html(content)
        return self._store.add_document(
            content=clean,
            collection="web_snippets",
            metadata={"title": title or url, "url": url},
            source_url=url,
        )

    def _fetch_url(self, url: str, timeout: int = 10) -> Optional[str]:
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception:
            return None

    def _clean_html(self, html: str) -> str:
        """Nettoie le HTML pour garder seulement le texte."""
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()[:50000]  # max 50k chars

    # ── Recherche enrichie ────────────────────────────────────────────────────

    def search_for_prompt(
        self,
        query: str,
        top_k: int = 5,
        collections: Optional[List[str]] = None,
    ) -> str:
        """
        Recherche multi-collection et retourne un contexte formaté pour LLM.
        """
        all_results = []
        target = collections or ["pyqgis_docs", "project_layers", "user_notes"]
        per_col = max(2, top_k // len(target))

        for col in target:
            results = self._store.search(query, top_k=per_col, collection=col)
            all_results.extend(results)

        all_results.sort(key=lambda r: r.score, reverse=True)
        top = all_results[:top_k]

        if not top:
            return ""

        lines = ["## Contexte RAG — QGISIA+"]
        for r in top:
            title = r.metadata.get("title", r.collection)
            col_label = {"pyqgis_docs": "📘 PyQGIS", "project_layers": "🗂️ Projet",
                         "user_notes": "📝 Notes", "web_snippets": "🌐 Web"}.get(r.collection, r.collection)
            lines.append(f"\n### {col_label} | {title} *(score: {r.score:.2f})*")
            lines.append(r.content[:500])
        return "\n".join(lines)

    def stats(self) -> Dict[str, Any]:
        return self._store.stats()


# ── Singleton ─────────────────────────────────────────────────────────────────
_indexer_instance: Optional[RAGIndexer] = None


def get_indexer() -> RAGIndexer:
    global _indexer_instance
    if _indexer_instance is None:
        _indexer_instance = RAGIndexer()
    return _indexer_instance


def bootstrap_knowledge_base() -> Dict[str, int]:
    """
    Initialise la base de connaissances PyQGIS au démarrage du plugin.
    À appeler une fois dans __init__.py ou geoai_assistant.py.
    """
    indexer = get_indexer()
    n = indexer.index_pyqgis_knowledge(force=False)
    return {"pyqgis_docs_indexed": n, "total": get_store().count()}
