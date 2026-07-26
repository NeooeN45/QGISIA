# -*- coding: utf-8 -*-
"""
Earth-2 Studio tool — Prévisions météo/climat IA (NVIDIA Earth-2).

Wrappe `earth2studio` (https://docs.nvidia.com/deeplearning/earth2-studio/) pour
produire des cartes de prévisions à partir de modèles globaux (FourCastNet,
Pangu, AIFS, GraphCast).

Modes supportés (MVP) :
    - global_forecast : prévision globale à N heures pour des variables choisies

Variables courantes (ECMWF/ERA5) :
    t2m  : température 2 m (°C)
    msl  : pression mer (hPa)
    u10  : vent zonal 10 m (m/s)
    v10  : vent méridien 10 m (m/s)
    tp   : précipitations totales (mm)

Dépendances lourdes (~2 GB, GPU fortement recommandé) :
    pip install earth2studio xarray netCDF4 torch

Modèle par défaut : `fcn` (FourCastNet, ~150 Mo). Téléchargé en cache au premier
appel via earth2studio.models.

L'API du module reste **agnostique de l'environnement** : si earth2studio est
absent, `is_available()` retourne (False, raison) et toutes les méthodes lèvent
`Earth2UnavailableError` plutôt que de crasher.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

# ─── Constantes ───────────────────────────────────────────────────────────────

DEFAULT_MODEL = "fcn"
SUPPORTED_MODELS = ("fcn", "pangu", "aifs", "graphcast")
DEFAULT_VARIABLES = ("t2m", "msl", "u10", "v10")
SUPPORTED_VARIABLES = (
    "t2m", "msl", "u10", "v10", "tp", "tcwv", "z500", "t850", "u500", "v500",
)
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "earth2studio"
MAX_LEAD_HOURS = 240  # 10 jours


class Earth2UnavailableError(RuntimeError):
    """Levée quand earth2studio n'est pas installable/utilisable sur ce système."""


@dataclass
class ForecastResult:
    ok: bool
    geotiff_paths: list[str]
    variables: list[str]
    model: str
    lead_hours: int
    init_time: str
    duration_s: float
    message: str


# ─── Détection environnement ──────────────────────────────────────────────────


def is_available() -> tuple[bool, str]:
    """
    Vérifie que earth2studio + torch + xarray sont importables. Retourne
    (True, "") si OK, sinon (False, raison).
    """
    try:
        import torch  # noqa: F401
        # Vérifier que c'est bien la version CUDA
        if not torch.cuda.is_available():
            # Vérifier si c'est la version CPU
            if hasattr(torch, '_C') and 'cpu' in str(torch.__file__).lower():
                return False, "torch CPU détecté - version CUDA requise"
    except ImportError as e:
        return False, f"torch non installé : {e}"
    try:
        import xarray  # noqa: F401
    except ImportError as e:
        return False, f"xarray non installé : {e}"
    try:
        import earth2studio  # noqa: F401
    except ImportError as e:
        return False, (
            f"earth2studio non installé : {e}. "
            "Installe via 'pip install earth2studio'."
        )
    return True, ""


def _ensure_available() -> None:
    ok, reason = is_available()
    if not ok:
        raise Earth2UnavailableError(reason)


def install_dependencies(force: bool = False) -> dict:
    """
    Installe automatiquement les dépendances NVIDIA (torch CUDA + earth2studio).
    
    Args:
        force: Force la réinstallation même si déjà présent
        
    Returns:
        Dict avec success, error, logs, already_installed
    """
    try:
        from .nvidia_deps_installer import install_nvidia_deps
    except ImportError:
        # Fallback si import relatif échoue
        import sys
        import os
        sys.path.insert(0, os.path.dirname(__file__))
        from nvidia_deps_installer import install_nvidia_deps
    
    return install_nvidia_deps(force=force)


# ─── Validation des paramètres ────────────────────────────────────────────────


def _validate_lead_hours(lead_hours: int) -> int:
    if not isinstance(lead_hours, int) or lead_hours < 1:
        raise ValueError(f"lead_hours doit être un entier >= 1 (reçu : {lead_hours})")
    if lead_hours > MAX_LEAD_HOURS:
        raise ValueError(
            f"lead_hours dépasse le maximum supporté ({MAX_LEAD_HOURS}h = 10j)",
        )
    return lead_hours


def _validate_variables(variables: Sequence[str]) -> list[str]:
    if not variables:
        return list(DEFAULT_VARIABLES)
    out: list[str] = []
    for v in variables:
        v_norm = str(v).strip().lower()
        if v_norm not in SUPPORTED_VARIABLES:
            raise ValueError(
                f"Variable '{v}' non supportée. "
                f"Choisis parmi {SUPPORTED_VARIABLES}.",
            )
        if v_norm not in out:
            out.append(v_norm)
    return out


def _parse_init_time(init_time: Optional[str]) -> datetime:
    """
    Parse l'heure d'initialisation. Si None, utilise le dernier 6h pivot UTC.
    Retourne une datetime aware UTC.
    """
    if init_time is None or not str(init_time).strip():
        now = datetime.now(timezone.utc)
        # Aligne au pivot 6h le plus proche dans le passé
        pivot_hour = (now.hour // 6) * 6
        return now.replace(hour=pivot_hour, minute=0, second=0, microsecond=0)
    try:
        dt = datetime.fromisoformat(str(init_time).replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(
            f"init_time doit être ISO 8601 (ex: 2026-04-26T00:00:00Z). Reçu : {init_time!r}",
        ) from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ─── Forecaster principal ─────────────────────────────────────────────────────


class Earth2Forecaster:
    """
    Forecaster Earth-2 Studio. Lazy-init du modèle.
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
        self.device = device  # None → cuda si dispo, sinon cpu
        self._prognostic: Any = None  # earth2studio model, lazy

    def _load_prognostic(self) -> Any:
        """Instancie le modèle prognostic une seule fois."""
        if self._prognostic is not None:
            return self._prognostic
        _ensure_available()
        from earth2studio.models.px import FCN, Pangu24, AIFS, GraphCastSmall  # type: ignore

        registry = {
            "fcn": FCN,
            "pangu": Pangu24,
            "aifs": AIFS,
            "graphcast": GraphCastSmall,
        }
        cls = registry.get(self.model)
        if cls is None:
            raise Earth2UnavailableError(f"Mapping modèle introuvable : {self.model}")
        logger.info("Chargement modèle Earth-2 : %s", self.model)
        self._prognostic = cls.load_default_package().load_model()
        return self._prognostic

    def forecast_global(
        self,
        output_dir: str,
        *,
        init_time: Optional[str] = None,
        lead_hours: int = 24,
        variables: Sequence[str] = DEFAULT_VARIABLES,
    ) -> ForecastResult:
        """
        Lance une prévision globale et exporte chaque variable en GeoTIFF.
        """
        import time

        _ensure_available()
        lead_h = _validate_lead_hours(lead_hours)
        var_list = _validate_variables(variables)
        init_dt = _parse_init_time(init_time)

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        start = time.time()

        # Lazy imports lourds — on évite de polluer l'import du module
        from earth2studio.data import GFS  # type: ignore
        from earth2studio.io import XarrayBackend  # type: ignore
        import numpy as np  # type: ignore

        prognostic = self._load_prognostic()
        data_source = GFS()
        backend = XarrayBackend()

        # Boucle de propagation : de t=0 à t=lead_h par pas du modèle
        # earth2studio gère la cadence interne (généralement 6h).
        nsteps = max(1, lead_h // 6)
        ds = self._run_inference(prognostic, data_source, init_dt, nsteps, var_list, backend)

        # Export final tile par variable
        geotiff_paths: list[str] = []
        for var in var_list:
            if var not in ds.data_vars:
                logger.warning("Variable '%s' absente du dataset, ignorée", var)
                continue
            tif_path = out_dir / f"{self.model}_{var}_{init_dt.strftime('%Y%m%d_%H')}_+{lead_h:03d}h.tif"
            self._save_geotiff(ds[var].isel(time=-1), tif_path)
            geotiff_paths.append(str(tif_path))

        duration = time.time() - start
        return ForecastResult(
            ok=True,
            geotiff_paths=geotiff_paths,
            variables=var_list,
            model=self.model,
            lead_hours=lead_h,
            init_time=init_dt.isoformat(),
            duration_s=duration,
            message=(
                f"{len(geotiff_paths)} variables prévues à +{lead_h}h "
                f"avec {self.model} en {duration:.1f}s"
            ),
        )

    def _run_inference(
        self,
        prognostic: Any,
        data_source: Any,
        init_dt: datetime,
        nsteps: int,
        variables: list[str],
        backend: Any,
    ) -> Any:
        """Exécute l'inférence Earth-2 et retourne le xarray Dataset."""
        from earth2studio.run import deterministic  # type: ignore

        deterministic(
            time=[init_dt],
            nsteps=nsteps,
            prognostic=prognostic,
            data=data_source,
            io=backend,
        )
        ds = backend.root  # xarray.Dataset
        # Filtrage variables si nécessaire
        keep = [v for v in variables if v in ds.data_vars]
        return ds[keep] if keep else ds

    def _save_geotiff(self, da: Any, output_path: Path) -> None:
        """
        Sauvegarde un xarray.DataArray (lat/lon) en GeoTIFF EPSG:4326.
        Requires rioxarray.
        """
        try:
            import rioxarray  # noqa: F401  # type: ignore
        except ImportError as e:
            raise Earth2UnavailableError(
                f"rioxarray requis pour export GeoTIFF : {e}. "
                "Installe via 'pip install rioxarray'.",
            ) from e

        # Renomme les dims standard si nécessaire
        if "longitude" in da.dims:
            da = da.rename({"longitude": "x"})
        if "latitude" in da.dims:
            da = da.rename({"latitude": "y"})
        if "lon" in da.dims:
            da = da.rename({"lon": "x"})
        if "lat" in da.dims:
            da = da.rename({"lat": "y"})

        da = da.rio.write_crs("EPSG:4326", inplace=False)
        da.rio.to_raster(str(output_path), tiled=True, compress="DEFLATE")


# ─── API publique ─────────────────────────────────────────────────────────────


def forecast_weather(
    output_dir: str,
    *,
    model: str = DEFAULT_MODEL,
    init_time: Optional[str] = None,
    lead_hours: int = 24,
    variables: Optional[Sequence[str]] = None,
) -> ForecastResult:
    """
    Lance une prévision météo Earth-2 et exporte les résultats en GeoTIFF.

    Args:
        output_dir: Dossier de sortie pour les GeoTIFF.
        model: fcn (défaut) | pangu | aifs | graphcast.
        init_time: ISO 8601 UTC (défaut : dernier pivot 6h).
        lead_hours: Horizon de prévision (1-240h, défaut 24h).
        variables: Liste de variables (défaut : t2m, msl, u10, v10).

    Returns:
        ForecastResult avec geotiff_paths.

    Raises:
        Earth2UnavailableError si dépendances absentes.
        ValueError si paramètres invalides.
    """
    forecaster = Earth2Forecaster(model=model)
    return forecaster.forecast_global(
        output_dir,
        init_time=init_time,
        lead_hours=lead_hours,
        variables=variables or DEFAULT_VARIABLES,
    )
