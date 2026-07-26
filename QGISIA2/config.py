# -*- coding: utf-8 -*-
"""
Configuration du plugin QGISIA+ pour QGIS
"""

# Configuration de l'interface
PLUGIN_CONFIG = {
    "name": "QGISIA+",
    "version": "3.4",
    "description": "Assistant IA pour QGIS - BYOK multi-provider",
    "author": "QGISIA+",
    
    # Interface
    "dock_title": "QGISIA+",
    "dock_area": "right",  # left, right, top, bottom
    "dock_width": 450,
    
    # Performance
    "enable_caching": True,
    "cache_ttl": 300,  # secondes
    "max_concurrent_requests": 3,
    
    # Interface utilisateur
    "show_quick_actions": True,
    "show_layer_panel": True,
    "show_history": True,
    "show_settings_button": True,
    
    # Actions rapides
    "quick_actions": [
        {
            "id": "list_layers",
            "label": "Lister les couches",
            "icon": "mActionListLayers",
            "tooltip": "Afficher toutes les couches du projet",
        },
        {
            "id": "diagnose_layer",
            "label": "Diagnostiquer couche",
            "icon": "mActionIdentify",
            "tooltip": "Diagnostiquer la couche sélectionnée",
        },
        {
            "id": "export_stats",
            "label": "Statistiques",
            "icon": "mActionStatistics",
            "tooltip": "Calculer les statistiques de la couche sélectionnée",
        },
        {
            "id": "zoom_to_layer",
            "label": "Zoomer sur couche",
            "icon": "mActionZoomToLayer",
            "tooltip": "Zoomer sur la couche sélectionnée",
        },
    ],
    
    # Messages
    "messages": {
        "loading": "Chargement en cours...",
        "error": "Une erreur est survenue",
        "success": "Opération réussie",
        "no_layer_selected": "Aucune couche sélectionnée",
        "bridge_connected": "Connecté à QGIS",
        "bridge_disconnected": "Déconnecté de QGIS",
    },
    
    # Couleurs (format hex)
    "colors": {
        "primary": "#0891b2",  # cyan-600
        "success": "#10b981",  # emerald-500
        "warning": "#f59e0b",  # amber-500
        "error": "#ef4444",    # red-500
        "background": "#131314",
        "text": "#e3e3e3",
    },
}
