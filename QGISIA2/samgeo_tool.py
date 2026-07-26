# -*- coding: utf-8 -*-
"""
SAMGeo tool — Segmentation automatique de rasters via Segment Anything (Meta).

Wrappe la lib `samgeo` (https://samgeo.gishub.org/) pour produire des polygones
GeoJSON depuis une image satellite/orthophoto.

Modes supportés (MVP) :
    - automatic   : génère tous les masques sans prompt (SAM AutomaticMaskGenerator)
    - text_prompt : segmente selon un prompt texte (LangSAM, requires GroundingDINO)

Dépendances lourdes (~1.5 GB, GPU recommandé) :
    pip install samgeo segment-anything torch torchvision

Le module s'auto-évalue : `is_available()` retourne (False, raison) si une
dépendance manque, et toutes les méthodes de segmentation lèvent une
SAMGeoUnavailableError plutôt que de crasher.

Le checkpoint SAM (~400 Mo pour vit_h) est téléchargé au premier appel et
mis en cache dans ~/.cache/samgeo/.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ─── Constantes ───────────────────────────────────────────────────────────────

DEFAULT_MODEL = "vit_h"
SUPPORTED_MODELS = ("vit_h", "vit_l", "vit_b")
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "samgeo"


class SAMGeoUnavailableError(RuntimeError):
    """Levée quand samgeo n'est pas installable/utilisable sur ce système."""


@dataclass
class SegmentationResult:
    ok: bool
    geojson_path: Optional[str]
    feature_count: int
    message: str
    model: str
    duration_s: float


# ─── Détection environnement ──────────────────────────────────────────────────


def is_available() -> tuple[bool, str]:
    """
    Vérifie que samgeo + torch sont importables sans déclencher de
    téléchargement de modèle. Retourne (True, "") si OK, sinon (False, raison).
    """
    try:
        import torch  # noqa: F401
    except ImportError as e:
        return False, f"torch non installé : {e}"

    try:
        import samgeo  # noqa: F401
    except ImportError as e:
        return False, f"samgeo non installé : {e}. Installe via 'pip install samgeo'"

    return True, ""


def _ensure_available() -> None:
    ok, reason = is_available()
    if not ok:
        raise SAMGeoUnavailableError(reason)


# ─── Segmenter principal ──────────────────────────────────────────────────────


class SAMGeoSegmenter:
    """
    Segmenter principal. Lazy-init du modèle pour éviter le téléchargement
    avant le premier appel.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        cache_dir: Optional[Path] = None,
        device: Optional[str] = None,
    ) -> None:
        if model not in SUPPORTED_MODELS:
            raise ValueError(
                f"Modèle '{model}' non supporté. Choisis parmi {SUPPORTED_MODELS}.",
            )
        self.model = model
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.device = device  # None → samgeo choisit (cuda si dispo, sinon cpu)
        self._sam_instance: Any = None  # type samgeo.SamGeo, lazy

    @property
    def checkpoint_path(self) -> Path:
        """Chemin local attendu pour le checkpoint SAM."""
        filenames = {
            "vit_h": "sam_vit_h_4b8939.pth",
            "vit_l": "sam_vit_l_0b3195.pth",
            "vit_b": "sam_vit_b_01ec64.pth",
        }
        return self.cache_dir / filenames[self.model]

    def _ensure_sam(self) -> Any:
        """Instancie SamGeo une seule fois (déclenche le download si besoin)."""
        if self._sam_instance is not None:
            return self._sam_instance
        _ensure_available()
        from samgeo import SamGeo  # type: ignore

        logger.info(
            "Initialisation SamGeo (model=%s, device=%s, cache=%s)",
            self.model,
            self.device or "auto",
            self.cache_dir,
        )
        self._sam_instance = SamGeo(
            model_type=self.model,
            checkpoint=str(self.checkpoint_path),
            sam_kwargs=None,
        )
        return self._sam_instance

    def segment_automatic(
        self,
        raster_path: str,
        output_geojson: str,
        *,
        min_area_px: int = 200,
    ) -> SegmentationResult:
        """
        Segmentation automatique sans prompt. Génère tous les masques détectés
        et les sauvegarde en GeoJSON polygons.
        """
        import time

        _ensure_available()
        in_path = Path(raster_path)
        if not in_path.exists():
            raise FileNotFoundError(f"Raster introuvable : {raster_path}")

        out_path = Path(output_geojson)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        start = time.time()
        sam = self._ensure_sam()
        # SamGeo API : generate(image_path, output, ...) puis raster_to_vector
        mask_tif = out_path.with_suffix(".mask.tif")
        sam.generate(str(in_path), output=str(mask_tif))
        # samgeo v3 : raster_to_vector ne supporte plus le kwarg min_area (transmis au
        # driver GeoJSON qui le rejette). On vectorise toutes les formes detectees.
        sam.raster_to_vector(str(mask_tif), str(out_path))
        # mask_tif laissé en place : utile pour QA visuelle, gérable côté
        # appelant si nettoyage souhaité.
        duration = time.time() - start

        feature_count = _count_features(out_path)
        return SegmentationResult(
            ok=True,
            geojson_path=str(out_path),
            feature_count=feature_count,
            message=f"{feature_count} polygones générés en {duration:.1f}s avec SAM-{self.model}",
            model=self.model,
            duration_s=duration,
        )

    def segment_text_prompt(
        self,
        raster_path: str,
        text_prompt: str,
        output_geojson: str,
        *,
        box_threshold: float = 0.24,
        text_threshold: float = 0.24,
    ) -> SegmentationResult:
        """
        Segmentation guidée par prompt texte (LangSAM = SAM + GroundingDINO).
        Ex : text_prompt='trees', 'buildings', 'water bodies'.

        Nécessite samgeo.text_sam.LangSAM.
        """
        import time

        _ensure_available()
        try:
            from samgeo.text_sam import LangSAM  # type: ignore
        except ImportError as e:
            raise SAMGeoUnavailableError(
                f"LangSAM (text prompt) indisponible : {e}. "
                "Installe via 'pip install samgeo[text]'.",
            ) from e

        in_path = Path(raster_path)
        if not in_path.exists():
            raise FileNotFoundError(f"Raster introuvable : {raster_path}")
        out_path = Path(output_geojson)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        start = time.time()
        lang_sam = LangSAM()
        lang_sam.predict(
            str(in_path),
            text_prompt,
            box_threshold=box_threshold,
            text_threshold=text_threshold,
            output=str(out_path.with_suffix(".mask.tif")),
        )
        lang_sam.raster_to_vector(
            str(out_path.with_suffix(".mask.tif")),
            str(out_path),
        )
        duration = time.time() - start

        feature_count = _count_features(out_path)
        return SegmentationResult(
            ok=True,
            geojson_path=str(out_path),
            feature_count=feature_count,
            message=f"{feature_count} polygones '{text_prompt}' générés en {duration:.1f}s",
            model=f"LangSAM-{self.model}",
            duration_s=duration,
        )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _count_features(geojson_path: Path) -> int:
    if not geojson_path.exists():
        return 0
    try:
        with geojson_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("type") == "FeatureCollection":
            return len(data.get("features", []))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Impossible de compter les features de %s : %s", geojson_path, e)
    return 0


def segment_raster_to_geojson(
    raster_path: str,
    output_geojson: str,
    *,
    mode: str = "automatic",
    text_prompt: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    min_area_px: int = 200,
) -> SegmentationResult:
    """
    API simple appelable par l'agent LLM.

    Args:
        raster_path: Chemin local du raster (GeoTIFF, PNG, JPG géoréférencés).
        output_geojson: Chemin où sauvegarder le GeoJSON résultat.
        mode: "automatic" (défaut) ou "text_prompt".
        text_prompt: Requis si mode="text_prompt" (ex: "trees", "buildings").
        model: vit_h (qualité, lent) | vit_l | vit_b (rapide).
        min_area_px: Filtre les polygones plus petits que N pixels.

    Returns:
        SegmentationResult.

    Raises:
        SAMGeoUnavailableError si samgeo/torch absents.
        ValueError si paramètres invalides.
        FileNotFoundError si raster_path manquant.
    """
    if mode == "text_prompt" and not text_prompt:
        raise ValueError("mode='text_prompt' requiert text_prompt.")
    if mode not in ("automatic", "text_prompt"):
        raise ValueError(f"Mode inconnu : {mode}")

    segmenter = SAMGeoSegmenter(model=model)
    if mode == "automatic":
        return segmenter.segment_automatic(
            raster_path,
            output_geojson,
            min_area_px=min_area_px,
        )
    return segmenter.segment_text_prompt(
        raster_path,
        text_prompt or "",
        output_geojson,
    )
