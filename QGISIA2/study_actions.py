# -*- coding: utf-8 -*-
"""
Actions supportees par l'orchestrateur d'etude territoriale autonome (/api/llm/autoStudy).

Module pur : sert de contrat partage entre study_plan (genere les etapes) et
l'executeur (geoai_assistant) qui les deroule. Un test verifie que toutes les
actions produites par study_plan sont bien prises en charge.
"""
from __future__ import annotations

SUPPORTED_ACTIONS = {
    "add_basemap",      # -> addDataSource
    "load_satellite",   # -> loadSatelliteBands
    "compute_index",    # -> computeSpectralIndex
    "detect_change",    # -> computeRasterDifference
    "zonal_stats",      # -> zonalStatistics
    "classify",         # -> classifyRaster
    "layout",           # -> exportPrintLayout
    "report",           # -> generate_report (report_templates)
}

# Gabarit de rapport par theme
REPORT_TEMPLATE_BY_THEME = {
    "vegetation": "diagnostic_vegetation",
    "urbanisme": "diagnostic_urbanisme",
    "risques": "diagnostic_risques",
}


def is_supported(action: str) -> bool:
    return action in SUPPORTED_ACTIONS
