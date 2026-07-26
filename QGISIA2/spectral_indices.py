# -*- coding: utf-8 -*-
"""
Indices spectraux pour Sentinel-2 / Landsat — expressions compatibles QgsRasterCalculator.

Module pur Python (testable sans QGIS). Remplace les noms de bandes abstraits
(RED, NIR, GREEN, SWIR, BLUE) par les references de canaux raster fournies.
"""
from __future__ import annotations

from typing import List

INDICES = {
    "ndvi": {
        "name": "NDVI",
        "description": "Normalized Difference Vegetation Index",
        "formula": "(NIR - RED) / (NIR + RED)",
        "bands": ["NIR", "RED"],
    },
    "ndwi": {
        "name": "NDWI",
        "description": "Normalized Difference Water Index (McFeeters)",
        "formula": "(GREEN - NIR) / (GREEN + NIR)",
        "bands": ["GREEN", "NIR"],
    },
    "ndbi": {
        "name": "NDBI",
        "description": "Normalized Difference Built-up Index",
        "formula": "(SWIR - NIR) / (SWIR + NIR)",
        "bands": ["SWIR", "NIR"],
    },
    "nbr": {
        "name": "NBR",
        "description": "Normalized Burn Ratio",
        "formula": "(NIR - SWIR) / (NIR + SWIR)",
        "bands": ["NIR", "SWIR"],
    },
    "evi": {
        "name": "EVI",
        "description": "Enhanced Vegetation Index",
        "formula": "2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))",
        "bands": ["NIR", "RED", "BLUE"],
    },
    "savi": {
        "name": "SAVI",
        "description": "Soil Adjusted Vegetation Index",
        "formula": "((NIR - RED) / (NIR + RED + 0.5)) * 1.5",
        "bands": ["NIR", "RED"],
    },
    "msavi2": {
        "name": "MSAVI2",
        "description": "Modified Soil Adjusted Vegetation Index 2",
        "formula": "(2 * NIR + 1 - sqrt((2 * NIR + 1)^2 - 8 * (NIR - RED))) / 2",
        "bands": ["NIR", "RED"],
    },
    "ndmi": {
        "name": "NDMI",
        "description": "Normalized Difference Moisture Index",
        "formula": "(NIR - SWIR) / (NIR + SWIR)",
        "bands": ["NIR", "SWIR"],
    },
    "bsi": {
        "name": "BSI",
        "description": "Bare Soil Index",
        "formula": "((SWIR + RED) - (NIR + BLUE)) / ((SWIR + RED) + (NIR + BLUE))",
        "bands": ["SWIR", "RED", "NIR", "BLUE"],
    },
    "mndwi": {
        "name": "MNDWI",
        "description": "Modified Normalized Difference Water Index (Xu, 2006)",
        "formula": "(GREEN - SWIR) / (GREEN + SWIR)",
        "bands": ["GREEN", "SWIR"],
    },
    "ndsi": {
        "name": "NDSI",
        "description": "Normalized Difference Snow Index",
        "formula": "(GREEN - SWIR) / (GREEN + SWIR)",
        "bands": ["GREEN", "SWIR"],
    },
    "gci": {
        "name": "GCI",
        "description": "Green Chlorophyll Index",
        "formula": "(NIR / GREEN) - 1",
        "bands": ["NIR", "GREEN"],
    },
    "exg": {
        "name": "ExG",
        "description": "Excess Green Index",
        "formula": "2 * GREEN - RED - BLUE",
        "bands": ["GREEN", "RED", "BLUE"],
    },
    "gndvi": {
        "name": "GNDVI",
        "description": "Green Normalized Difference Vegetation Index",
        "formula": "(NIR - GREEN) / (NIR + GREEN)",
        "bands": ["NIR", "GREEN"],
    },
    "osavi": {
        "name": "OSAVI",
        "description": "Optimized Soil Adjusted Vegetation Index",
        "formula": "((NIR - RED) / (NIR + RED + 0.16)) * 1.16",
        "bands": ["NIR", "RED"],
    },
    "evi2": {
        "name": "EVI2",
        "description": "Enhanced Vegetation Index 2 (2-band)",
        "formula": "2.5 * ((NIR - RED) / (NIR + 2.4 * RED + 1))",
        "bands": ["NIR", "RED"],
    },
    "arvi": {
        "name": "ARVI",
        "description": "Atmospherically Resistant Vegetation Index",
        "formula": "(NIR - (2 * RED - BLUE)) / (NIR + (2 * RED - BLUE))",
        "bands": ["NIR", "RED", "BLUE"],
    },
    "vari": {
        "name": "VARI",
        "description": "Visible Atmospherically Resistant Index",
        "formula": "(GREEN - RED) / (GREEN + RED - BLUE)",
        "bands": ["GREEN", "RED", "BLUE"],
    },
    "tgi": {
        "name": "TGI",
        "description": "Triangular Greenness Index",
        "formula": "GREEN - 0.39 * RED - 0.61 * NIR",
        "bands": ["GREEN", "RED", "NIR"],
    },
    "ndre": {
        "name": "NDRE",
        "description": "Normalized Difference Red Edge",
        "formula": "(NIR - RED_EDGE) / (NIR + RED_EDGE)",
        "bands": ["NIR", "RED_EDGE"],
    },
    "cire": {
        "name": "CIRE",
        "description": "Chlorophyll Index Red Edge",
        "formula": "(NIR / RED_EDGE) - 1",
        "bands": ["NIR", "RED_EDGE"],
    },
    "awei": {
        "name": "AWEI",
        "description": "Automated Water Extraction Index",
        "formula": "4 * (GREEN - SWIR1) - (0.25 * NIR + 2.75 * SWIR2)",
        "bands": ["GREEN", "NIR", "SWIR1", "SWIR2"],
    },
    "nbr2": {
        "name": "NBR2",
        "description": "Normalized Burn Ratio 2",
        "formula": "(SWIR1 - SWIR2) / (SWIR1 + SWIR2)",
        "bands": ["SWIR1", "SWIR2"],
    },
    "bai": {
        "name": "BAI",
        "description": "Burned Area Index",
        "formula": "1 / ((0.1 - RED)^2 + (0.06 - NIR)^2)",
        "bands": ["RED", "NIR"],
    },
    "nbri": {
        "name": "NBRI",
        "description": "Normalized Burn Ratio Index",
        "formula": "(NIR - SWIR2) / (NIR + SWIR2)",
        "bands": ["NIR", "SWIR2"],
    },
    "baei": {
        "name": "BAEI",
        "description": "Built-up Area Extraction Index",
        "formula": "(RED + 0.3) / (GREEN + SWIR1)",
        "bands": ["RED", "GREEN", "SWIR1"],
    },
    "ui": {
        "name": "UI",
        "description": "Urban Index",
        "formula": "(SWIR2 - NIR) / (SWIR2 + NIR)",
        "bands": ["SWIR2", "NIR"],
    },
    "ibi": {
        "name": "IBI",
        "description": "Index-based Built-up Index",
        "formula": "((2 * SWIR1) / (SWIR1 + NIR)) - ((NIR / (NIR + RED)) + (GREEN / (GREEN + SWIR1)))",
        "bands": ["SWIR1", "NIR", "RED", "GREEN"],
    },
    "si": {
        "name": "SI",
        "description": "Salinity Index",
        "formula": "sqrt(SWIR1 * SWIR2)",
        "bands": ["SWIR1", "SWIR2"],
    },
}


def list_indices() -> List[dict]:
    """Renvoie la liste des indices avec leurs metadonnees."""
    return [
        {
            "id": k,
            "name": v["name"],
            "description": v["description"],
            "bands": v["bands"],
        }
        for k, v in INDICES.items()
    ]


def build_expression(index_id: str, band_map: dict) -> str:
    """
    Construit l'expression QgsRasterCalculator pour un indice spectral.

    Args:
        index_id: identifiant de l'indice (ex: 'ndvi').
        band_map: mapping {band_name: raster_ref}, ex {"NIR": "b8@1", "RED": "b4@1"}.

    Raises:
        ValueError: si l'indice est inconnu ou si une bande requise est manquante.
    """
    meta = INDICES.get(index_id)
    if meta is None:
        raise ValueError(f"Indice spectral inconnu: {index_id}")

    expr = meta["formula"]
    for band in meta["bands"]:
        ref = band_map.get(band)
        if ref is None:
            raise ValueError(f"Bande manquante pour {index_id}: {band}")
        expr = expr.replace(band, ref)
    return expr


def index_metadata(index_id: str) -> dict | None:
    """Retourne les metadonnees completes d'un indice spectral."""
    meta = INDICES.get(index_id)
    if meta is None:
        return None
    return {
        "name": meta["name"],
        "formula": meta["formula"],
        "bands": meta["bands"],
        "range": _INDEX_RANGES.get(index_id),
        "usage": _INDEX_USAGE.get(index_id),
    }


def list_index_metadata() -> list[dict]:
    """Liste les metadonnees de tous les indices spectraux."""
    return [index_metadata(k) for k in INDICES.keys()]


# ─── Metadonnees enrichies ───────────────────────────────────────────────────

_INDEX_RANGES: dict[str, tuple[float, float]] = {
    "ndvi": (-1.0, 1.0),
    "ndwi": (-1.0, 1.0),
    "ndbi": (-1.0, 1.0),
    "nbr": (-1.0, 1.0),
    "evi": (-1.0, 1.0),
    "savi": (-1.0, 1.0),
    "msavi2": (-1.0, 1.0),
    "ndmi": (-1.0, 1.0),
    "bsi": (-1.0, 1.0),
    "mndwi": (-1.0, 1.0),
    "ndsi": (-1.0, 1.0),
    "gci": (-1.0, 10.0),
    "exg": (-255.0, 255.0),
    "gndvi": (-1.0, 1.0),
    "osavi": (-1.0, 1.0),
    "evi2": (-1.0, 1.0),
    "arvi": (-1.0, 1.0),
    "vari": (-1.0, 1.0),
    "tgi": (-255.0, 255.0),
    "ndre": (-1.0, 1.0),
    "cire": (-1.0, 10.0),
    "awei": (-10.0, 10.0),
    "nbr2": (-1.0, 1.0),
    "bai": (0.0, 1000.0),
    "nbri": (-1.0, 1.0),
    "baei": (-1.0, 1.0),
    "ui": (-1.0, 1.0),
    "ibi": (-1.0, 1.0),
    "si": (0.0, 255.0),
}

_INDEX_USAGE: dict[str, str] = {
    "ndvi": "vegetation",
    "ndwi": "eau",
    "ndbi": "urbain",
    "nbr": "brulure",
    "evi": "vegetation",
    "savi": "vegetation",
    "msavi2": "vegetation",
    "ndmi": "humidite",
    "bsi": "sol_nu",
    "mndwi": "eau",
    "ndsi": "neige",
    "gci": "chlorophylle",
    "exg": "vegetation",
    "gndvi": "vegetation",
    "osavi": "vegetation",
    "evi2": "vegetation",
    "arvi": "vegetation",
    "vari": "vegetation",
    "tgi": "chlorophylle",
    "ndre": "vegetation",
    "cire": "chlorophylle",
    "awei": "eau",
    "nbr2": "brulure",
    "bai": "brulure",
    "nbri": "brulure",
    "baei": "urbain",
    "ui": "urbain",
    "ibi": "urbain",
    "si": "salinite",
}


def sentinel2_band_map() -> dict:
    """Mapping bandes Sentinel-2 (niveau 1C/2A) vers references raster standard."""
    return {
        "BLUE": "B2@1",
        "GREEN": "B3@1",
        "RED": "B4@1",
        "RED_EDGE": "B5@1",
        "NIR": "B8@1",
        "SWIR": "B11@1",
        "SWIR1": "B11@1",
        "SWIR2": "B12@1",
    }
