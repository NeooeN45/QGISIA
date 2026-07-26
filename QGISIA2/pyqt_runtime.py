# -*- coding: utf-8 -*-
"""
pyqt_runtime — bootstrap PyQt/WebEngine pour le bridge QGISIA+.

Extrait de geoai_assistant (démantèlement du monolithe, étape 1). Centralise la
détection de version PyQt (QGIS 3 → PyQt5, QGIS 4 → PyQt6), la résolution du
site-packages QGIS et le chargement du runtime web Qt (WebEngine/WebChannel).

⚠️ Code couplé au runtime QGIS : à valider via le smoke-test QGIS headless de la
CI après toute modification. Le comportement est strictement identique à
l'ancien code in-line (déplacement verbatim).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import qgis.PyQt


def detect_pyqt_version() -> str:
    """Retourne 'PyQt6' si QGIS 4+, sinon 'PyQt5'."""
    try:
        from qgis.core import Qgis
        ver = Qgis.versionInt() if callable(Qgis.versionInt) else int(Qgis.QGIS_VERSION_INT)
        return "PyQt6" if ver >= 40000 else "PyQt5"
    except Exception:
        try:
            import PyQt6  # noqa: F401
            return "PyQt6"
        except ImportError:
            return "PyQt5"


PYQT_VERSION = detect_pyqt_version()


def qgis_site_packages():
    """Détecte le site-packages de QGIS avec gestion des versions multiples."""
    try:
        from .version_manager import qgis_version_manager
        site_packages = qgis_version_manager.current_site_packages
        if site_packages:
            return str(site_packages)
    except ImportError:
        pass

    qgis_pyqt_dir = Path(qgis.PyQt.__file__).resolve()
    try:
        apps_dir = qgis_pyqt_dir.parents[4]
    except IndexError:
        return None

    for site_packages in sorted(apps_dir.glob("Python*/Lib/site-packages")):
        if (site_packages / PYQT_VERSION).exists():
            return str(site_packages)

    return None


def prefer_qgis_pyqt(site_packages) -> None:
    if not site_packages:
        return

    try:
        sys.path.remove(site_packages)
    except ValueError:
        pass

    sys.path.insert(0, site_packages)

    pyqt_module = sys.modules.get(PYQT_VERSION)
    module_path = getattr(pyqt_module, "__file__", None)
    if not module_path:
        return

    resolved_module_path = str(Path(module_path).resolve())
    if resolved_module_path.startswith(site_packages):
        return

    prefix = PYQT_VERSION
    for module_name in list(sys.modules):
        if (
            module_name == prefix
            or module_name.startswith(prefix + ".")
            or module_name.startswith("qgis.PyQt.QtWebEngine")
            or module_name.startswith("qgis.PyQt.QtWebChannel")
        ):
            del sys.modules[module_name]


def import_web_runtime():
    """Charge le runtime web Qt. Retourne
    (QWebEngineView, QWebChannel, QObject, pyqtSlot, QUrl)."""
    site_packages = qgis_site_packages()
    prefer_qgis_pyqt(site_packages)

    qt_pkg = PYQT_VERSION  # "PyQt5" ou "PyQt6"

    if qt_pkg == "PyQt6":
        try:
            web_engine_module = importlib.import_module("PyQt6.QtWebEngineWidgets")
        except ImportError:
            web_engine_module = importlib.import_module("PyQt6.QtWebEngineCore")
        web_channel_module = importlib.import_module("PyQt6.QtWebChannel")
        web_core_module = importlib.import_module("PyQt6.QtCore")
    else:
        web_engine_module = importlib.import_module("PyQt5.QtWebEngineWidgets")
        web_channel_module = importlib.import_module("PyQt5.QtWebChannel")
        web_core_module = importlib.import_module("PyQt5.QtCore")

    web_engine_path = str(Path(web_engine_module.__file__).resolve())
    web_channel_path = str(Path(web_channel_module.__file__).resolve())
    web_core_path = str(Path(web_core_module.__file__).resolve())
    if site_packages and (
        not web_engine_path.startswith(site_packages)
        or not web_channel_path.startswith(site_packages)
        or not web_core_path.startswith(site_packages)
    ):
        raise ImportError(
            "Runtime web Qt résolu hors de QGIS: "
            f"engine={web_engine_path}, channel={web_channel_path}, core={web_core_path}"
        )

    QWebEngineViewCls = getattr(web_engine_module, "QWebEngineView", None)
    QWebChannelCls = web_channel_module.QWebChannel
    QObjectCls = web_core_module.QObject
    pyqtSlotFn = web_core_module.pyqtSlot
    QUrlCls = web_core_module.QUrl

    return (QWebEngineViewCls, QWebChannelCls, QObjectCls, pyqtSlotFn, QUrlCls)
