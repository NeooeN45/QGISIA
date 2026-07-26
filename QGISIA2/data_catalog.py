# -*- coding: utf-8 -*-
"""
Catalogue de sources cartographiques mondiales gratuites (XYZ / WMTS / WMS).

Module pur Python (testable sans QGIS). Lit QGISIA2/config/data_sources.json et
construit la config attendue par le bridge (_create_service_layer).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

CATALOG_PATH = Path(__file__).parent / "config" / "data_sources.json"
VALID_SERVICE_TYPES = {"XYZ", "WMTS", "WMS", "WFS"}


def load_sources() -> List[dict]:
    if not CATALOG_PATH.exists():
        return []
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8")).get("sources", [])
    except (json.JSONDecodeError, OSError):
        return []


def get_source(source_id: str) -> Optional[dict]:
    return next((s for s in load_sources() if s.get("id") == source_id), None)


def list_sources(category: Optional[str] = None) -> List[dict]:
    sources = load_sources()
    if category:
        sources = [s for s in sources if s.get("category") == category]
    return [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "category": s.get("category"),
            "coverage": s.get("coverage"),
            "provider": s.get("provider"),
        }
        for s in sources
    ]


def build_service_config(source: dict) -> dict:
    """Transforme une entree du catalogue en config pour _create_service_layer."""
    st = source.get("service_type")
    params = source.get("params", {}) or {}
    cfg = {
        "service_type": st,
        "url": source.get("url", ""),
        "name": source.get("name", source.get("id")),
    }
    if st == "XYZ":
        cfg["zmax"] = params.get("zmax", 19)
        cfg["zmin"] = params.get("zmin", 0)
    elif st == "WMS":
        cfg["layers"] = params.get("layers", "")
        cfg["format"] = params.get("format", "image/png")
        cfg["crs"] = params.get("crs", "EPSG:3857")
    elif st == "WMTS":
        cfg["layer"] = params.get("layer", "")
        cfg["tileMatrixSet"] = params.get("tileMatrixSet", "PM")
        cfg["format"] = params.get("format", "image/png")
        cfg["style"] = params.get("style", "normal")
    elif st == "WFS":
        cfg["layer"] = params.get("layer", "")  # typename
        cfg["crs"] = params.get("crs", "EPSG:4326")
        cfg["version"] = params.get("version", "2.0.0")
    return cfg
