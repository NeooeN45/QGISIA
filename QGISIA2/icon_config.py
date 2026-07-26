# -*- coding: utf-8 -*-
"""
Configuration de l'icône et de la disposition du plugin dans QGIS
"""

# Configuration de l'icône
ICON_CONFIG = {
    "name": "QGISAI+ AI",
    "tooltip": "Ouvrir l'assistant IA QGISAI+",
    "status_tip": "Assistant IA pour QGIS - Intégration OpenRouter",
    "whats_this": (
        "QGISAI+ AI est un assistant intelligent qui vous aide à accomplir "
        "des tâches SIG complexes en langage naturel.\n\n"
        "Fonctionnalités:\n"
        "- Commandes en langage naturel\n"
        "- Gestion de couches QGIS\n"
        "- Exécution de scripts PyQGIS\n"
        "- Intégration avec OpenRouter, Google Gemini, Ollama\n\n"
        "Raccourci clavier: Ctrl+Shift+G"
    ),
    "shortcut": "Ctrl+Shift+G",
    "shortcut_context": "window",  # window, application
    "text": "QGISAI+ AI",  # Texte à afficher sur le bouton
    "show_text": True,  # Afficher le texte sur le bouton
    "icon_size": 32,  # Taille de l'icône en pixels
}

# Configuration de la disposition dans la barre d'outils
TOOLBAR_CONFIG = {
    "position": "left",  # left, right (par défaut QGIS décide)
    "priority": 10,  # Priorité pour le placement (plus élevé = plus à gauche)
    "group": "GeoAI",  # Groupe d'icônes
    "separator_before": True,  # Ajouter un séparateur avant
    "separator_after": False,  # Ajouter un séparateur après
}

# Configuration du menu
MENU_CONFIG = {
    "name": "&QGISAI+",
    "position": "top",  # top, bottom dans le menu Plugins
    "icon": True,  # Afficher l'icône dans le menu
    "submenu": True,  # Utiliser un sous-menu
    "items": [
        {
            "name": "Ouvrir",
            "tooltip": "Ouvrir le panneau QGISAI+ AI",
            "icon": "icon.svg",
            "shortcut": "Ctrl+Shift+G",
        },
        {
            "separator": True,
        },
        {
            "name": "Paramètres...",
            "tooltip": "Ouvrir les paramètres",
            "icon": "preferences-system",
        },
        {
            "name": "Aide & Documentation",
            "tooltip": "Ouvrir la documentation",
            "icon": "help-contents",
        },
        {
            "separator": True,
        },
        {
            "name": "À propos",
            "tooltip": "À propos de QGISAI+",
            "icon": "help-about",
        },
    ],
}

# Configuration du menu Processing (si disponible)
PROCESSING_MENU_CONFIG = {
    "add": True,
    "separator_before": True,
    "position": "bottom",
}

# Configuration du dock widget
DOCK_CONFIG = {
    "title": "QGISAI+",
    "area": "right",  # left, right, top, bottom
    "allowed_areas": ["left", "right"],
    "default_width": 450,
    "minimum_width": 300,
    "maximum_width": 800,
    "floating": False,  # Permettre le mode flottant
    "closable": True,  # Permettre la fermeture
    "movable": True,  # Permettre le déplacement
}

# Configuration des messages
MESSAGE_CONFIG = {
    "on_open": "QGISAI+ ouvert",
    "on_close": "QGISAI+ fermé",
    "on_error": "Erreur QGISAI+: {error}",
    "on_success": "Opération réussie",
    "duration": 3,  # secondes
}

# Configuration des couleurs pour l'interface QGIS
COLORS = {
    "primary": "#22c55e",  # emerald-500
    "success": "#10b981",  # emerald-500
    "warning": "#f59e0b",  # amber-500
    "error": "#ef4444",    # red-500
    "info": "#3b82f6",     # blue-500
}
