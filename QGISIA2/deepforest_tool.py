"""DeepForest tool — Détection d'arbres sur raster via DeepForest.

Wrappe la lib `deepforest` (https://deepforest.readthedocs.io/) pour produire
un GeoJSON de polygones d'arbres depuis une image satellite/orthophoto.

Dépendances lourdes (~500 MB, GPU recommandé) :
    pip install deepforest torch

Le module s'auto-évalue : `is_available()` retourne (False, raison) si une
dépendance manque, et `detect_trees()` lève une DeepForestUnavailableError
plutôt que de crasher.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PATCH_SIZE = 400
DEFAULT_PATCH_OVERLAP = 0.25


class DeepForestUnavailableError(RuntimeError):
    """Levée quand deepforest n'est pas installable/utilisable sur ce système."""


@dataclass
class TreeDetectionResult:
    ok: bool
    geojson_path: Optional[str]
    tree_count: int
    message: str
    duration_s: float


def is_available() -> tuple[bool, str]:
    """
    Vérifie que deepforest + torch sont importables sans déclencher de
    téléchargement de modèle. Retourne (True, "") si OK, sinon (False, raison).
    """
    try:
        import torch  # noqa: F401
    except ImportError as e:
        return False, f"torch non installé : {e}"

    try:
        import deepforest  # noqa: F401
    except ImportError as e:
        return False, f"deepforest non installé : {e}. Installe via 'pip install deepforest'"

    return True, ""


def _ensure_available() -> None:
    ok, reason = is_available()
    if not ok:
        raise DeepForestUnavailableError(reason)


def _boxes_to_geojson(boxes, transform, crs_wkt: str) -> dict:
    """Convertit un GeoDataFrame de boxes en FeatureCollection GeoJSON."""
    features = []
    for _, row in boxes.iterrows():
        geom = row.geometry
        features.append({
            "type": "Feature",
            "properties": {"score": float(row.get("score", 0.0))},
            "geometry": geom.__geo_interface__,
        })
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": crs_wkt}},
        "features": features,
    }


def detect_trees(
    raster_path: str,
    output_geojson: str,
    patch_size: int = DEFAULT_PATCH_SIZE,
    patch_overlap: float = DEFAULT_PATCH_OVERLAP,
) -> TreeDetectionResult:
    """
    Détecte les arbres sur un raster et sauvegarde les résultats en GeoJSON.

    Args:
        raster_path: Chemin local du raster (GeoTIFF, PNG, JPG géoréférencés).
        output_geojson: Chemin où sauvegarder le GeoJSON résultat.
        patch_size: Taille des tuiles pour la prédiction (pixels).
        patch_overlap: Chevauchement entre tuiles (0..1).

    Returns:
        TreeDetectionResult.

    Raises:
        DeepForestUnavailableError si deepforest/torch absents.
        FileNotFoundError si raster_path manquant.
    """
    _ensure_available()

    in_path = Path(raster_path)
    if not in_path.exists():
        raise FileNotFoundError(f"Raster introuvable : {raster_path}")

    out_path = Path(output_geojson)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    start = time.time()

    from deepforest import main as deepforest_main
    import rasterio
    from rasterio.transform import from_bounds

    # Charger le modèle pré-entraîné
    model = deepforest_main.deepforest()
    model.use_release()

    # Lire l'extent du raster
    with rasterio.open(in_path) as src:
        bounds = src.bounds
        crs_wkt = src.crs.to_wkt() if src.crs else "EPSG:4326"
        width = src.width
        height = src.height

    # Prédiction par tuiles
    boxes = model.predict_tile(
        raster_path=str(in_path),
        patch_size=patch_size,
        patch_overlap=patch_overlap,
        return_plot=False,
    )

    # Convertir les boxes en polygones
    if boxes is None or boxes.empty:
        duration = time.time() - start
        geojson = {"type": "FeatureCollection", "features": []}
        out_path.write_text(json.dumps(geojson), encoding="utf-8")
        return TreeDetectionResult(
            ok=True,
            geojson_path=str(out_path),
            tree_count=0,
            message="Aucun arbre détecté",
            duration_s=duration,
        )

    # Géoréférencer les boxes
    import geopandas as gpd
    from shapely.geometry import box

    boxes["geometry"] = boxes.apply(
        lambda row: box(row["xmin"], row["ymin"], row["xmax"], row["ymax"]), axis=1,
    )
    transform = from_bounds(bounds.left, bounds.bottom, bounds.right, bounds.top, width, height)
    gdf = gpd.GeoDataFrame(boxes, geometry="geometry", crs=crs_wkt)
    gdf = gdf.to_crs("EPSG:4326")

    geojson = _boxes_to_geojson(gdf, transform, crs_wkt)
    out_path.write_text(json.dumps(geojson), encoding="utf-8")

    duration = time.time() - start
    tree_count = len(geojson["features"])
    return TreeDetectionResult(
        ok=True,
        geojson_path=str(out_path),
        tree_count=tree_count,
        message=f"{tree_count} arbres détectés en {duration:.1f}s",
        duration_s=duration,
    )
