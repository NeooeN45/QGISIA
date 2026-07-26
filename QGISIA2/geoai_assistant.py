# -*- coding: utf-8 -*-
from .ui import LaunchButton, QGISAILaunchDock
import ast
import functools
import http.server
import importlib
import json
import os
import re
import socketserver
import statistics
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse

# ── Sécurité (P0) ───────────────────────────────────────────────────────────
# Middleware de rate-limiting / validation, désormais réellement câblé au bridge.
try:
    from .security_layer import SecurityMiddleware
except Exception:  # pragma: no cover - fallback standalone / import partiel
    SecurityMiddleware = None  # type: ignore[assignment]

# Modules purs (sans Qt) extraits du monolithe — testables en CI sans QGIS.
try:
    from . import script_validation
    from . import bridge_http
except ImportError:  # pragma: no cover - fallback import absolu (standalone)
    import script_validation  # type: ignore[no-redef]
    import bridge_http  # type: ignore[no-redef]

# Réexports pour compatibilité interne (anciens noms locaux).
MAX_REQUEST_BYTES = bridge_http.MAX_REQUEST_BYTES
_send_cors_headers = bridge_http.send_cors_headers

# Correction des problèmes de versions multiples QGIS
try:
    from .version_manager import fix_qgis_multi_version_issues
    fix_qgis_multi_version_issues()
except ImportError:
    # Si le module n'est pas disponible, continuer sans
    pass

# Import de la configuration de l'icône
try:
    from .icon_config import ICON_CONFIG, MENU_CONFIG, TOOLBAR_CONFIG
except ImportError:
    # Fallback si la configuration n'est pas disponible
    ICON_CONFIG = {}
    MENU_CONFIG = {}
    TOOLBAR_CONFIG = {}


# ── Persistance des clés API côté plugin (QgsSettings) ────────────────────────
# Stockage indépendant du navigateur, du port et du localStorage : la clé saisie
# une fois reste disponible entre sessions. Le backend la réinjecte dans chaque
# requête LLM si le frontend n'en fournit pas (fallback : QgsSettings puis env).
_API_KEY_PROVIDERS = ("nvidia_nim", "openrouter", "gemini")
_ENV_KEY_FALLBACK = {"nvidia_nim": "NVIDIA_API_KEY", "openrouter": "OPENROUTER_API_KEY"}


def _stored_api_keys():
    """Clés persistées (QgsSettings) + repli variables d'environnement."""
    keys = {}
    try:
        from qgis.core import QgsSettings
        settings = QgsSettings()
        for provider in _API_KEY_PROVIDERS:
            value = settings.value(f"QGISIA/keys/{provider}", "", type=str)
            if value:
                keys[provider] = value
    except Exception:  # pragma: no cover - hors QGIS
        pass
    for provider, env_name in _ENV_KEY_FALLBACK.items():
        if not keys.get(provider) and os.environ.get(env_name):
            keys[provider] = os.environ[env_name]
    return keys


def _store_api_key(provider, key):
    """Persiste (ou efface) une clé API dans QgsSettings."""
    try:
        from qgis.core import QgsSettings
        QgsSettings().setValue(f"QGISIA/keys/{provider}", key or "")
        return True
    except Exception:  # pragma: no cover - hors QGIS
        return False

# Import des modules d'installation Ollama
try:
    from .system_capabilities import system_capabilities
    from .ollama_installer import ollama_installer
except ImportError:
    # Fallback si les modules ne sont pas disponibles
    system_capabilities = None
    ollama_installer = None

import processing
import qgis.PyQt
from qgis.PyQt.QtCore import QObject, Qt, QThread, QEventLoop, QTimer, QUrl, QVariant, pyqtSignal, pyqtSlot
from qgis.PyQt.QtGui import QDesktopServices, QColor, QFont, QGuiApplication, QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QFileDialog,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsDataSourceUri,
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsLineSymbol,
    QgsMapLayerType,
    QgsMessageLog,
    QgsPalLayerSettings,
    QgsProcessingFeedback,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
    Qgis,
)

QWebEngineView = None
QWebChannel = None
BridgeQObject = QObject
BridgeSlot = pyqtSlot
WebQUrl = QUrl
WEB_IMPORT_ERROR = None


# Bootstrap PyQt/WebEngine extrait dans pyqt_runtime (étape 1 démantèlement).
try:
    from . import pyqt_runtime
except ImportError:  # pragma: no cover - fallback import absolu (standalone)
    import pyqt_runtime  # type: ignore[no-redef]

_PYQT_VERSION = pyqt_runtime.PYQT_VERSION

try:
    QWebEngineView, QWebChannel, BridgeQObject, BridgeSlot, WebQUrl = pyqt_runtime.import_web_runtime()
except Exception as exc:
    WEB_IMPORT_ERROR = exc


class QgisBridge(BridgeQObject):
    """Bridge between the embedded web app and the active QGIS session."""

    DIAGNOSTIC_SAMPLE_LIMIT = 1500
    MAX_LAYER_IMPORT_LOGS = 50

    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        # Log des erreurs d'import de couche pour diagnostic
        self._layer_import_logs: list = []

    def _find_layer(self, layer_ref):
        if not layer_ref:
            return None

        layers = QgsProject.instance().mapLayersByName(layer_ref)
        if layers:
            return layers[0]

        return QgsProject.instance().mapLayer(layer_ref)

    def _notify(self, message, level=Qgis.Info, duration=4):
        self.iface.messageBar().pushMessage("QGISAI+", message, level=level, duration=duration)
        QgsMessageLog.logMessage(message, "QGISAI+", level=level)

    def _layer_node(self, layer):
        if layer is None:
            return None

        return QgsProject.instance().layerTreeRoot().findLayer(layer.id())

    def _layer_opacity(self, layer):
        if layer is None:
            return 1.0

        if hasattr(layer, "opacity"):
            try:
                return float(layer.opacity())
            except Exception:
                pass

        renderer = getattr(layer, "renderer", lambda: None)()
        if renderer is not None and hasattr(renderer, "opacity"):
            try:
                return float(renderer.opacity())
            except Exception:
                pass

        return 1.0

    def _apply_layer_opacity(self, layer, opacity_value):
        clamped_opacity = max(0.0, min(1.0, float(opacity_value)))
        applied = False

        if hasattr(layer, "setOpacity"):
            try:
                layer.setOpacity(clamped_opacity)
                applied = True
            except Exception:
                applied = False

        if not applied:
            renderer = getattr(layer, "renderer", lambda: None)()
            if renderer is not None and hasattr(renderer, "setOpacity"):
                renderer.setOpacity(clamped_opacity)
                applied = True

        if not applied:
            return False

        layer.triggerRepaint()

        layer_tree_view = getattr(self.iface, "layerTreeView", lambda: None)()
        if layer_tree_view is not None and hasattr(layer_tree_view, "refreshLayerSymbology"):
            layer_tree_view.refreshLayerSymbology(layer.id())

        self.iface.mapCanvas().refresh()
        return True

    def _layer_summary(self, layer):
        layer_type = "unknown"
        geometry_type = ""

        if layer.type() == QgsMapLayerType.VectorLayer:
            layer_type = "vector"
        elif layer.type() == QgsMapLayerType.RasterLayer:
            layer_type = "raster"
        elif layer.type() == QgsMapLayerType.MeshLayer:
            layer_type = "mesh"
        elif layer.type() == QgsMapLayerType.VectorTileLayer:
            layer_type = "vector-tile"
        elif layer.type() == QgsMapLayerType.PointCloudLayer:
            layer_type = "point-cloud"
        elif layer.type() == QgsMapLayerType.AnnotationLayer:
            layer_type = "annotation"
        elif layer.type() == QgsMapLayerType.PluginLayer:
            layer_type = "plugin"

        if isinstance(layer, QgsVectorLayer):
            geometry_type = QgsWkbTypes.geometryDisplayString(layer.geometryType())

        feature_count = None
        selected_feature_count = 0
        subset_string = ""
        editable = False

        if isinstance(layer, QgsVectorLayer):
            feature_count = int(layer.featureCount())
            selected_feature_count = int(layer.selectedFeatureCount())
            subset_string = layer.subsetString() or ""
            editable = bool(layer.isEditable())

        layer_node = self._layer_node(layer)
        is_visible = True if layer_node is None else bool(layer_node.itemVisibilityChecked())

        return {
            "id": layer.id(),
            "name": layer.name(),
            "type": layer_type,
            "geometryType": geometry_type,
            "crs": layer.crs().authid() if layer.crs().isValid() else "",
            "featureCount": feature_count,
            "selectedFeatureCount": selected_feature_count,
            "visible": is_visible,
            "opacity": round(self._layer_opacity(layer), 3),
            "subsetString": subset_string,
            "provider": layer.providerType() if hasattr(layer, "providerType") else "",
            "editable": editable,
        }

    def _extent_payload(self, layer):
        if layer is None:
            return None

        extent = layer.extent()
        if extent is None or extent.isEmpty():
            return None

        return {
            "xmin": extent.xMinimum(),
            "ymin": extent.yMinimum(),
            "xmax": extent.xMaximum(),
            "ymax": extent.yMaximum(),
        }

    def _layer_diagnostics(self, layer):
        summary = self._layer_summary(layer)
        diagnostics = {
            "layerId": summary["id"],
            "layerName": summary["name"],
            "layerType": summary["type"],
            "geometryType": summary["geometryType"],
            "crs": summary["crs"],
            "featureCount": summary["featureCount"],
            "selectedFeatureCount": summary["selectedFeatureCount"],
            "sampledFeatureCount": 0,
            "isSampled": False,
            "invalidGeometryCount": 0,
            "emptyGeometryCount": 0,
            "subsetString": summary["subsetString"],
            "extent": self._extent_payload(layer),
            "warnings": [],
            "fieldDiagnostics": [],
        }

        if not isinstance(layer, QgsVectorLayer):
            diagnostics["warnings"].append(
                "Diagnostic détaillé disponible principalement pour les couches vectorielles."
            )
            return diagnostics

        feature_count = int(layer.featureCount())
        sampled_feature_count = min(feature_count, self.DIAGNOSTIC_SAMPLE_LIMIT)
        is_sampled = feature_count > self.DIAGNOSTIC_SAMPLE_LIMIT
        field_names = [field.name() for field in layer.fields()]
        field_null_counts = {field_name: 0 for field_name in field_names}
        invalid_geometry_count = 0
        empty_geometry_count = 0

        for index, feature in enumerate(layer.getFeatures()):
            if index >= self.DIAGNOSTIC_SAMPLE_LIMIT:
                break

            geometry = feature.geometry()
            if geometry is None or geometry.isNull():
                empty_geometry_count += 1
            else:
                try:
                    if geometry.isEmpty():
                        empty_geometry_count += 1
                    elif not geometry.isGeosValid():
                        invalid_geometry_count += 1
                except Exception:
                    pass

            for field_name in field_names:
                raw_value = feature[field_name]
                if raw_value in (None, ""):
                    field_null_counts[field_name] += 1

        denominator = sampled_feature_count or 1
        field_diagnostics = []
        for field in layer.fields():
            null_count = field_null_counts.get(field.name(), 0)
            field_diagnostics.append(
                {
                    "name": field.name(),
                    "type": field.typeName(),
                    "nullCount": null_count,
                    "fillRate": round(max(0.0, 1.0 - (null_count / denominator)), 4),
                }
            )

        warnings = []
        if feature_count == 0:
            warnings.append("La couche est vide.")
        if summary["selectedFeatureCount"] == 0:
            warnings.append("Aucune entité n'est sélectionnée.")
        if invalid_geometry_count > 0:
            warnings.append(
                f"{invalid_geometry_count} géométrie(s) invalide(s) détectée(s) sur l'échantillon."
            )
        if empty_geometry_count > 0:
            warnings.append(
                f"{empty_geometry_count} géométrie(s) vide(s) ou nulles détectée(s) sur l'échantillon."
            )
        sparse_fields = [
            field["name"]
            for field in field_diagnostics
            if field["fillRate"] < 0.6
        ]
        if sparse_fields:
            warnings.append(
                "Champs peu renseignés : " + ", ".join(sparse_fields[:6])
            )
        if is_sampled:
            warnings.append(
                f"Diagnostic calculé sur un échantillon de {sampled_feature_count} entités."
            )

        diagnostics.update(
            {
                "sampledFeatureCount": sampled_feature_count,
                "isSampled": is_sampled,
                "invalidGeometryCount": invalid_geometry_count,
                "emptyGeometryCount": empty_geometry_count,
                "warnings": warnings,
                "fieldDiagnostics": field_diagnostics,
            }
        )
        return diagnostics

    def _encode_uri(self, params):
        normalized = {}
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, bool):
                normalized[key] = "1" if value else "0"
            else:
                normalized[key] = str(value)

        return urlencode(normalized, doseq=True)

    def _encode_qgis_uri(self, params):
        uri = QgsDataSourceUri()
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, bool):
                uri.setParam(key, "1" if value else "0")
            else:
                uri.setParam(key, str(value))

        encoded = uri.encodedUri()
        if isinstance(encoded, bytes):
            return encoded.decode("utf-8")
        return str(encoded)

    def _log_layer_import_error(self, source: str, error_message: str, layer_name: str = None):
        """Log une erreur d'import de couche pour diagnostic."""
        import datetime
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "source": source,
            "layer_name": layer_name or "Unknown",
            "error": error_message,
        }
        self._layer_import_logs.append(log_entry)
        # Garder seulement les MAX_LAYER_IMPORT_LOGS derniers
        if len(self._layer_import_logs) > self.MAX_LAYER_IMPORT_LOGS:
            self._layer_import_logs = self._layer_import_logs[-self.MAX_LAYER_IMPORT_LOGS:]
        # Also log to QGIS message log
        QgsMessageLog.logMessage(
            f"Layer import error [{source}]: {error_message}",
            "QGISAI+",
            level=Qgis.Warning
        )

    def _add_layer_to_project(self, layer, layer_name=None, source: str = "Unknown"):
        if layer is None:
            error_msg = "Layer is None"
            self._log_layer_import_error(source, error_msg, layer_name)
            return None

        if not layer.isValid():
            error_msg = self._layer_error_message(layer) or "Layer is invalid (no details)"
            self._log_layer_import_error(source, error_msg, layer_name or layer.name())
            return None

        if layer_name:
            layer.setName(layer_name)

        QgsProject.instance().addMapLayer(layer)
        return layer

    def _layer_error_message(self, layer):
        if layer is None:
            return ""

        details = []

        try:
            layer_error = layer.error()
            summary = getattr(layer_error, "summary", None)
            message = getattr(layer_error, "message", None)
            if callable(summary):
                details.append(str(summary() or "").strip())
            if callable(message):
                details.append(str(message() or "").strip())
        except Exception:
            pass

        try:
            provider = layer.dataProvider()
            if provider is not None and hasattr(provider, "error"):
                provider_error = provider.error()
                provider_summary = getattr(provider_error, "summary", None)
                provider_message = getattr(provider_error, "message", None)
                if callable(provider_summary):
                    details.append(str(provider_summary() or "").strip())
                if callable(provider_message):
                    details.append(str(provider_message() or "").strip())
        except Exception:
            pass

        normalized = [entry for entry in details if entry]
        if not normalized:
            return ""

        return " | ".join(dict.fromkeys(normalized))

    def _ensure_raster_layer(self, layer_ref):
        layer = self._find_layer(layer_ref)
        if layer is None or layer.type() != QgsMapLayerType.RasterLayer:
            return None
        return layer

    def _resolve_output_destination(self, output_path):
        if not output_path:
            return "TEMPORARY_OUTPUT"

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        return str(output_file)

    def _runtime_directory(self):
        runtime_dir = Path(tempfile.gettempdir()) / "geoai_qgis_runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return runtime_dir

    def _write_temp_geojson(self, geojson_text, layer_name):
        safe_name = "".join(
            character if character.isalnum() or character in ("_", "-") else "_"
            for character in (layer_name or "geojson")
        ).strip("_") or "geojson"
        target = self._runtime_directory() / f"{safe_name}.geojson"
        target.write_text(geojson_text, encoding="utf-8")
        return str(target)

    def _refresh_layer_rendering(self, layer):
        if layer is None:
            return

        layer.triggerRepaint()
        layer_tree_view = getattr(self.iface, "layerTreeView", lambda: None)()
        if layer_tree_view is not None and hasattr(layer_tree_view, "refreshLayerSymbology"):
            layer_tree_view.refreshLayerSymbology(layer.id())
        self.iface.mapCanvas().refresh()

    def _guess_label_field(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            return ""

        field_names = [field.name() for field in layer.fields()]
        preferred_fields = [
            "numero",
            "idu",
            "id",
            "section",
            "nom",
            "name",
            "code",
            "code_insee",
        ]
        normalized_fields = {field_name.lower(): field_name for field_name in field_names}

        for preferred_field in preferred_fields:
            if preferred_field in normalized_fields:
                return normalized_fields[preferred_field]

        return field_names[0] if field_names else ""

    def _create_service_layer(self, config):
        service_type = str(config.get("serviceType", "")).strip()
        layer_name = str(config.get("name", "")).strip() or "Service distant"
        url = str(config.get("url", "")).strip()
        layer_ref = str(config.get("layerName", "")).strip()
        style = str(config.get("style", "")).strip()
        image_format = str(config.get("format", "")).strip() or "image/png"
        crs = str(config.get("crs", "")).strip()
        tile_matrix_set = str(config.get("tileMatrixSet", "")).strip()
        version = str(config.get("version", "")).strip() or "2.0.0"
        z_min = config.get("zMin")
        z_max = config.get("zMax")

        if not service_type or not url:
            raise ValueError("Configuration de service distante incomplète.")

        if service_type in ("XYZ", "TMS"):
            uri = self._encode_uri(
                {
                    "type": "xyz",
                    "url": url,
                    "zmin": z_min if z_min is not None else 0,
                    "zmax": z_max if z_max is not None else 22,
                }
            )
            return QgsRasterLayer(uri, layer_name, "wms")

        if service_type == "WMS":
            uri = self._encode_qgis_uri(
                {
                    "contextualWMSLegend": 0,
                    "crs": crs or "EPSG:3857",
                    "dpiMode": 7,
                    "featureCount": 10,
                    "format": image_format,
                    "layers": layer_ref,
                    "styles": style,
                    "url": url,
                }
            )
            return QgsRasterLayer(uri, layer_name, "wms")

        if service_type == "WMTS":
            wmts_url = url
            if "GetCapabilities" not in wmts_url and "WMTSCapabilities.xml" not in wmts_url:
                separator = "&" if "?" in wmts_url else "?"
                wmts_url = (
                    f"{wmts_url}{separator}SERVICE=WMTS&REQUEST=GetCapabilities"
                )
            uri = self._encode_qgis_uri(
                {
                    "contextualWMSLegend": 0,
                    "crs": crs or "EPSG:3857",
                    "dpiMode": 7,
                    "featureCount": 10,
                    "format": image_format,
                    "layers": layer_ref,
                    "styles": style or "default",
                    "type": "wmts",
                    "tileMatrixSet": tile_matrix_set or "PM",
                    "url": wmts_url,
                }
            )
            return QgsRasterLayer(uri, layer_name, "wms")

        if service_type == "WFS":
            query = unquote(
                urlencode(
                    {
                        "service": "WFS",
                        "version": version,
                        "request": "GetFeature",
                        "typename": layer_ref,
                        "srsname": crs or "EPSG:4326",
                    }
                )
            )
            separator = "&" if "?" in url else "?"
            uri = f"{url}{separator}{query}"
            return QgsVectorLayer(uri, layer_name, "WFS")

        if service_type == "WCS":
            uri = self._encode_qgis_uri(
                {
                    "url": url,
                    "identifier": layer_ref,
                    "crs": crs or "",
                    "format": image_format or "image/tiff",
                    "version": version,
                }
            )
            return QgsRasterLayer(uri, layer_name, "wcs")

        if service_type == "ArcGISMapServer":
            return QgsRasterLayer(url, layer_name, "arcgismapserver")

        if service_type == "ArcGISFeatureServer":
            return QgsVectorLayer(url, layer_name, "arcgisfeatureserver")

        raise ValueError(f"Type de service non supporté: {service_type}")

    def _run_raster_calculator(self, raster_layers, formula, output_name, output_path):
        if len(raster_layers) == 0 or len(raster_layers) > 6:
            raise ValueError("Le calcul raster attend entre 1 et 6 rasters.")

        params = {
            "FORMULA": formula,
            "NO_DATA": -9999,
            "EXTENT_OPT": 3,
            "RTYPE": 5,
            "CREATION_OPTIONS": "COMPRESS=LZW",
            "OUTPUT": self._resolve_output_destination(output_path),
        }

        for index, layer in enumerate(raster_layers):
            letter = "ABCDEF"[index]
            params[f"INPUT_{letter}"] = layer.source()
            params[f"BAND_{letter}"] = 1

        result = processing.run("gdal:rastercalculator", params, feedback=QgsProcessingFeedback())
        output = result.get("OUTPUT")
        output_value = str(output)
        raster_layer = QgsRasterLayer(output_value, output_name)
        if not raster_layer.isValid():
            raise RuntimeError("Le raster calculé n'est pas exploitable.")

        self._add_layer_to_project(raster_layer, output_name, source="RasterCalculator")
        return {
            "outputLayerName": raster_layer.name(),
            "outputPath": output_value,
            "formula": formula,
        }

    def _run_raster_band_merge(self, raster_layers, output_name, output_path):
        if len(raster_layers) < 2:
            raise ValueError("La fusion multi-bandes attend au moins 2 rasters.")

        params = {
            "INPUT": [layer.source() for layer in raster_layers],
            "PCT": False,
            "SEPARATE": True,
            "NODATA_INPUT": None,
            "NODATA_OUTPUT": -9999,
            "OPTIONS": "COMPRESS=LZW",
            "EXTRA": "",
            "DATA_TYPE": 0,
            "OUTPUT": self._resolve_output_destination(output_path),
        }

        result = processing.run("gdal:merge", params, feedback=QgsProcessingFeedback())
        output = result.get("OUTPUT")
        output_value = str(output)
        raster_layer = QgsRasterLayer(output_value, output_name)
        if not raster_layer.isValid():
            raise RuntimeError("Le raster fusionne n'est pas exploitable.")

        self._add_layer_to_project(raster_layer, output_name, source="RasterMerge")
        return {
            "outputLayerName": raster_layer.name(),
            "outputPath": output_value,
            "inputLayers": [layer.name() for layer in raster_layers],
            "separateBands": True,
        }

    def _run_inventory_grid(
        self,
        source_layer,
        cell_width,
        cell_height,
        grid_name,
        centroids_name,
        clip_to_source,
    ):
        if source_layer is None:
            raise ValueError("Couche source introuvable pour creer la grille.")

        cell_width = float(cell_width)
        cell_height = float(cell_height)
        if cell_width <= 0 or cell_height <= 0:
            raise ValueError("La taille de maille doit etre strictement positive.")

        grid_result = processing.run(
            "native:creategrid",
            {
                "TYPE": 2,
                "EXTENT": source_layer.extent(),
                "HSPACING": cell_width,
                "VSPACING": cell_height,
                "HOVERLAY": 0,
                "VOVERLAY": 0,
                "CRS": source_layer.crs(),
                "OUTPUT": "memory:",
            },
            feedback=QgsProcessingFeedback(),
        )
        grid_layer = grid_result.get("OUTPUT")
        if grid_layer is None:
            raise RuntimeError("La grille d'inventaire n'a pas ete produite.")

        clipped = False
        if (
            clip_to_source
            and isinstance(source_layer, QgsVectorLayer)
            and source_layer.geometryType() == QgsWkbTypes.PolygonGeometry
        ):
            clip_result = processing.run(
                "native:clip",
                {
                    "INPUT": grid_layer,
                    "OVERLAY": source_layer,
                    "OUTPUT": "memory:",
                },
                feedback=QgsProcessingFeedback(),
            )
            grid_layer = clip_result.get("OUTPUT")
            clipped = True

        if grid_layer is None:
            raise RuntimeError("La grille clippee n'est pas exploitable.")

        grid_layer.setName(grid_name)
        QgsProject.instance().addMapLayer(grid_layer)
        self._refresh_layer_rendering(grid_layer)

        centroids_result = processing.run(
            "native:centroids",
            {
                "INPUT": grid_layer,
                "ALL_PARTS": False,
                "OUTPUT": "memory:",
            },
            feedback=QgsProcessingFeedback(),
        )
        centroid_layer = centroids_result.get("OUTPUT")
        if centroid_layer is None:
            raise RuntimeError("Les centroides n'ont pas pu etre generes.")

        centroid_layer.setName(centroids_name)
        QgsProject.instance().addMapLayer(centroid_layer)
        self._refresh_layer_rendering(centroid_layer)

        return {
            "gridLayerName": grid_layer.name(),
            "centroidLayerName": centroid_layer.name(),
            "sourceLayerName": source_layer.name(),
            "cellWidth": cell_width,
            "cellHeight": cell_height,
            "clipped": clipped,
        }

    @BridgeSlot()
    def openLayers(self):
        self.iface.showLayerPanel()
        self._notify("Panneau des couches ouvert.", Qgis.Info)

    @BridgeSlot()
    def openSettings(self):
        self._notify(
            "Les paramètres du modèle se configurent depuis l'interface QGISAI+.",
            Qgis.Info,
        )

    @BridgeSlot(str, str, result=str)
    def pickFile(self, file_filter, title):
        selected_file, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            str(title or "Choisir un fichier"),
            "",
            str(file_filter or "Tous les fichiers (*.*)"),
        )
        return selected_file or ""

    @BridgeSlot(result=list)
    def getLayersList(self):
        return [layer.name() for layer in QgsProject.instance().mapLayers().values()]

    @BridgeSlot(result=str)
    def getLayersCatalog(self):
        ordered_layers = QgsProject.instance().layerTreeRoot().layerOrder()
        if not ordered_layers:
            ordered_layers = list(QgsProject.instance().mapLayers().values())

        payload = [self._layer_summary(layer) for layer in ordered_layers]
        return json.dumps(payload, ensure_ascii=False)

    @BridgeSlot(str, result=list)
    def getLayerFields(self, layer_ref):
        layer = self._find_layer(layer_ref)
        if not isinstance(layer, QgsVectorLayer):
            return []

        return [field.name() for field in layer.fields()]

    @BridgeSlot(str, result=str)
    def getLayerDiagnostics(self, layer_ref):
        layer = self._find_layer(layer_ref)
        if layer is None:
            return ""

        return json.dumps(self._layer_diagnostics(layer), ensure_ascii=False)

    @BridgeSlot(str, str, result=str)
    def filterLayer(self, layer_ref, subset_string):
        layer = self._find_layer(layer_ref)
        if layer is None:
            message = "Couche introuvable."
            self._notify(message, Qgis.Warning)
            return message

        if not hasattr(layer, "setSubsetString"):
            message = "Cette couche ne supporte pas les filtres attributaires."
            self._notify(message, Qgis.Warning)
            return message

        layer.setSubsetString(subset_string)
        message = f"Filtre appliqué sur {layer.name()}."
        self._notify(message, Qgis.Success)
        return message

    @BridgeSlot(str, bool, result=str)
    def setLayerVisibility(self, layer_ref, is_visible):
        layer = self._find_layer(layer_ref)
        layer_node = self._layer_node(layer)
        if layer is None or layer_node is None:
            message = "Couche introuvable."
            self._notify(message, Qgis.Warning)
            return message

        layer_node.setItemVisibilityChecked(bool(is_visible))
        self.iface.mapCanvas().refresh()

        message = f"{layer.name()} {'affichée' if is_visible else 'masquée'}."
        self._notify(message, Qgis.Info)
        return message

    @BridgeSlot(str, float, result=str)
    def setLayerOpacity(self, layer_ref, opacity_value):
        layer = self._find_layer(layer_ref)
        if layer is None:
            message = "Couche introuvable."
            self._notify(message, Qgis.Warning)
            return message

        opacity = max(0.0, min(1.0, float(opacity_value)))
        if not self._apply_layer_opacity(layer, opacity):
            message = "Impossible de modifier l'opacité de cette couche."
            self._notify(message, Qgis.Warning)
            return message

        message = f"Opacité de {layer.name()} réglée à {int(round(opacity * 100))}%."
        self._notify(message, Qgis.Success)
        return message

    @BridgeSlot(str, result=str)
    def zoomToLayer(self, layer_ref):
        layer = self._find_layer(layer_ref)
        if layer is None:
            message = "Couche introuvable."
            self._notify(message, Qgis.Warning)
            return message

        self.iface.setActiveLayer(layer)
        self.iface.zoomToActiveLayer()
        message = f"Vue centrée sur {layer.name()}."
        self._notify(message, Qgis.Info)
        return message

    @BridgeSlot(str, result=str)
    def setMapExtent(self, bbox):
        """Cadre la vue sur une emprise/point WGS84.

        bbox : 'minlon,minlat,maxlon,maxlat' (emprise) ou 'lon,lat' (point ->
        petite emprise auto). Indispensable pour cadrer sur un lieu géocodé,
        car zoomToLayer sur un fond mondial (OSM) affiche le monde entier.
        """
        try:
            parts = [float(x) for x in str(bbox).replace(";", ",").split(",") if x.strip()]
        except ValueError:
            return "bbox invalide (nombres attendus)"

        if len(parts) == 2:
            lon, lat = parts
            margin = 0.05
            rect = QgsRectangle(lon - margin, lat - margin, lon + margin, lat + margin)
        elif len(parts) == 4:
            xmin, ymin, xmax, ymax = parts
            rect = QgsRectangle(xmin, ymin, xmax, ymax)
        else:
            return "bbox invalide (attendu 'minlon,minlat,maxlon,maxlat' ou 'lon,lat')"

        canvas = self.iface.mapCanvas()
        try:
            dst = canvas.mapSettings().destinationCrs()
            src = QgsCoordinateReferenceSystem("EPSG:4326")
            if dst.isValid() and src != dst:
                transform = QgsCoordinateTransform(src, dst, QgsProject.instance())
                rect = transform.transformBoundingBox(rect)
            rect.scale(1.1)  # légère marge
            canvas.setExtent(rect)
            canvas.refresh()
        except Exception as exc:  # noqa: BLE001
            return f"Erreur cadrage: {exc}"

        message = "Vue cadrée sur l'emprise demandée."
        self._notify(message, Qgis.Info)
        return message

    @BridgeSlot(str, str, result=str)
    def renameLayer(self, layer_ref, new_name):
        """Renomme une couche (nom affiché dans le panneau)."""
        layer = self._find_layer(layer_ref)
        if layer is None:
            return "Couche introuvable."
        new_name = (new_name or "").strip()
        if not new_name:
            return "Nom vide."
        old = layer.name()
        layer.setName(new_name)
        message = f"Couche '{old}' renommee en '{new_name}'."
        self._notify(message, Qgis.Info)
        return message

    @BridgeSlot(str, str, result=str)
    def setLayerGroup(self, layer_ref, group_name):
        """Range une couche dans un groupe nommé du panneau (cree le groupe si besoin).

        Permet une organisation pro de l'arbre des couches : fonds de carte,
        donnees, analyses, etc. dans des groupes clairs.
        """
        layer = self._find_layer(layer_ref)
        if layer is None:
            return "Couche introuvable."
        group_name = (group_name or "").strip() or "Groupe"
        try:
            root = QgsProject.instance().layerTreeRoot()
            group = root.findGroup(group_name)
            if group is None:
                group = root.addGroup(group_name)
            node = root.findLayer(layer.id())
            if node is None:
                return "Noeud de couche introuvable."
            # Déjà dans le bon groupe ?
            if node.parent() is group:
                return f"Couche deja dans '{group_name}'."
            cloned = node.clone()
            group.insertChildNode(0, cloned)
            parent = node.parent()
            if parent is not None:
                parent.removeChildNode(node)
        except Exception as exc:  # noqa: BLE001
            return f"Erreur groupe: {exc}"
        message = f"Couche '{layer.name()}' rangee dans le groupe '{group_name}'."
        self._notify(message, Qgis.Info)
        return message

    @BridgeSlot(str, str, result=str)
    def getLayerStatistics(self, layer_ref, field_name):
        layer = self._find_layer(layer_ref)
        if not isinstance(layer, QgsVectorLayer):
            return ""

        field_index = layer.fields().indexOf(field_name)
        if field_index == -1:
            return ""

        values = []
        for feature in layer.getFeatures():
            raw_value = feature[field_index]
            if raw_value in (None, ""):
                continue
            try:
                values.append(float(raw_value))
            except (TypeError, ValueError):
                continue

        if not values:
            return ""

        count = len(values)
        total = sum(values)
        mean = total / count
        minimum = min(values)
        maximum = max(values)

        payload = {
            "count": count,
            "sum": total,
            "mean": mean,
            "min": minimum,
            "max": maximum,
            "range": maximum - minimum,
            "sampleStandardDeviation": statistics.stdev(values) if count > 1 else 0.0,
            "populationStandardDeviation": statistics.pstdev(values) if count > 0 else 0.0,
        }

        return json.dumps(payload)

    @BridgeSlot(result=str)
    def captureMapSnapshot(self):
        """
        Capture la carte courante et retourne une data-URL base64 PNG.
        Utilisé après chaque modification pour montrer le résultat dans le chat.
        """
        try:
            import base64

            temp_path = self._capture_map_snapshot()
            if not temp_path or not os.path.exists(temp_path):
                return ""

            with open(temp_path, "rb") as f:
                png_bytes = f.read()

            os.unlink(temp_path)

            b64 = base64.b64encode(png_bytes).decode("utf-8")
            return f"data:image/png;base64,{b64}"
        except Exception:
            return ""

    @BridgeSlot(str, str, result=str)
    def reprojectLayer(self, layer_ref, target_crs_authid):
        layer = self._find_layer(layer_ref)
        if not isinstance(layer, QgsVectorLayer):
            return ""

        target_crs = QgsCoordinateReferenceSystem(target_crs_authid)
        if not target_crs.isValid():
            self._notify("CRS cible invalide.", Qgis.Warning)
            return ""

        try:
            result = processing.run(
                "native:reprojectlayer",
                {
                    "INPUT": layer,
                    "TARGET_CRS": target_crs,
                    "OUTPUT": "memory:",
                },
                feedback=QgsProcessingFeedback(),
            )
        except Exception:
            QgsMessageLog.logMessage(
                traceback.format_exc(),
                "GeoAI",
                level=Qgis.Critical,
            )
            self._notify("La reprojection a échoué.", Qgis.Critical, duration=6)
            return ""

        output_layer = result.get("OUTPUT")
        if output_layer is None:
            return ""

        output_layer.setName(f"{layer.name()}_{target_crs.authid().replace(':', '_')}")
        QgsProject.instance().addMapLayer(output_layer)
        self._notify(f"Couche reprojetée créée : {output_layer.name()}.", Qgis.Success)
        return output_layer.name()

    @BridgeSlot(str, result=str)
    def addServiceLayer(self, config_json):
        try:
            config = json.loads(config_json) if config_json else {}
        except json.JSONDecodeError:
            message = "Configuration de service distante invalide."
            self._notify(message, Qgis.Warning)
            return message

        try:
            layer = self._create_service_layer(config)
        except Exception as exc:
            message = f"Impossible de préparer le service distant : {exc}"
            self._notify(message, Qgis.Warning, duration=6)
            return message

        service_type = config.get("service_type", "Unknown")
        if self._add_layer_to_project(layer, config.get("name"), source=f"RemoteService:{service_type}") is None:
            reason = self._layer_error_message(layer)
            message = "Le service distant n'a pas pu être chargé dans QGIS."
            if reason:
                message = f"{message} Cause: {reason}"
            self._notify(message, Qgis.Warning, duration=6)
            return message

        message = f"Service ajouté : {layer.name()}."
        self._notify(message, Qgis.Success)
        return message

    @BridgeSlot(str, str, result=str)
    def addDataSource(self, source_id, layer_name):
        """Charge une source du catalogue mondial (config/data_sources.json) dans QGIS.

        Adapte la config generique de data_catalog vers le schema attendu par
        _create_service_layer (serviceType / layerName / zMin / zMax camelCase).
        """
        try:
            from data_catalog import get_source, build_service_config
        except ImportError:
            from .data_catalog import get_source, build_service_config

        source = get_source(str(source_id or "").strip())
        if source is None:
            message = f"Source de donnees inconnue : {source_id}"
            self._notify(message, Qgis.Warning)
            return message

        generic = build_service_config(source)
        st = generic.get("service_type", "")
        qgis_cfg = {
            "serviceType": st,
            "url": generic.get("url", ""),
            "name": str(layer_name or "").strip() or generic.get("name", source["id"]),
        }
        if st in ("XYZ", "TMS"):
            qgis_cfg["zMin"] = generic.get("zmin", 0)
            qgis_cfg["zMax"] = generic.get("zmax", 22)
        elif st == "WMS":
            qgis_cfg["layerName"] = generic.get("layers", "")
            qgis_cfg["format"] = generic.get("format", "image/png")
            qgis_cfg["crs"] = generic.get("crs", "EPSG:3857")
        elif st == "WMTS":
            qgis_cfg["layerName"] = generic.get("layer", "")
            qgis_cfg["tileMatrixSet"] = generic.get("tileMatrixSet", "PM")
            qgis_cfg["format"] = generic.get("format", "image/png")
            qgis_cfg["style"] = generic.get("style", "normal")
        elif st == "WFS":
            qgis_cfg["layerName"] = generic.get("layer", "")
            qgis_cfg["crs"] = generic.get("crs", "EPSG:4326")
            qgis_cfg["version"] = generic.get("version", "2.0.0")

        try:
            layer = self._create_service_layer(qgis_cfg)
        except Exception as exc:  # noqa: BLE001
            message = f"Impossible de preparer la source : {exc}"
            self._notify(message, Qgis.Warning, duration=6)
            return message

        if self._add_layer_to_project(layer, qgis_cfg.get("name"),
                                      source=f"Catalog:{source['id']}") is None:
            reason = self._layer_error_message(layer)
            message = f"La source '{source['id']}' n'a pas pu etre chargee."
            if reason:
                message = f"{message} Cause: {reason}"
            self._notify(message, Qgis.Warning, duration=6)
            return message

        message = f"Source ajoutee : {layer.name()} ({source.get('provider', '')})."
        self._notify(message, Qgis.Success)
        return message

    def _find_vector_layer_with_field(self, field_name):
        """Retourne le NOM d'une couche vectorielle ayant le champ donne, sinon None."""
        if not field_name:
            return None
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.fields().indexOf(field_name) >= 0:
                return layer.name()
        return None

    @BridgeSlot(str, result=str)
    def runDossier(self, dossier_id):
        """Deroule un dossier territorial pre-assemble (P2, 1 clic) : charge les couches
        du catalogue et applique les symbologies institutionnelles. Renvoie un rapport JSON.
        """
        try:
            from dossier_blueprint import expand_dossier, get_dossier
        except ImportError:
            from .dossier_blueprint import expand_dossier, get_dossier

        dossier_id = str(dossier_id or "").strip()
        if get_dossier(dossier_id) is None:
            msg = f"Dossier inconnu : {dossier_id}"
            self._notify(msg, Qgis.Warning)
            return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)

        report = []
        for step in expand_dossier(dossier_id):
            action = step.get("action")
            if action == "addDataSource":
                m = self.addDataSource(step.get("sourceId", ""), "")
                report.append({"action": action, "target": step.get("sourceId"), "message": m})
            elif action == "applySymbologyPreset":
                field = step.get("field", "")
                target = self._find_vector_layer_with_field(field)
                if target is None:
                    report.append({
                        "action": action, "preset": step.get("presetId"), "skipped": True,
                        "message": f"Aucune couche vectorielle avec le champ '{field}' "
                                   "(symbologie a appliquer ulterieurement).",
                    })
                else:
                    m = self.applySymbologyPreset(target, step.get("presetId", ""), field)
                    report.append({"action": action, "preset": step.get("presetId"),
                                   "layer": target, "message": m})
            else:
                report.append({"action": action, "skipped": True, "message": "action inconnue"})

        loaded = sum(1 for r in report
                     if r.get("action") == "addDataSource" and "ajout" in r.get("message", "").lower())
        summary = (f"Dossier '{dossier_id}' deroule : {loaded} couche(s) chargee(s), "
                   f"{len(report)} etapes.")
        self._notify(summary, Qgis.Success)
        return json.dumps({"ok": True, "dossier": dossier_id, "steps": report,
                           "summary": summary}, ensure_ascii=False)

    @BridgeSlot(str, str, result=str)
    def addRasterFile(self, file_path, layer_name):
        file_path = str(file_path or "").strip()
        if not file_path or not Path(file_path).exists():
            message = "Fichier raster introuvable."
            self._notify(message, Qgis.Warning)
            return message

        final_name = str(layer_name or "").strip() or Path(file_path).stem
        layer = QgsRasterLayer(file_path, final_name)
        if self._add_layer_to_project(layer, final_name, source=f"FileImport:{file_path}") is None:
            message = "Le raster n'a pas pu être chargé."
            self._notify(message, Qgis.Warning)
            return message

        message = f"Raster chargé : {final_name}."
        self._notify(message, Qgis.Success)
        return message

    @BridgeSlot(str, str, result=str)
    def addRemoteRaster(self, url, layer_name):
        """Charge un raster distant (COG https, S3) dans QGIS via GDAL /vsicurl/.

        Permet d'amener une image satellite (Sentinel/Landsat trouvee via
        search_satellite_imagery) directement dans le projet (P3-S2).
        """
        url = str(url or "").strip()
        if not url:
            message = "URL de raster distante vide."
            self._notify(message, Qgis.Warning)
            return message
        try:
            from raster_remote import to_gdal_remote_path
        except ImportError:
            from .raster_remote import to_gdal_remote_path
        gdal_path = to_gdal_remote_path(url)
        final_name = str(layer_name or "").strip() or "Raster distant"
        layer = QgsRasterLayer(gdal_path, final_name)
        if not layer.isValid():
            reason = self._layer_error_message(layer) or url
            message = f"Raster distant invalide : {reason}"
            self._notify(message, Qgis.Warning, duration=6)
            return message
        if self._add_layer_to_project(layer, final_name, source=f"RemoteRaster:{url}") is None:
            message = "Le raster distant n'a pas pu etre charge."
            self._notify(message, Qgis.Warning, duration=6)
            return message
        message = f"Raster distant charge : {final_name}."
        self._notify(message, Qgis.Success)
        return message

    @BridgeSlot(str, str, str, str, result=str)
    def loadSatelliteBands(self, bbox, collection, bands_json, datetime):
        """Cherche une image satellite (STAC Earth Search) sur une emprise, choisit la
        moins nuageuse, et charge les bandes demandees (COG) dans QGIS. Enchainer avec
        computeSpectralIndex pour un NDVI sur vrai Sentinel (P1-S2)."""
        try:
            from native_tools import EARTH_SEARCH_STAC, _default_get_json
            from stac_assets import normalize_datetime, resolve_asset_href
            from stac_collections import asset_key_for
        except ImportError:
            from .native_tools import EARTH_SEARCH_STAC, _default_get_json
            from .stac_assets import normalize_datetime, resolve_asset_href
            from .stac_collections import asset_key_for

        bbox = str(bbox or "").strip()
        if not bbox:
            self._notify("Emprise (bbox) requise.", Qgis.Warning)
            return ""
        collection = str(collection or "").strip() or "sentinel-2-l2a"
        try:
            bands = json.loads(bands_json) if bands_json else ["RED", "NIR"]
        except json.JSONDecodeError:
            bands = ["RED", "NIR"]

        params = {"collections": collection, "bbox": bbox, "limit": 10}
        norm_dt = normalize_datetime(datetime)
        if norm_dt:
            params["datetime"] = norm_dt
        try:
            data = _default_get_json(EARTH_SEARCH_STAC, params)
        except Exception as exc:  # noqa: BLE001
            msg = f"Recherche STAC echouee : {exc}"
            self._notify(msg, Qgis.Warning, duration=6)
            return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)

        feats = (data or {}).get("features", []) or []
        if not feats:
            msg = "Aucune image satellite pour cette emprise/periode."
            self._notify(msg, Qgis.Warning)
            return json.dumps({"ok": False, "error": msg,
                               "stac_keys": list((data or {}).keys())}, ensure_ascii=False)
        feats.sort(key=lambda f: (f.get("properties", {}) or {}).get("eo:cloud_cover", 100))
        item = feats[0]

        # Resolution multi-capteurs : mapping bande->asset selon la collection
        # (stac_collections), avec repli generique (stac_assets).
        assets = item.get("assets", {}) or {}
        loaded = {}
        for band in bands:
            href = None
            key = asset_key_for(collection, band)
            if key and isinstance(assets.get(key), dict):
                href = assets[key].get("href")
            if not href:
                href = resolve_asset_href(item, band)
            if not href:
                continue
            name = f"{collection}_{band}"
            msg = self.addRemoteRaster(href, name)
            if "charge" in msg.lower():
                loaded[band] = name
        if not loaded:
            self._notify("Image trouvee mais aucune bande chargeable.", Qgis.Warning)
            return ""

        props = item.get("properties", {}) or {}
        self._notify(f"{len(loaded)} bande(s) chargee(s) (item {item.get('id')}).", Qgis.Success)
        return json.dumps({
            "ok": True, "item": item.get("id"),
            "datetime": props.get("datetime"),
            "cloud_cover": props.get("eo:cloud_cover"),
            "bands": loaded,
        }, ensure_ascii=False)

    @BridgeSlot(str, str, result=str)
    def addGeoJsonLayer(self, geojson_text, layer_name):
        geojson_text = str(geojson_text or "").strip()
        if not geojson_text:
            message = "GeoJSON vide."
            self._notify(message, Qgis.Warning)
            return message

        try:
            parsed = json.loads(geojson_text)
            normalized_geojson = json.dumps(parsed, ensure_ascii=False)
        except Exception:
            message = "GeoJSON invalide."
            self._notify(message, Qgis.Warning)
            return message

        final_name = str(layer_name or "").strip() or "GeoJSON"
        file_path = self._write_temp_geojson(normalized_geojson, final_name)
        layer = QgsVectorLayer(file_path, final_name, "ogr")
        if self._add_layer_to_project(layer, final_name, source="GeoJSONImport") is None:
            message = "Le GeoJSON n'a pas pu etre charge."
            self._notify(message, Qgis.Warning)
            return message

        message = f"Couche GeoJSON ajoutee : {final_name}."
        self._notify(message, Qgis.Success)
        return message

    @BridgeSlot(str, result=str)
    def segmentRasterWithSAM(self, options_json):
        """
        Segmente un raster avec Segment Anything (samgeo) puis charge le
        GeoJSON résultat dans QGIS comme nouvelle couche.

        options_json : JSON sérialisé avec rasterPath, outputGeojson, mode,
        textPrompt, model, minAreaPx, layerName.
        """
        try:
            opts = json.loads(options_json) if options_json else {}
        except json.JSONDecodeError:
            message = "Options SAM invalides (JSON malforme)."
            self._notify(message, Qgis.Warning)
            return message

        raster_path = str(opts.get("rasterPath") or "").strip()
        output_geojson = str(opts.get("outputGeojson") or "").strip()
        if not raster_path or not output_geojson:
            message = "rasterPath et outputGeojson sont requis."
            self._notify(message, Qgis.Warning)
            return message

        # Import lazy + dégradation gracieuse
        try:
            from .samgeo_tool import (
                segment_raster_to_geojson,
                SAMGeoUnavailableError,
            )
        except ImportError as e:
            message = f"Module samgeo_tool indisponible : {e}"
            self._notify(message, Qgis.Critical)
            return message

        try:
            result = segment_raster_to_geojson(
                raster_path,
                output_geojson,
                mode=opts.get("mode") or "automatic",
                text_prompt=opts.get("textPrompt"),
                model=opts.get("model") or "vit_h",
                min_area_px=int(opts.get("minAreaPx") or 200),
            )
        except SAMGeoUnavailableError as e:
            message = f"SAM indisponible : {e}. Installe via 'pip install samgeo torch'."
            self._notify(message, Qgis.Critical)
            return message
        except FileNotFoundError as e:
            message = f"Raster introuvable : {e}"
            self._notify(message, Qgis.Warning)
            return message
        except Exception as e:  # noqa: BLE001
            message = f"Echec segmentation SAM : {e}"
            self._notify(message, Qgis.Critical)
            return message

        # Charge le GeoJSON résultat comme couche QGIS
        layer_name = str(opts.get("layerName") or "").strip() or "SAM_segmentation"
        try:
            with open(result.geojson_path, "r", encoding="utf-8") as f:
                geojson_text = f.read()
            self.addGeoJsonLayer(geojson_text, layer_name)
        except Exception as e:  # noqa: BLE001
            message = f"Segmentation OK mais chargement couche echoue : {e}"
            self._notify(message, Qgis.Warning)
            return message

        message = (
            f"{result.feature_count} polygones SAM ajoutes a QGIS "
            f"(couche '{layer_name}', {result.duration_s:.1f}s)."
        )
        self._notify(message, Qgis.Success)
        return message

    @BridgeSlot(str, result=str)
    def forecastWeatherWithEarth2(self, options_json):
        """
        Lance une prevision meteo Earth-2 et charge les GeoTIFF resultats
        comme couches raster QGIS.

        options_json : JSON serialise avec outputDir, model, initTime,
        leadHours, variables, layerPrefix.
        """
        try:
            opts = json.loads(options_json) if options_json else {}
        except json.JSONDecodeError:
            message = "Options Earth-2 invalides (JSON malforme)."
            self._notify(message, Qgis.Warning)
            return message

        output_dir = str(opts.get("outputDir") or "").strip()
        if not output_dir:
            message = "outputDir est requis."
            self._notify(message, Qgis.Warning)
            return message

        try:
            from .earth2_tool import (
                forecast_weather,
                Earth2UnavailableError,
            )
        except ImportError as e:
            message = f"Module earth2_tool indisponible : {e}"
            self._notify(message, Qgis.Critical)
            return message

        try:
            result = forecast_weather(
                output_dir,
                model=opts.get("model") or "fcn",
                init_time=opts.get("initTime"),
                lead_hours=int(opts.get("leadHours") or 24),
                variables=opts.get("variables"),
            )
        except Earth2UnavailableError as e:
            message = (
                f"Earth-2 indisponible : {e}. "
                "Installe via 'pip install earth2studio xarray rioxarray torch'."
            )
            self._notify(message, Qgis.Critical)
            return message
        except ValueError as e:
            message = f"Parametres Earth-2 invalides : {e}"
            self._notify(message, Qgis.Warning)
            return message
        except Exception as e:  # noqa: BLE001
            message = f"Echec prevision Earth-2 : {e}"
            self._notify(message, Qgis.Critical)
            return message

        # Charge chaque GeoTIFF comme couche raster
        layer_prefix = str(opts.get("layerPrefix") or "Earth2").strip()
        loaded = 0
        for tif_path in result.geotiff_paths:
            try:
                var_name = Path(tif_path).stem
                layer_name = f"{layer_prefix}_{var_name}"
                layer = QgsRasterLayer(tif_path, layer_name, "gdal")
                if self._add_layer_to_project(layer, layer_name, source="Earth2Forecast") is not None:
                    loaded += 1
            except Exception as e:  # noqa: BLE001
                QgsMessageLog.logMessage(
                    f"Earth-2 : couche {tif_path} non chargee : {e}",
                    "QGISIA+",
                    Qgis.Warning,
                )

        message = (
            f"{loaded}/{len(result.geotiff_paths)} previsions Earth-2 chargees "
            f"(modele={result.model}, +{result.lead_hours}h, {result.duration_s:.1f}s)."
        )
        self._notify(message, Qgis.Success)
        return message

    @BridgeSlot(str, result=str)
    def exportProjectReport(self, options_json):
        """
        Exporte un rapport PDF ou DOCX du projet QGIS courant.

        options_json : JSON serialise avec title, format ('pdf'|'docx'),
        outputPath, author, subtitle, includeLayers, includeMap, sections.
        """
        try:
            opts = json.loads(options_json) if options_json else {}
        except json.JSONDecodeError:
            message = "Options export rapport invalides (JSON malforme)."
            self._notify(message, Qgis.Warning)
            return message

        title = str(opts.get("title") or "").strip()
        if not title:
            message = "Le titre du rapport est requis."
            self._notify(message, Qgis.Warning)
            return message

        output_path = str(opts.get("outputPath") or "").strip()
        if not output_path:
            message = "outputPath est requis."
            self._notify(message, Qgis.Warning)
            return message

        fmt = str(opts.get("format") or "pdf").lower().strip()
        if fmt not in ("pdf", "docx"):
            message = f"Format non supporte : {fmt}. Choisis 'pdf' ou 'docx'."
            self._notify(message, Qgis.Warning)
            return message

        try:
            from .report_export import (
                LayerInfo,
                ReportConfig,
                ReportSection,
                ReportExportError,
                export_report,
            )
        except ImportError as e:
            message = f"Module report_export indisponible : {e}"
            self._notify(message, Qgis.Critical)
            return message

        # Collecte des couches du projet
        layers_info: list = []
        if opts.get("includeLayers", True):
            for layer in QgsProject.instance().mapLayers().values():
                try:
                    if isinstance(layer, QgsVectorLayer):
                        layers_info.append(LayerInfo(
                            name=layer.name(),
                            type="vector",
                            crs=layer.crs().authid(),
                            feature_count=layer.featureCount(),
                            geometry_type=str(layer.geometryType()),
                        ))
                    elif isinstance(layer, QgsRasterLayer):
                        layers_info.append(LayerInfo(
                            name=layer.name(),
                            type="raster",
                            crs=layer.crs().authid(),
                        ))
                except Exception:  # noqa: BLE001
                    continue

        # Snapshot carte (optionnel)
        map_image = None
        if opts.get("includeMap", True):
            try:
                map_image = self._capture_map_snapshot()
            except Exception as e:  # noqa: BLE001
                QgsMessageLog.logMessage(
                    f"Snapshot carte echouee : {e}", "QGISIA+", Qgis.Warning,
                )

        # Sections custom
        sections = []
        for sec in (opts.get("sections") or []):
            sections.append(ReportSection(
                title=str(sec.get("title", "Section")),
                body=str(sec.get("body", "")),
                bullets=[str(b) for b in (sec.get("bullets") or [])],
                table_headers=[str(h) for h in (sec.get("tableHeaders") or [])],
                table_rows=[[str(c) for c in row] for row in (sec.get("tableRows") or [])],
            ))

        config = ReportConfig(
            title=title,
            subtitle=str(opts.get("subtitle") or ""),
            author=str(opts.get("author") or ""),
            map_image=map_image,
            layers=layers_info,
            sections=sections,
        )

        try:
            result = export_report(config, output_path, format=fmt)
        except ReportExportError as e:
            message = (
                f"Export {fmt.upper()} indisponible : {e}. "
                f"Installe via 'pip install {'reportlab' if fmt == 'pdf' else 'python-docx'} Pillow'."
            )
            self._notify(message, Qgis.Critical)
            return message
        except ValueError as e:
            message = f"Parametres rapport invalides : {e}"
            self._notify(message, Qgis.Warning)
            return message
        except Exception as e:  # noqa: BLE001
            message = f"Echec export rapport : {e}"
            self._notify(message, Qgis.Critical)
            return message

        message = (
            f"Rapport {fmt.upper()} genere : {Path(result.output_path).name} "
            f"({len(layers_info)} couches, {result.duration_s:.1f}s)."
        )
        self._notify(message, Qgis.Success)
        return message

    def _capture_map_snapshot(self):
        """Capture la carte en PNG — utilise un job parallele pour ne pas bloquer l'UI."""
        try:
            from qgis.utils import iface
            from qgis.core import QgsMapSettings, QgsMapRendererParallelJob
            from qgis.PyQt.QtCore import QSize, QEventLoop
            from qgis.PyQt.QtGui import QColor

            canvas = iface.mapCanvas()
            settings = QgsMapSettings()
            settings.setLayers(canvas.layers())
            settings.setExtent(canvas.extent())
            settings.setOutputSize(QSize(1600, 1000))
            settings.setDestinationCrs(canvas.mapSettings().destinationCrs())
            settings.setBackgroundColor(QColor(255, 255, 255))

            job = QgsMapRendererParallelJob(settings)
            loop = QEventLoop()
            job.finished.connect(loop.quit)
            job.start()
            loop.exec()

            img = job.renderedImage()
            if img.isNull():
                return None

            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            img.save(tmp.name, "PNG")
            return tmp.name
        except Exception:  # noqa: BLE001
            return None

    @BridgeSlot(str, str, result=str)
    def applyParcelStylePreset(self, layer_ref, preset_id):
        layer = self._find_layer(layer_ref)
        if not isinstance(layer, QgsVectorLayer):
            message = "Couche vectorielle introuvable pour appliquer un style."
            self._notify(message, Qgis.Warning)
            return message

        preset = str(preset_id or "").strip().lower() or "cadastre"

        if layer.geometryType() == QgsWkbTypes.PolygonGeometry:
            symbol_props = {
                "outline_style": "solid",
                "outline_width": "0.8",
            }
            if preset == "focus":
                symbol_props.update(
                    {
                        "color": "255,203,70,55",
                        "outline_color": "255,189,46,255",
                    }
                )
            else:
                symbol_props.update(
                    {
                        "color": "46,212,191,38",
                        "outline_color": "76,99,255,255",
                    }
                )
            symbol = QgsFillSymbol.createSimple(symbol_props)
        elif layer.geometryType() == QgsWkbTypes.LineGeometry:
            symbol = QgsLineSymbol.createSimple(
                {
                    "line_color": "76,99,255,255",
                    "line_width": "0.9",
                }
            )
        else:
            message = "Le preset cadastral cible principalement les couches polygones ou lignes."
            self._notify(message, Qgis.Warning)
            return message

        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        self._refresh_layer_rendering(layer)
        message = f"Style applique a {layer.name()}."
        self._notify(message, Qgis.Success)
        return message

    @BridgeSlot(str, str, bool, result=str)
    def setLayerLabels(self, layer_ref, field_name, enabled):
        layer = self._find_layer(layer_ref)
        if not isinstance(layer, QgsVectorLayer):
            message = "Couche vectorielle introuvable pour les etiquettes."
            self._notify(message, Qgis.Warning)
            return message

        if not enabled:
            layer.setLabelsEnabled(False)
            self._refresh_layer_rendering(layer)
            message = f"Etiquettes desactivees sur {layer.name()}."
            self._notify(message, Qgis.Success)
            return message

        final_field_name = str(field_name or "").strip() or self._guess_label_field(layer)
        if not final_field_name or layer.fields().indexOf(final_field_name) < 0:
            message = "Aucun champ valide pour creer les etiquettes."
            self._notify(message, Qgis.Warning)
            return message

        label_settings = QgsPalLayerSettings()
        label_settings.fieldName = final_field_name
        label_settings.enabled = True
        if layer.geometryType() == QgsWkbTypes.PointGeometry:
            label_settings.placement = QgsPalLayerSettings.AroundPoint
        elif layer.geometryType() == QgsWkbTypes.LineGeometry:
            label_settings.placement = QgsPalLayerSettings.Line
        else:
            label_settings.placement = QgsPalLayerSettings.Horizontal

        text_format = QgsTextFormat()
        text_format.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        text_format.setSize(9.5)
        text_format.setColor(QColor("#f8fafc"))
        buffer_settings = QgsTextBufferSettings()
        buffer_settings.setEnabled(True)
        buffer_settings.setColor(QColor("#111827"))
        buffer_settings.setSize(1.1)
        text_format.setBuffer(buffer_settings)
        label_settings.setFormat(text_format)

        layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
        layer.setLabelsEnabled(True)
        self._refresh_layer_rendering(layer)
        message = f"Etiquettes activees sur {layer.name()} avec le champ {final_field_name}."
        self._notify(message, Qgis.Success)
        return message

    @BridgeSlot(str, str, result=str)
    def applyQmlStyle(self, layer_ref, qml_xml):
        """Applique un style QGIS (.qml fourni en chaine XML) a une couche.

        Utilise par la reproduction de carte (legende VLM -> QML -> style).
        """
        layer = self._find_layer(layer_ref)
        if layer is None:
            message = "Couche introuvable pour appliquer le style."
            self._notify(message, Qgis.Warning)
            return message
        try:
            from qgis.PyQt.QtXml import QDomDocument
            doc = QDomDocument()
            if not doc.setContent(qml_xml):
                message = "QML invalide (XML non analysable)."
                self._notify(message, Qgis.Warning)
                return message
            ok, err = layer.importNamedStyle(doc)
            if not ok:
                message = f"Echec application du style: {err}"
                self._notify(message, Qgis.Warning)
                return message
            self._refresh_layer_rendering(layer)
            message = f"Style applique sur {layer.name()}."
            self._notify(message, Qgis.Success)
            return message
        except Exception as exc:  # noqa: BLE001
            message = f"Erreur application style: {exc}"
            self._notify(message, Qgis.Warning)
            return message

    @BridgeSlot(str, str, str, result=str)
    def applySymbologyPreset(self, layer_ref, preset_id, field):
        """Applique une symbologie institutionnelle francaise (preset) a une couche.

        Les presets (ONF, IGN, PLU, Cadastre, Corine, PPRi...) sont definis dans
        config/symbology_presets.json et convertis en renderer categorise QGIS.
        """
        layer = self._find_layer(layer_ref)
        if not isinstance(layer, QgsVectorLayer):
            message = "Couche vectorielle introuvable pour le preset."
            self._notify(message, Qgis.Warning)
            return message
        try:
            try:
                from symbology_presets import preset_to_qml, get_preset
            except ImportError:
                from .symbology_presets import preset_to_qml, get_preset
            if get_preset(preset_id) is None:
                message = f"Preset de symbologie inconnu: {preset_id}"
                self._notify(message, Qgis.Warning)
                return message
            qml = preset_to_qml(preset_id, field=(field or None))
            from qgis.PyQt.QtXml import QDomDocument
            doc = QDomDocument()
            if not doc.setContent(qml):
                message = "QML du preset invalide."
                self._notify(message, Qgis.Warning)
                return message
            ok, err = layer.importNamedStyle(doc)
            if not ok:
                message = f"Echec application preset: {err}"
                self._notify(message, Qgis.Warning)
                return message
            self._refresh_layer_rendering(layer)
            message = f"Symbologie '{preset_id}' appliquee sur {layer.name()}."
            self._notify(message, Qgis.Success)
            return message
        except Exception as exc:  # noqa: BLE001
            message = f"Erreur application preset: {exc}"
            self._notify(message, Qgis.Warning)
            return message

    @BridgeSlot(str, str, str, result=str)
    def splitSelectedLayerByLine(self, layer_ref, line_wkt, output_name):
        layer = self._find_layer(layer_ref)
        if not isinstance(layer, QgsVectorLayer):
            message = "Couche vectorielle introuvable pour la decoupe."
            self._notify(message, Qgis.Warning)
            return message
        if layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            message = "La decoupe par ligne est reservee aux couches polygonales."
            self._notify(message, Qgis.Warning)
            return message
        if layer.selectedFeatureCount() <= 0:
            message = "Selectionne au moins une entite avant de lancer la decoupe."
            self._notify(message, Qgis.Warning)
            return message

        split_geometry = QgsGeometry.fromWkt(str(line_wkt or "").strip())
        if split_geometry is None or split_geometry.isNull() or split_geometry.isEmpty():
            message = "Ligne de decoupe invalide."
            self._notify(message, Qgis.Warning)
            return message

        split_layer = QgsVectorLayer(
            f"LineString?crs={layer.crs().authid()}",
            "geoai_split_line",
            "memory",
        )
        split_provider = split_layer.dataProvider()
        split_provider.addAttributes([QgsField("id", QVariant.Int)])
        split_layer.updateFields()
        split_feature = QgsFeature(split_layer.fields())
        split_feature.setAttributes([1])
        split_feature.setGeometry(split_geometry)
        split_provider.addFeatures([split_feature])
        split_layer.updateExtents()

        try:
            selected_result = processing.run(
                "native:saveselectedfeatures",
                {
                    "INPUT": layer,
                    "OUTPUT": "memory:",
                },
                feedback=QgsProcessingFeedback(),
            )
            selected_layer = selected_result.get("OUTPUT")
            split_result = processing.run(
                "native:splitwithlines",
                {
                    "INPUT": selected_layer,
                    "LINES": split_layer,
                    "OUTPUT": "memory:",
                },
                feedback=QgsProcessingFeedback(),
            )
        except Exception:
            QgsMessageLog.logMessage(
                traceback.format_exc(),
                "GeoAI",
                level=Qgis.Critical,
            )
            message = "La decoupe des entites selectionnees a echoue."
            self._notify(message, Qgis.Critical, duration=6)
            return message

        output_layer = split_result.get("OUTPUT")
        if output_layer is None:
            message = "Aucune couche de sortie n'a ete produite."
            self._notify(message, Qgis.Warning)
            return message

        final_output_name = str(output_name or "").strip() or f"{layer.name()}_split"
        output_layer.setName(final_output_name)
        QgsProject.instance().addMapLayer(output_layer)
        self._refresh_layer_rendering(output_layer)
        message = f"Couche decoupee creee : {final_output_name}."
        self._notify(message, Qgis.Success)
        return message

    @BridgeSlot(str, str, str, str, result=str)
    def calculateRasterFormula(self, layer_ids_json, formula, output_name, output_path):
        try:
            layer_ids = json.loads(layer_ids_json) if layer_ids_json else []
        except json.JSONDecodeError:
            layer_ids = []

        if not isinstance(layer_ids, list):
            layer_ids = []

        raster_layers = []
        for layer_ref in layer_ids:
            layer = self._ensure_raster_layer(layer_ref)
            if layer is None:
                message = f"Raster introuvable ou invalide: {layer_ref}"
                self._notify(message, Qgis.Warning)
                return ""
            raster_layers.append(layer)

        if not formula:
            self._notify("La formule raster est requise.", Qgis.Warning)
            return ""

        final_output_name = str(output_name or "").strip() or "Raster_calcule"

        try:
            payload = self._run_raster_calculator(
                raster_layers,
                str(formula).strip(),
                final_output_name,
                str(output_path or "").strip(),
            )
        except Exception:
            QgsMessageLog.logMessage(
                traceback.format_exc(),
                "GeoAI",
                level=Qgis.Critical,
            )
            self._notify("Le calcul raster a échoué.", Qgis.Critical, duration=6)
            return ""

        self._notify(f"Raster calculé créé : {payload['outputLayerName']}.", Qgis.Success)
        return json.dumps(payload, ensure_ascii=False)

    @BridgeSlot(str, str, str, str, result=str)
    def computeSpectralIndex(self, layer_ref, index_id, band_map_json, output_path):
        """Calcule un indice spectral (NDVI/NDWI/NDBI/NBR/EVI) sur un raster multibande
        et applique automatiquement une rampe pseudocolor (P1 - diagnostic satellite).

        band_map_json : {"NIR": "couche@8", "RED": "couche@4", ...} (refs QgsRasterCalculator).
        """
        try:
            from spectral_indices import build_expression
        except ImportError:
            from .spectral_indices import build_expression

        index_id = str(index_id or "").strip().lower()
        try:
            band_map = json.loads(band_map_json) if band_map_json else {}
        except json.JSONDecodeError:
            band_map = {}
        if not isinstance(band_map, dict) or not band_map:
            msg = 'band_map requis, ex: {"NIR":"couche@2","RED":"couche@1"}.'
            self._notify(msg, Qgis.Warning)
            return ""

        # Calcul via QgsRasterCalculator (band-aware, independant du provider gdal
        # processing). band_map : {"NIR":"couche@8","RED":"couche@4"} ou {"NIR":"couche"} (bande 1).
        try:
            from qgis.analysis import QgsRasterCalculator, QgsRasterCalculatorEntry
        except ImportError:
            self._notify("QgsRasterCalculator indisponible.", Qgis.Critical)
            return ""

        entries = []
        ref_map = {}
        base_layer = None
        for band, spec in band_map.items():
            spec = str(spec)
            if "@" in spec:
                lname, _, bnum_s = spec.rpartition("@")
                try:
                    bnum = int(bnum_s)
                except ValueError:
                    lname, bnum = spec, 1
            else:
                lname, bnum = spec, 1
            layer = self._ensure_raster_layer(lname)
            if layer is None:
                self._notify(f"Raster introuvable pour la bande {band}: {lname}", Qgis.Warning)
                return ""
            base_layer = base_layer or layer
            ref = f"{lname}@{bnum}"
            entry = QgsRasterCalculatorEntry()
            entry.ref = ref
            entry.raster = layer
            entry.bandNumber = bnum
            entries.append(entry)
            ref_map[band] = f'"{ref}"'

        try:
            expression = build_expression(index_id, ref_map)
        except ValueError as exc:
            self._notify(str(exc), Qgis.Warning)
            return ""

        output_name = f"{index_id.upper()}_{layer_ref}"
        out_path = str(output_path or "").strip() or str(
            self._runtime_directory() / f"{output_name}.tif")
        calc = QgsRasterCalculator(
            expression, out_path, "GTiff", base_layer.extent(),
            base_layer.width(), base_layer.height(), entries)
        if calc.processCalculation() != 0:
            self._notify("Echec du calcul d'indice spectral.", Qgis.Critical)
            return ""

        out_rl = QgsRasterLayer(out_path, output_name)
        if self._add_layer_to_project(out_rl, output_name, source="SpectralIndex") is None:
            self._notify("Indice calcule mais non chargeable.", Qgis.Warning)
            return ""
        out_layer = out_rl.name()
        payload = {"outputLayerName": out_layer, "outputPath": out_path}

        # Auto-stylage pseudocolor selon l'indice (plage -1..1 typique des indices normalises)
        try:
            from raster_style import build_pseudocolor_qml, RAMPS
        except ImportError:
            from .raster_style import build_pseudocolor_qml, RAMPS
        ramp = index_id if index_id in RAMPS else "greyscale"
        try:
            qml = build_pseudocolor_qml(ramp, -1.0, 1.0, band=1)
            self.applyQmlStyle(out_layer, qml)
            payload["styled_with"] = ramp
        except Exception as exc:  # noqa: BLE001 - le calcul a reussi, le style est best-effort
            payload["style_error"] = str(exc)

        payload["index"] = index_id
        payload["expression"] = expression
        return json.dumps(payload, ensure_ascii=False)

    @BridgeSlot(str, str, str, result=str)
    def computeRasterDifference(self, layer_a, layer_b, output_path):
        """Difference de deux rasters mono-bande (ex: NDVI_t2 - NDVI_t1) : detection de
        changement / monitoring temporel. Auto-style diverging (P1)."""
        try:
            from qgis.analysis import QgsRasterCalculator, QgsRasterCalculatorEntry
        except ImportError:
            self._notify("QgsRasterCalculator indisponible.", Qgis.Critical)
            return ""

        la = self._ensure_raster_layer(str(layer_a or "").strip())
        lb = self._ensure_raster_layer(str(layer_b or "").strip())
        if la is None or lb is None:
            self._notify("Deux rasters valides requis pour la difference.", Qgis.Warning)
            return ""

        ea = QgsRasterCalculatorEntry()
        ea.ref = f"{la.name()}@1"; ea.raster = la; ea.bandNumber = 1
        eb = QgsRasterCalculatorEntry()
        eb.ref = f"{lb.name()}@1"; eb.raster = lb; eb.bandNumber = 1
        expression = f'"{ea.ref}" - "{eb.ref}"'
        output_name = f"DIFF_{la.name()}_{lb.name()}"
        out_path = str(output_path or "").strip() or str(
            self._runtime_directory() / f"{output_name}.tif")

        calc = QgsRasterCalculator(
            expression, out_path, "GTiff", la.extent(), la.width(), la.height(), [ea, eb])
        if calc.processCalculation() != 0:
            self._notify("Echec du calcul de difference raster.", Qgis.Critical)
            return ""

        out_rl = QgsRasterLayer(out_path, output_name)
        if self._add_layer_to_project(out_rl, output_name, source="RasterDifference") is None:
            self._notify("Difference calculee mais non chargeable.", Qgis.Warning)
            return ""

        payload = {"outputLayerName": out_rl.name(), "outputPath": out_path,
                   "expression": expression}
        try:
            from raster_style import build_pseudocolor_qml, RAMPS
        except ImportError:
            from .raster_style import build_pseudocolor_qml, RAMPS
        ramp = "thermal" if "thermal" in RAMPS else "greyscale"
        try:
            qml = build_pseudocolor_qml(ramp, -1.0, 1.0, band=1)
            self.applyQmlStyle(out_rl.name(), qml)
            payload["styled_with"] = ramp
        except Exception as exc:  # noqa: BLE001
            payload["style_error"] = str(exc)

        self._notify(f"Difference raster creee : {out_rl.name()}.", Qgis.Success)
        return json.dumps(payload, ensure_ascii=False)

    @BridgeSlot(str, str, str, result=str)
    def zonalStatistics(self, raster_ref, polygon_ref, prefix):
        """Statistiques zonales d'un raster par entite d'une couche de polygones
        (ex: NDVI moyen par parcelle). Ajoute des champs <prefix>mean/min/max/count
        a la couche vecteur. (P1 - diagnostic par zone)."""
        try:
            from qgis.analysis import QgsZonalStatistics
        except ImportError:
            self._notify("QgsZonalStatistics indisponible.", Qgis.Critical)
            return ""

        raster = self._ensure_raster_layer(str(raster_ref or "").strip())
        poly = self._find_layer(str(polygon_ref or "").strip())
        if raster is None:
            self._notify(f"Raster introuvable : {raster_ref}", Qgis.Warning)
            return ""
        if not isinstance(poly, QgsVectorLayer) or \
                poly.geometryType() != QgsWkbTypes.PolygonGeometry:
            self._notify("Couche de polygones requise pour les stats zonales.", Qgis.Warning)
            return ""

        prefix = str(prefix or "").strip() or "zs_"
        stats = (QgsZonalStatistics.Mean | QgsZonalStatistics.Min
                 | QgsZonalStatistics.Max | QgsZonalStatistics.Count)
        try:
            zs = QgsZonalStatistics(poly, raster, prefix, 1, QgsZonalStatistics.Statistics(stats))
            zs.calculateStatistics(None)
        except Exception as exc:  # noqa: BLE001
            self._notify(f"Echec des stats zonales : {exc}", Qgis.Critical)
            return ""

        fields_added = [f.name() for f in poly.fields() if f.name().startswith(prefix)]
        poly.triggerRepaint()
        message = f"Stats zonales calculees sur {poly.name()} ({len(fields_added)} champs)."
        self._notify(message, Qgis.Success)
        return json.dumps({
            "ok": True, "layer": poly.name(), "prefix": prefix,
            "fields_added": fields_added,
        }, ensure_ascii=False)

    @BridgeSlot(str, str, str, result=str)
    def bufferLayer(self, layer_ref, distance, output_name):
        """Cree une zone tampon (buffer) autour des entites d'une couche vectorielle.
        Ex: 'buffer de 500m autour des ecoles'. Distance dans l'unite du CRS de la couche.
        """
        src = self._find_layer(str(layer_ref or "").strip())
        if not isinstance(src, QgsVectorLayer):
            self._notify("Couche vectorielle introuvable pour le buffer.", Qgis.Warning)
            return ""
        try:
            dist = float(str(distance).replace(",", "."))
        except ValueError:
            self._notify("Distance de buffer invalide.", Qgis.Warning)
            return ""

        final_name = str(output_name or "").strip() or f"{src.name()}_buffer_{dist:g}"
        crs_id = src.crs().authid() or "EPSG:4326"
        buf = QgsVectorLayer(f"Polygon?crs={crs_id}", final_name, "memory")
        buf.dataProvider().addAttributes(src.fields())
        buf.updateFields()

        out_feats = []
        for feat in src.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            nf = QgsFeature(buf.fields())
            nf.setAttributes(feat.attributes())
            nf.setGeometry(geom.buffer(dist, 12))
            out_feats.append(nf)

        buf.dataProvider().addFeatures(out_feats)
        buf.updateExtents()
        if self._add_layer_to_project(buf, final_name, source="Buffer") is None:
            self._notify("Le buffer n'a pas pu etre charge.", Qgis.Warning)
            return ""

        message = f"Buffer cree : {final_name} ({len(out_feats)} entites, {dist:g} u)."
        self._notify(message, Qgis.Success)
        return json.dumps({"ok": True, "layer": final_name,
                           "features": len(out_feats), "distance": dist}, ensure_ascii=False)

    @BridgeSlot(str, str, str, result=str)
    def saveVectorLayer(self, layer_ref, output_path, driver):
        """Exporte une couche vectorielle vers un fichier (livrable) : GeoPackage (GPKG),
        GeoJSON ou ESRI Shapefile. Utile pour produire un resultat telechargeable.
        """
        layer = self._find_layer(str(layer_ref or "").strip())
        if not isinstance(layer, QgsVectorLayer):
            self._notify("Couche vectorielle introuvable pour l'export.", Qgis.Warning)
            return ""
        out = str(output_path or "").strip()
        if not out:
            self._notify("Chemin de sortie requis pour l'export.", Qgis.Warning)
            return ""
        driver = str(driver or "").strip() or "GPKG"

        try:
            from qgis.core import QgsVectorFileWriter, QgsCoordinateTransformContext
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = driver
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            res = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, out, QgsCoordinateTransformContext(), options)
            err_code = res[0] if isinstance(res, (tuple, list)) else res
            if err_code != QgsVectorFileWriter.NoError:
                detail = res[1] if isinstance(res, (tuple, list)) and len(res) > 1 else ""
                self._notify(f"Echec de l'export : {detail}", Qgis.Warning, duration=6)
                return ""
        except Exception as exc:  # noqa: BLE001
            self._notify(f"Erreur export : {exc}", Qgis.Critical)
            return ""

        message = f"Couche exportee : {Path(out).name} ({driver})."
        self._notify(message, Qgis.Success)
        return json.dumps({"ok": True, "path": out, "driver": driver,
                           "features": layer.featureCount()}, ensure_ascii=False)

    _DEFAULT_LAYOUT_ELEMENTS = [
        {"type": "title", "x": 10, "y": 8, "width": 190, "height": 12},
        {"type": "map", "x": 10, "y": 22, "width": 190, "height": 235},
        {"type": "legend", "x": 150, "y": 200, "width": 50, "height": 60},
        {"type": "scalebar", "x": 10, "y": 262, "width": 80, "height": 15},
    ]

    def _render_layout_to_file(self, title, out, fmt, page_w, page_h, elements):
        """Construit une mise en page (carte + elements positionnes) et l'exporte (PNG/PDF).
        Renvoie un payload dict (avec layout_meta) ou None apres notification d'echec.
        Partage par exportPrintLayout et exportLayoutSpec."""
        from qgis.core import (
            QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLabel, QgsLayoutItemLegend,
            QgsLayoutItemScaleBar, QgsLayoutItemPicture, QgsLayoutPoint, QgsLayoutSize,
            QgsUnitTypes, QgsLayoutExporter,
        )
        project = QgsProject.instance()
        canvas = self.iface.mapCanvas()
        layers = canvas.layers() or list(project.mapLayers().values())
        if not layers:
            self._notify("Aucune couche a mettre en page.", Qgis.Warning)
            return None
        fmt = str(fmt or "png").strip().lower()

        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName(title or "Carte QGISIA")
        mm = QgsUnitTypes.LayoutMillimeters
        layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(page_w, page_h, mm))

        extent = canvas.extent()
        if extent is None or extent.isEmpty():
            extent = layers[0].extent()

        # 1er passage : la carte (les autres elements s'y rattachent)
        map_item = None
        for el in elements:
            if el.get("type") != "map":
                continue
            map_item = QgsLayoutItemMap(layout)
            map_item.attemptMove(QgsLayoutPoint(el.get("x", 10), el.get("y", 22), mm))
            map_item.attemptResize(QgsLayoutSize(el.get("width", 190), el.get("height", 235), mm))
            map_item.setLayers(layers)
            map_item.setExtent(extent)
            map_item.setFrameEnabled(True)
            layout.addLayoutItem(map_item)
            break

        # 2e passage : les autres elements
        for el in elements:
            etype = el.get("type")
            x, y = el.get("x", 10), el.get("y", 10)
            w_, h_ = el.get("width", 50), el.get("height", 20)
            if etype in ("title", "text"):
                lab = QgsLayoutItemLabel(layout)
                txt = el.get("text") or (title or "Carte QGISIA+") if etype == "title" \
                    else el.get("text", "")
                lab.setText(txt)
                size = 16 if etype == "title" else 10
                lab.setFont(QFont("Segoe UI", size, QFont.Bold if etype == "title" else QFont.Normal))
                lab.attemptMove(QgsLayoutPoint(x, y, mm))
                lab.attemptResize(QgsLayoutSize(w_, h_, mm))
                layout.addLayoutItem(lab)
            elif etype == "legend" and map_item is not None:
                leg = QgsLayoutItemLegend(layout)
                leg.setLinkedMap(map_item)
                leg.setTitle("Legende")
                leg.attemptMove(QgsLayoutPoint(x, y, mm))
                layout.addLayoutItem(leg)
            elif etype == "scalebar" and map_item is not None:
                sb = QgsLayoutItemScaleBar(layout)
                sb.setStyle("Single Box")
                sb.setLinkedMap(map_item)
                sb.applyDefaultSize()
                sb.attemptMove(QgsLayoutPoint(x, y, mm))
                layout.addLayoutItem(sb)
            elif etype in ("north", "image"):
                try:
                    pic = QgsLayoutItemPicture(layout)
                    if etype == "north":
                        pic.setPicturePath(os.path.join(
                            QgsApplication.pkgDataPath(), "svg", "arrows", "NorthArrow_02.svg"))
                    elif el.get("path"):
                        pic.setPicturePath(el["path"])
                    pic.attemptMove(QgsLayoutPoint(x, y, mm))
                    pic.attemptResize(QgsLayoutSize(w_, h_, mm))
                    layout.addLayoutItem(pic)
                except Exception:  # noqa: BLE001 - element decoratif best-effort
                    pass

        Path(out).parent.mkdir(parents=True, exist_ok=True)
        exporter = QgsLayoutExporter(layout)
        try:
            if fmt == "pdf":
                res = exporter.exportToPdf(out, QgsLayoutExporter.PdfExportSettings())
            else:
                res = exporter.exportToImage(out, QgsLayoutExporter.ImageExportSettings())
        except Exception as exc:  # noqa: BLE001
            self._notify(f"Erreur export mise en page : {exc}", Qgis.Critical)
            return None
        if res != QgsLayoutExporter.Success:
            self._notify("Echec de l'export de la mise en page.", Qgis.Warning)
            return None

        present = {el.get("type") for el in elements}
        extent_list = None
        if map_item is not None:
            ext = map_item.extent()
            extent_list = [ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum()]
        layout_meta = {
            "title": bool(title) or ("title" in present or "text" in present),
            "map": {"extent": extent_list} if map_item is not None else None,
            "legend": "legend" in present,
            "scalebar": "scalebar" in present,
            "north": "north" in present,
        }
        self._notify(f"Planche cartographique exportee : {Path(out).name}.", Qgis.Success)
        return {"ok": True, "path": out, "format": fmt,
                "layers": len(layers), "layout_meta": layout_meta}

    @BridgeSlot(str, str, str, str, result=str)
    def exportPrintLayout(self, title, output_path, fmt, template_id):
        """Genere une planche cartographique pro et l'exporte (PNG/PDF). Si template_id est
        fourni (voir layout_specs.list_templates : a4_portrait_simple, a4_paysage_pro,
        a3_paysage_atlas), la page et le placement des elements suivent ce gabarit."""
        out = str(output_path or "").strip()
        if not out:
            self._notify("Chemin de sortie requis.", Qgis.Warning)
            return ""
        template_id = str(template_id or "").strip()
        page_w, page_h = 210.0, 297.0  # A4 portrait par defaut
        elements = self._DEFAULT_LAYOUT_ELEMENTS
        if template_id:
            try:
                from layout_specs import get_template, page_dimensions_mm
            except ImportError:
                from .layout_specs import get_template, page_dimensions_mm
            template = get_template(template_id)
            if template:
                page_w, page_h = page_dimensions_mm(
                    template["page_size"], template["orientation"])
                elements = template.get("elements", [])
            else:
                template_id = ""

        payload = self._render_layout_to_file(title, out, fmt, page_w, page_h, elements)
        if payload is None:
            return ""
        payload["template"] = template_id or None
        return json.dumps(payload, ensure_ascii=False)

    @BridgeSlot(str, str, str, str, result=str)
    def exportLayoutSpec(self, title, output_path, fmt, spec_json):
        """Exporte une mise en page a partir d'une specification explicite d'elements
        (utilisee par la boucle d'auto-amelioration). spec_json :
        {page_size, orientation, elements:[{type,x,y,width,height,...}]}."""
        out = str(output_path or "").strip()
        if not out:
            self._notify("Chemin de sortie requis.", Qgis.Warning)
            return ""
        try:
            spec = json.loads(spec_json) if spec_json else {}
        except (ValueError, TypeError):
            spec = {}
        elements = spec.get("elements") or []
        if not elements:
            self._notify("Specification d'elements vide.", Qgis.Warning)
            return ""
        try:
            from layout_specs import page_dimensions_mm
        except ImportError:
            from .layout_specs import page_dimensions_mm
        page_w, page_h = page_dimensions_mm(
            spec.get("page_size", "A4"), spec.get("orientation", "portrait"))

        payload = self._render_layout_to_file(title, out, fmt, page_w, page_h, elements)
        if payload is None:
            return ""
        payload["elements"] = len(elements)
        return json.dumps(payload, ensure_ascii=False)

    @BridgeSlot(str, str, result=str)
    def classifyRaster(self, layer_ref, scheme_id):
        """Applique une classification thematique a un raster continu (ex: NDVI -> classes
        de vegetation, dNBR -> severite du feu, pente -> classes de degres) via un style
        discret. Voir classification.list_schemes pour les id."""
        raster = self._ensure_raster_layer(str(layer_ref or "").strip())
        if raster is None:
            self._notify(f"Raster introuvable : {layer_ref}", Qgis.Warning)
            return ""
        try:
            from classification import build_discrete_pseudocolor_qml, get_scheme
        except ImportError:
            from .classification import build_discrete_pseudocolor_qml, get_scheme
        scheme_id = str(scheme_id or "").strip()
        if get_scheme(scheme_id) is None:
            self._notify(f"Schema de classification inconnu : {scheme_id}", Qgis.Warning)
            return ""
        try:
            qml = build_discrete_pseudocolor_qml(scheme_id, band=1)
        except Exception as exc:  # noqa: BLE001
            self._notify(f"Erreur classification : {exc}", Qgis.Warning)
            return ""

        from qgis.PyQt.QtXml import QDomDocument
        doc = QDomDocument()
        if not doc.setContent(qml):
            self._notify("QML de classification invalide.", Qgis.Warning)
            return ""
        ok, err = raster.importNamedStyle(doc)
        if not ok:
            self._notify(f"Echec application classification : {err}", Qgis.Warning)
            return ""
        self._refresh_layer_rendering(raster)
        message = f"Classification '{scheme_id}' appliquee sur {raster.name()}."
        self._notify(message, Qgis.Success)
        return json.dumps({"ok": True, "layer": raster.name(), "scheme": scheme_id},
                          ensure_ascii=False)

    @BridgeSlot(str, str, result=str)
    def classifyChange(self, layer_ref, scheme_id):
        """Stylise une carte de changement (ex: dNDVI de computeRasterDifference) en classes
        de severite ('dndvi', 'dnbr_feu') via un style raster discret colore."""
        raster = self._ensure_raster_layer(str(layer_ref or "").strip())
        if raster is None:
            self._notify(f"Raster introuvable : {layer_ref}", Qgis.Warning)
            return ""
        try:
            from change_classes import get_scheme
        except ImportError:
            from .change_classes import get_scheme
        scheme = get_scheme(str(scheme_id or "").strip())
        if scheme is None:
            self._notify(f"Schema de changement inconnu : {scheme_id}", Qgis.Warning)
            return ""

        items = []
        for cls in scheme["classes"]:
            top = cls["max"]
            val = top if top is not None else 1e9
            items.append(
                f'<item value="{val:g}" label="{cls["label"]}" alpha="255" '
                f'color="{cls["color"]}"/>')
        items_xml = "\n          ".join(items)
        qml = (
            '<!DOCTYPE qgis>\n<qgis version="3.34" styleCategories="Symbology">\n'
            '  <pipe>\n'
            '    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="1">\n'
            '      <rastershader>\n'
            '        <colorrampshader colorRampType="DISCRETE" classificationMode="1">\n'
            f'          {items_xml}\n'
            '        </colorrampshader>\n'
            '      </rastershader>\n'
            '    </rasterrenderer>\n'
            '  </pipe>\n</qgis>\n'
        )

        from qgis.PyQt.QtXml import QDomDocument
        doc = QDomDocument()
        if not doc.setContent(qml):
            self._notify("QML de changement invalide.", Qgis.Warning)
            return ""
        ok, err = raster.importNamedStyle(doc)
        if not ok:
            self._notify(f"Echec application classes changement : {err}", Qgis.Warning)
            return ""
        self._refresh_layer_rendering(raster)
        self._notify(f"Classes de changement '{scheme_id}' appliquees sur {raster.name()}.",
                     Qgis.Success)
        return json.dumps({"ok": True, "layer": raster.name(), "scheme": scheme_id,
                           "classes": len(scheme["classes"])}, ensure_ascii=False)

    @BridgeSlot(str, str, str, str, result=str)
    def exportAtlas(self, coverage_ref, output_path, atlas_id, page_field):
        """Genere un atlas PDF multi-pages (1 page par entite d'une couche de couverture).
        atlas_id (optionnel) choisit le gabarit de base (voir atlas_specs.list_atlas)."""
        from qgis.core import (
            QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLabel, QgsLayoutItemLegend,
            QgsLayoutItemScaleBar, QgsLayoutPoint, QgsLayoutSize, QgsUnitTypes,
            QgsLayoutExporter,
        )
        coverage = self._find_layer(str(coverage_ref or "").strip())
        if not isinstance(coverage, QgsVectorLayer) or coverage.featureCount() == 0:
            self._notify("Couche de couverture vectorielle (non vide) requise.", Qgis.Warning)
            return ""
        out = str(output_path or "").strip()
        if not out:
            self._notify("Chemin PDF de sortie requis.", Qgis.Warning)
            return ""

        page_size, orientation = "A4", "landscape"
        try:
            from atlas_specs import get_atlas
            from layout_specs import get_template, page_dimensions_mm
        except ImportError:
            from .atlas_specs import get_atlas
            from .layout_specs import get_template, page_dimensions_mm
        atlas_meta = get_atlas(str(atlas_id or "").strip()) if atlas_id else None
        base_layout = atlas_meta["base_layout"] if atlas_meta else "a4_paysage_pro"
        tmpl = get_template(base_layout)
        if tmpl:
            page_size, orientation = tmpl["page_size"], tmpl["orientation"]

        project = QgsProject.instance()
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName(atlas_meta["name"] if atlas_meta else "Atlas QGISIA")
        mm = QgsUnitTypes.LayoutMillimeters
        w, h = page_dimensions_mm(page_size, orientation)
        layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(w, h, mm))

        m = QgsLayoutItemMap(layout)
        m.attemptMove(QgsLayoutPoint(10, 18, mm))
        m.attemptResize(QgsLayoutSize(w - 20, h - 30, mm))
        m.setLayers(self.iface.mapCanvas().layers() or list(project.mapLayers().values()))
        m.setExtent(coverage.extent())
        m.setAtlasDriven(True)
        m.setAtlasMargin(0.10)
        m.setFrameEnabled(True)
        layout.addLayoutItem(m)

        label = QgsLayoutItemLabel(layout)
        label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        label.setText("[% @atlas_pagename %]")
        label.attemptMove(QgsLayoutPoint(10, 6, mm))
        label.attemptResize(QgsLayoutSize(w - 20, 10, mm))
        layout.addLayoutItem(label)

        legend = QgsLayoutItemLegend(layout)
        legend.setLinkedMap(m)
        legend.attemptMove(QgsLayoutPoint(w - 48, h - 52, mm))
        layout.addLayoutItem(legend)

        scalebar = QgsLayoutItemScaleBar(layout)
        scalebar.setStyle("Single Box")
        scalebar.setLinkedMap(m)
        scalebar.applyDefaultSize()
        scalebar.attemptMove(QgsLayoutPoint(10, h - 12, mm))
        layout.addLayoutItem(scalebar)

        atlas = layout.atlas()
        atlas.setEnabled(True)
        atlas.setCoverageLayer(coverage)
        pf = str(page_field or "").strip()
        if pf and coverage.fields().indexOf(pf) >= 0:
            atlas.setPageNameExpression(f'"{pf}"')

        Path(out).parent.mkdir(parents=True, exist_ok=True)
        exporter = QgsLayoutExporter(layout)
        try:
            res = exporter.exportToPdf(atlas, out, QgsLayoutExporter.PdfExportSettings())
        except Exception as exc:  # noqa: BLE001
            self._notify(f"Erreur export atlas : {exc}", Qgis.Critical)
            return ""
        code = res[0] if isinstance(res, (tuple, list)) else res
        if code != QgsLayoutExporter.Success:
            self._notify("Echec de l'export de l'atlas.", Qgis.Warning)
            return ""

        pages = coverage.featureCount()
        self._notify(f"Atlas exporte : {Path(out).name} ({pages} pages).", Qgis.Success)
        return json.dumps({"ok": True, "path": out, "pages": pages,
                           "base_layout": base_layout,
                           "atlas": atlas_id or None}, ensure_ascii=False)

    @BridgeSlot(str, str, result=str)
    def suitabilityAnalysis(self, criteria_json, output_path):
        """Carte d'aptitude (site selection) : somme ponderee de rasters criteres
        (pente, NDVI, distance...). criteria_json : [{"layer","weight","invert"?}]."""
        from qgis.analysis import QgsRasterCalculator, QgsRasterCalculatorEntry
        try:
            criteria = json.loads(criteria_json) if criteria_json else []
        except (ValueError, TypeError):
            criteria = []
        if not isinstance(criteria, list) or not criteria:
            self._notify("Criteres requis (liste non vide).", Qgis.Warning)
            return ""

        entries, terms, base = [], [], None
        for c in criteria:
            layer = self._ensure_raster_layer(str(c.get("layer", "")).strip())
            if layer is None:
                self._notify(f"Raster critere introuvable : {c.get('layer')}", Qgis.Warning)
                return ""
            base = base or layer
            ref = f"{layer.name()}@1"
            entry = QgsRasterCalculatorEntry()
            entry.ref = ref
            entry.raster = layer
            entry.bandNumber = 1
            entries.append(entry)
            try:
                weight = float(c.get("weight", 1))
            except (ValueError, TypeError):
                weight = 1.0
            term = f'(1 - "{ref}")' if c.get("invert") else f'"{ref}"'
            terms.append(f"{weight} * {term}")

        expression = " + ".join(terms)
        out_path = str(output_path or "").strip() or str(self._runtime_directory() / "suitability.tif")
        out_name = "Aptitude"
        calc = QgsRasterCalculator(
            expression, out_path, "GTiff", base.extent(), base.width(), base.height(), entries)
        if calc.processCalculation() != 0:
            self._notify("Echec du calcul d'aptitude.", Qgis.Critical)
            return ""
        rl = QgsRasterLayer(out_path, out_name)
        if self._add_layer_to_project(rl, out_name, source="Suitability") is None:
            self._notify("Aptitude calculee mais non chargeable.", Qgis.Warning)
            return ""
        try:
            from raster_style import build_pseudocolor_qml
        except ImportError:
            from .raster_style import build_pseudocolor_qml
        try:
            vmax = sum(abs(float(c.get("weight", 1))) for c in criteria) or 1.0
            self.applyQmlStyle(out_name, build_pseudocolor_qml("rdylgn", 0.0, vmax, 1))
        except Exception:  # noqa: BLE001
            pass
        self._notify(f"Carte d'aptitude creee : {out_name}.", Qgis.Success)
        return json.dumps({"ok": True, "layer": out_name, "path": out_path,
                           "expression": expression, "criteria": len(criteria)},
                          ensure_ascii=False)

    @BridgeSlot(str, str, str, result=str)
    def hotspotAnalysis(self, point_ref, radius, output_path):
        """Carte de chaleur (densite de noyau) d'une couche de points = hotspots."""
        from qgis.analysis import QgsKernelDensityEstimation
        pts = self._find_layer(str(point_ref or "").strip())
        if not isinstance(pts, QgsVectorLayer) or pts.geometryType() != QgsWkbTypes.PointGeometry:
            self._notify("Couche de points requise pour les hotspots.", Qgis.Warning)
            return ""
        try:
            rad = float(str(radius).replace(",", ".")) if radius else 0.0
        except ValueError:
            rad = 0.0
        ext = pts.extent()
        span = max(ext.width(), ext.height()) or 1.0
        if rad <= 0:
            rad = span / 10.0
        pixel = span / 300.0 or 1.0

        out_path = str(output_path or "").strip() or str(self._runtime_directory() / "hotspots.tif")
        params = QgsKernelDensityEstimation.Parameters()
        params.source = pts
        params.radius = rad
        params.pixelSize = pixel
        try:
            kde = QgsKernelDensityEstimation(params, out_path, "GTiff")
            if kde.run() != QgsKernelDensityEstimation.Success:
                self._notify("Echec du calcul de densite (hotspots).", Qgis.Critical)
                return ""
        except Exception as exc:  # noqa: BLE001
            self._notify(f"Erreur hotspots : {exc}", Qgis.Critical)
            return ""

        out_name = "Hotspots"
        rl = QgsRasterLayer(out_path, out_name)
        if self._add_layer_to_project(rl, out_name, source="Hotspot") is None:
            self._notify("Densite calculee mais non chargeable.", Qgis.Warning)
            return ""
        try:
            from raster_style import build_pseudocolor_qml
        except ImportError:
            from .raster_style import build_pseudocolor_qml
        try:
            st = rl.dataProvider().bandStatistics(1)
            self.applyQmlStyle(out_name, build_pseudocolor_qml(
                "thermal", st.minimumValue, st.maximumValue, 1))
        except Exception:  # noqa: BLE001
            pass
        self._notify(f"Hotspots crees : {out_name}.", Qgis.Success)
        return json.dumps({"ok": True, "layer": out_name, "path": out_path,
                           "radius": rad}, ensure_ascii=False)

    @BridgeSlot(str, str, str, result=str)
    def computeTerrain(self, dem_ref, analysis, output_path):
        """Analyse de terrain depuis un MNT : 'slope', 'aspect', 'hillshade', 'ruggedness'
        (filtres QGIS natifs). Voir terrain_formulas.list_terrain pour les options."""
        from qgis.analysis import (
            QgsSlopeFilter, QgsAspectFilter, QgsHillshadeFilter, QgsRuggednessFilter)
        try:
            from terrain_formulas import list_terrain
        except ImportError:
            from .terrain_formulas import list_terrain

        raster = self._ensure_raster_layer(str(dem_ref or "").strip())
        if raster is None:
            self._notify(f"MNT introuvable : {dem_ref}", Qgis.Warning)
            return ""
        analysis = str(analysis or "slope").strip().lower()
        if analysis not in list_terrain():
            self._notify(f"Analyse de terrain inconnue : {analysis}", Qgis.Warning)
            return ""

        out_name = f"{analysis}_{raster.name()}"
        out_path = str(output_path or "").strip() or str(
            self._runtime_directory() / f"{out_name}.tif")
        src = raster.source()
        if analysis == "slope":
            flt = QgsSlopeFilter(src, out_path, "GTiff")
        elif analysis == "aspect":
            flt = QgsAspectFilter(src, out_path, "GTiff")
        elif analysis == "hillshade":
            flt = QgsHillshadeFilter(src, out_path, "GTiff", 315.0, 45.0)
        else:
            flt = QgsRuggednessFilter(src, out_path, "GTiff")
        try:
            flt.setZFactor(1.0)
        except Exception:  # noqa: BLE001
            pass
        try:
            res = flt.processRaster(None)
        except TypeError:
            res = flt.processRaster()
        if res != 0:
            self._notify(f"Echec de l'analyse de terrain ({analysis}).", Qgis.Critical)
            return ""

        rl = QgsRasterLayer(out_path, out_name)
        if self._add_layer_to_project(rl, out_name, source="Terrain") is None:
            self._notify("Analyse terrain calculee mais non chargeable.", Qgis.Warning)
            return ""
        try:
            from raster_style import build_pseudocolor_qml
        except ImportError:
            from .raster_style import build_pseudocolor_qml
        ramp = "greyscale" if analysis == "hillshade" else "rdylgn"
        try:
            sstat = rl.dataProvider().bandStatistics(1)
            self.applyQmlStyle(out_name, build_pseudocolor_qml(
                ramp, sstat.minimumValue, sstat.maximumValue, 1))
        except Exception:  # noqa: BLE001
            pass
        self._notify(f"Analyse terrain '{analysis}' creee : {out_name}.", Qgis.Success)
        return json.dumps({"ok": True, "layer": out_name, "analysis": analysis,
                           "path": out_path}, ensure_ascii=False)

    @BridgeSlot(str, str, str, result=str)
    def clusterPoints(self, point_ref, eps, min_pts):
        """Clustering DBSCAN d'une couche de points : ajoute un champ 'cluster' (-1 = bruit)."""
        from qgis.core import QgsField
        try:
            from cluster_utils import dbscan, centroids
        except ImportError:
            from .cluster_utils import dbscan, centroids

        pts = self._find_layer(str(point_ref or "").strip())
        if not isinstance(pts, QgsVectorLayer) or pts.geometryType() != QgsWkbTypes.PointGeometry:
            self._notify("Couche de points requise pour le clustering.", Qgis.Warning)
            return ""

        fids, coords = [], []
        for feat in pts.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            pt = geom.centroid().asPoint()
            fids.append(feat.id())
            coords.append((pt.x(), pt.y()))
        if not coords:
            self._notify("Aucun point a clusteriser.", Qgis.Warning)
            return ""

        try:
            eps_v = float(str(eps).replace(",", ".")) if eps else 0.0
        except ValueError:
            eps_v = 0.0
        if eps_v <= 0:
            ext = pts.extent()
            eps_v = (max(ext.width(), ext.height()) or 1.0) / 10.0
        try:
            mp = int(min_pts) if min_pts else 2
        except ValueError:
            mp = 2

        labels = dbscan(coords, eps_v, mp)
        dp = pts.dataProvider()
        if pts.fields().indexOf("cluster") < 0:
            dp.addAttributes([QgsField("cluster", QVariant.Int)])
            pts.updateFields()
        idx = pts.fields().indexOf("cluster")
        dp.changeAttributeValues({fid: {idx: int(lbl)} for fid, lbl in zip(fids, labels)})
        pts.triggerRepaint()

        cents = centroids(coords, labels)
        n_noise = sum(1 for lbl in labels if lbl == -1)
        self._notify(f"Clustering : {len(cents)} cluster(s), {n_noise} bruit.", Qgis.Success)
        return json.dumps({"ok": True, "layer": pts.name(), "clusters": len(cents),
                           "noise": n_noise, "eps": eps_v, "field": "cluster"},
                          ensure_ascii=False)

    @BridgeSlot(str, str, str, result=str)
    def renderMapView(self, output_path, width, height):
        """Rend la vue carte courante en image PNG. Brique de la BOUCLE VISION : l'agent
        envoie ensuite cette image a un VLM (NVIDIA) qui la critique pour auto-correction."""
        from qgis.core import QgsMapRendererParallelJob
        from qgis.PyQt.QtCore import QSize
        out = str(output_path or "").strip()
        if not out:
            self._notify("Chemin de sortie requis.", Qgis.Warning)
            return ""
        canvas = self.iface.mapCanvas()
        settings = canvas.mapSettings()

        all_layers = canvas.layers() or list(QgsProject.instance().mapLayers().values())
        if not settings.layers():
            settings.setLayers(all_layers)
        if settings.extent() is None or settings.extent().isEmpty():
            if all_layers:
                settings.setExtent(all_layers[0].extent())

        try:
            w = int(float(width)) if width else (canvas.width() or 1024)
            h = int(float(height)) if height else (canvas.height() or 768)
        except ValueError:
            w, h = (canvas.width() or 1024), (canvas.height() or 768)
        w = max(64, min(w, 4096))
        h = max(64, min(h, 4096))
        settings.setOutputSize(QSize(w, h))

        job = QgsMapRendererParallelJob(settings)
        job.start()
        job.waitForFinished()
        img = job.renderedImage()

        Path(out).parent.mkdir(parents=True, exist_ok=True)
        if not img.save(out):
            self._notify("Echec du rendu de la vue.", Qgis.Warning)
            return ""
        self._notify(f"Vue rendue : {Path(out).name} ({w}x{h}).", Qgis.Success)
        return json.dumps({"ok": True, "path": out, "width": w, "height": h,
                           "layers": len(all_layers)}, ensure_ascii=False)

    @BridgeSlot(str, str, str, result=str)
    def mergeRasterBands(self, layer_ids_json, output_name, output_path):
        try:
            layer_ids = json.loads(layer_ids_json) if layer_ids_json else []
        except json.JSONDecodeError:
            layer_ids = []

        if not isinstance(layer_ids, list):
            layer_ids = []

        raster_layers = []
        for layer_ref in layer_ids:
            layer = self._ensure_raster_layer(layer_ref)
            if layer is None:
                message = f"Raster introuvable ou invalide: {layer_ref}"
                self._notify(message, Qgis.Warning)
                return ""
            raster_layers.append(layer)

        final_output_name = str(output_name or "").strip() or "Fusion_biannuelle"

        try:
            payload = self._run_raster_band_merge(
                raster_layers,
                final_output_name,
                str(output_path or "").strip(),
            )
        except Exception:
            QgsMessageLog.logMessage(
                traceback.format_exc(),
                "QGISAI+",
                level=Qgis.Critical,
            )
            self._notify("La fusion raster a échoué.", Qgis.Critical, duration=6)
            return ""

        self._notify(
            f"Fusion multi-bandes créée : {payload['outputLayerName']}.",
            Qgis.Success,
        )
        return json.dumps(payload, ensure_ascii=False)

    @BridgeSlot(str, float, float, str, str, bool, result=str)
    def createInventoryGrid(
        self,
        layer_ref,
        cell_width,
        cell_height,
        grid_name,
        centroids_name,
        clip_to_source,
    ):
        layer = self._find_layer(layer_ref)
        if layer is None:
            self._notify("Couche source introuvable pour la grille.", Qgis.Warning)
            return ""

        final_grid_name = str(grid_name or "").strip() or f"{layer.name()}_grille"
        final_centroids_name = (
            str(centroids_name or "").strip() or f"{final_grid_name}_centroides"
        )

        try:
            payload = self._run_inventory_grid(
                layer,
                cell_width,
                cell_height,
                final_grid_name,
                final_centroids_name,
                bool(clip_to_source),
            )
        except Exception:
            QgsMessageLog.logMessage(
                traceback.format_exc(),
                "QGISAI+",
                level=Qgis.Critical,
            )
            self._notify(
                "La creation du dispositif d'inventaire a échoué.",
                Qgis.Critical,
                duration=6,
            )
            return ""

        self._notify(
            f"Dispositif d'inventaire créé : {payload['gridLayerName']} + {payload['centroidLayerName']}.",
            Qgis.Success,
        )
        return json.dumps(payload, ensure_ascii=False)

    @BridgeSlot(str, str, str, str, bool, result=str)
    def calculateMnh(self, mns_layer_ref, mnt_layer_ref, output_name, output_path, clamp_negative):
        mns_layer = self._ensure_raster_layer(mns_layer_ref)
        mnt_layer = self._ensure_raster_layer(mnt_layer_ref)
        if mns_layer is None or mnt_layer is None:
            self._notify("MNS ou MNT introuvable.", Qgis.Warning)
            return ""

        formula = "(A-B)*(A>B)" if clamp_negative else "A-B"
        final_output_name = str(output_name or "").strip() or "MNH"

        try:
            payload = self._run_raster_calculator(
                [mns_layer, mnt_layer],
                formula,
                final_output_name,
                str(output_path or "").strip(),
            )
        except Exception:
            QgsMessageLog.logMessage(
                traceback.format_exc(),
                "GeoAI",
                level=Qgis.Critical,
            )
            self._notify("Le calcul du MNH a échoué.", Qgis.Critical, duration=6)
            return ""

        self._notify(f"MNH créé : {payload['outputLayerName']}.", Qgis.Success)
        return json.dumps(payload, ensure_ascii=False)

    def _execute_script_payload(self, script, require_confirmation=True):
        if require_confirmation:
            message_box = QMessageBox(self.iface.mainWindow())
            message_box.setIcon(QMessageBox.Warning)
            message_box.setWindowTitle("QGISAI+")
            message_box.setText("Confirmer l'exécution du script PyQGIS ?")
            message_box.setInformativeText(
                "Le code proposé par l'IA va s'exécuter dans votre session QGIS."
            )
            message_box.setDetailedText(script)
            message_box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            message_box.setDefaultButton(QMessageBox.Cancel)

            if message_box.exec() != QMessageBox.Ok:
                message = "Exécution annulée."
                self._notify(message, Qgis.Warning)
                return {
                    "ok": False,
                    "message": message,
                    "traceback": "",
                }

        context = {
            "__builtins__": __builtins__,
            "iface": self.iface,
            "processing": processing,
            "Qgis": Qgis,
            "QgsCoordinateReferenceSystem": QgsCoordinateReferenceSystem,
            "QgsMessageLog": QgsMessageLog,
            "QgsProject": QgsProject,
            "QgsVectorLayer": QgsVectorLayer,
        }

        # ═══════════════════════════════════════════════════════════════════════
        # EXÉCUTION THREAD-SAFE AVEC TIMEOUT
        # Le script est exécuté dans un thread worker pour éviter les crashes de QGIS
        # ═══════════════════════════════════════════════════════════════════════
        worker = ScriptWorker(script, context, timeout_seconds=30)
        result_container = {}
        
        def on_finished(res):
            result_container['result'] = res
            
        def on_error(err):
            result_container['error'] = err
            
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        
        # Créer un thread pour le worker
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        
        # Event loop pour attendre le résultat (bloquant mais avec timeout)
        loop = QEventLoop()
        worker.finished.connect(loop.quit)
        
        # Timer de sécurité: forcer la sortie après 35s même si le worker bloque
        safety_timer = QTimer()
        safety_timer.setSingleShot(True)
        safety_timer.timeout.connect(loop.quit)
        
        # Démarrer
        thread.start()
        safety_timer.start(35000)  # 35 secondes max
        
        # Bloquer jusqu'à completion ou timeout
        loop.exec()
        
        # Nettoyage
        safety_timer.stop()
        thread.quit()
        thread.wait(5000)  # Attendre 5s max pour le nettoyage
        if thread.isRunning():
            thread.terminate()  # Forcer l'arrêt si nécessaire
        
        # Vérifier le résultat
        if 'error' in result_container:
            error_msg = f"Erreur thread worker: {result_container['error']}"
            QgsMessageLog.logMessage(error_msg, "QGISAI+", level=Qgis.Critical)
            return {
                "ok": False,
                "message": error_msg,
                "traceback": error_msg,
            }
            
        if 'result' not in result_container:
            # Timeout ou crash du worker
            timeout_msg = "Script interrompu (timeout 30s ou crash QGIS protégé)"
            QgsMessageLog.logMessage(timeout_msg, "QGISAI+", level=Qgis.Warning)
            self._notify(timeout_msg, Qgis.Warning, duration=5)
            return {
                "ok": False,
                "message": timeout_msg,
                "traceback": "Le script a dépassé le temps maximum d'exécution (30s)\nou a provoqué une erreur protégée.",
            }
        
        result = result_container['result']
        
        # Notifier selon le résultat
        if result.get("ok"):
            self._notify(result.get("message", "Script exécuté."), Qgis.Success)
        else:
            self._notify(result.get("message", "Erreur script."), Qgis.Critical, duration=6)
            
        return result

    def _execute_script(self, script, require_confirmation=True):
        return self._execute_script_payload(
            script,
            require_confirmation=require_confirmation,
        )["message"]

    @BridgeSlot(str, bool, result=str)
    def runScriptDetailed(self, script, require_confirmation=True):
        return json.dumps(
            self._execute_script_payload(
                script,
                require_confirmation=require_confirmation,
            ),
            ensure_ascii=False,
        )

    @BridgeSlot(str, result=str)
    def runScript(self, script):
        return self._execute_script(script, require_confirmation=True)

    @BridgeSlot(str, result=str)
    def runScriptDirect(self, script):
        return self._execute_script(script, require_confirmation=False)

    # ═══════════════════════════════════════════════════════════════════════════════
    # Fonctions pour l'installation et la gestion d'Ollama
    # ═══════════════════════════════════════════════════════════════════════════════

    @BridgeSlot(result=str)
    def getSystemCapabilities(self):
        """Retourne les capacités du système pour Ollama"""
        if system_capabilities is None:
            return json.dumps({"error": "Module system_capabilities non disponible"})
        return json.dumps(system_capabilities.to_dict())

    @BridgeSlot(result=str)
    def getLayerImportLogs(self):
        """Retourne les logs d'erreurs d'import de couche pour diagnostic."""
        return json.dumps({
            "logs": self._layer_import_logs,
            "count": len(self._layer_import_logs),
        }, ensure_ascii=False)

    @BridgeSlot(result=str)
    def clearLayerImportLogs(self):
        """Efface les logs d'erreurs d'import de couche."""
        self._layer_import_logs.clear()
        return json.dumps({"success": True})

    @BridgeSlot(result=str)
    def getOllamaStatus(self):
        """Retourne le statut d'Ollama"""
        if ollama_installer is None:
            return json.dumps({
                "error": "Module ollama_installer non disponible"
            })
        
        return json.dumps({
            "installed": ollama_installer.is_installed(),
            "running": ollama_installer.is_running(),
            "installed_models": [m["name"] for m in ollama_installer.get_installed_models()],
        })

    @BridgeSlot(str, result=str)
    def installOllamaModel(self, model_name):
        """Installe un modèle Ollama (sans callback de progression pour l'instant)"""
        if ollama_installer is None:
            return json.dumps({"success": False, "error": "Module ollama_installer non disponible"})
        
        try:
            success = ollama_installer.install_model(model_name)
            return json.dumps({"success": success})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @BridgeSlot(str, result=str)
    def removeOllamaModel(self, model_name):
        """Supprime un modèle Ollama"""
        if ollama_installer is None:
            return json.dumps({"success": False, "error": "Module ollama_installer non disponible"})
        
        try:
            success = ollama_installer.remove_model(model_name)
            return json.dumps({"success": success})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @BridgeSlot(result=str)
    def startOllama(self):
        """Démarre le service Ollama s'il est installé mais pas en cours d'exécution"""
        if ollama_installer is None:
            return json.dumps({"success": False, "error": "Module ollama_installer non disponible"})
        
        try:
            result = ollama_installer.start_ollama()
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @BridgeSlot(bool, result=str)
    def ensureOllamaRunning(self, auto_start=True):
        """
        Vérifie qu'Ollama est en cours d'exécution et tente de le démarrer automatiquement si nécessaire
        
        Args:
            auto_start: Si True, tente de démarrer Ollama automatiquement
        
        Returns:
            JSON avec status (running, started, not_installed, start_failed), message, can_proceed
        """
        if ollama_installer is None:
            return json.dumps({
                "status": "error",
                "can_proceed": False,
                "error": "Module ollama_installer non disponible"
            })
        
        try:
            result = ollama_installer.ensure_running(auto_start=auto_start)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({
                "status": "error",
                "can_proceed": False,
                "error": str(e)
            })

    @BridgeSlot(result=str)
    def getOllamaRecommendations(self):
        """Retourne les recommandations de modèles Ollama pour le système"""
        if ollama_installer is None:
            return json.dumps({"error": "Module ollama_installer non disponible"})
        
        try:
            recommendations = ollama_installer.get_recommendations()
            available_models = ollama_installer.get_available_models()
            return json.dumps({
                "recommendations": recommendations,
                "available_models": available_models,
                "system_info": ollama_installer.system.system_info if hasattr(ollama_installer, 'system') else {}
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ═══════════════════════════════════════════════════════════════════════════════
    # Fonctions pour la gestion des dépendances NVIDIA (torch CUDA + earth2studio)
    # ═══════════════════════════════════════════════════════════════════════════════

    @BridgeSlot(result=str)
    def getNvidiaDepsStatus(self):
        """
        Retourne le statut des dépendances NVIDIA (torch CUDA + earth2studio).
        """
        try:
            from .earth2_tool import is_available
        except ImportError:
            import sys
            import os
            sys.path.insert(0, os.path.dirname(__file__))
            from earth2_tool import is_available
        
        ok, reason = is_available()
        
        # Info sur torch si disponible
        torch_info = {}
        try:
            import torch
            torch_info = {
                "version": str(torch.__version__),
                "cuda_available": torch.cuda.is_available(),
                "cuda_version": str(torch.version.cuda) if torch.version.cuda else None,
            }
        except:
            pass
        
        return json.dumps({
            "available": ok,
            "reason": reason if not ok else "",
            "torch": torch_info,
        })

    @BridgeSlot(bool, result=str)
    def installNvidiaDeps(self, force=False):
        """
        Installe les dépendances NVIDIA (torch CUDA + earth2studio).
        
        Args:
            force: Force la réinstallation même si déjà présent
            
        Returns:
            JSON avec success, error, already_installed
        """
        try:
            from .earth2_tool import install_dependencies
        except ImportError:
            import sys
            import os
            sys.path.insert(0, os.path.dirname(__file__))
            from earth2_tool import install_dependencies
        
        try:
            result = install_dependencies(force=force)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
            })


class ScriptWorker(QObject):
    """
    Worker thread pour exécuter des scripts PyQGIS de manière sécurisée.
    Évite les crashes de QGIS en cas de script problématique (boucle infinie, exit(), etc.)
    """
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, script, context, timeout_seconds=30):
        super().__init__()
        self.script = script
        self.context = context
        self.timeout_seconds = timeout_seconds
        self._is_running = False

    @staticmethod
    def validate_script(script):
        """Valide le script avant exécution. Retourne (is_valid, error_message).

        Délègue au module pur `script_validation` (testable en CI sans QGIS).
        """
        return script_validation.validate_script(script)
    
    def run(self):
        """Exécute le script avec protection timeout dans un thread séparé"""
        self._is_running = True
        
        # ═══════════════════════════════════════════════════════════════════════
        # VALIDATION PRÉ-EXÉCUTION
        # ═══════════════════════════════════════════════════════════════════════
        is_valid, error_message = self.validate_script(self.script)
        if not is_valid:
            QgsMessageLog.logMessage(
                f"Script bloqué par validation: {error_message}",
                "QGISAI+",
                level=Qgis.Warning,
            )
            result = {
                "ok": False,
                "message": f"Script bloqué pour sécurité: {error_message}",
                "traceback": error_message
            }
            self._is_running = False
            self.finished.emit(result)
            return
        
        result = {"ok": False, "message": "", "traceback": ""}
        
        # Utiliser un thread séparé pour le script avec timeout
        script_thread = threading.Thread(target=self._execute_script)
        script_thread.daemon = True
        script_thread.start()
        script_thread.join(timeout=self.timeout_seconds)
        
        if script_thread.is_alive():
            # Timeout dépassé - on ne peut pas tuer le thread proprement en Python
            # mais on marque l'exécution comme échouée
            result["ok"] = False
            result["message"] = f"Script interrompu après {self.timeout_seconds}s (timeout)"
            result["traceback"] = "Le script a dépassé le temps d'exécution maximum.\n"
            result["traceback"] += "Causes possibles : boucle infinie, opération trop lourde, ou accès bloquant."
            QgsMessageLog.logMessage(
                f"Script PyQGIS timeout après {self.timeout_seconds}s",
                "QGISAI+",
                level=Qgis.Warning,
            )
        else:
            # Le thread a terminé normalement ou avec une exception
            result = getattr(self, '_execution_result', result)
            
        self._is_running = False
        self.finished.emit(result)
        
    def _execute_script(self):
        """Exécute réellement le script dans le contexte fourni"""
        try:
            # Créer une copie du contexte pour éviter les modifications globales
            local_context = dict(self.context)
            
            # Remplacer exit/quit/sys.exit par des fonctions sans effet
            local_context['exit'] = lambda *args: None
            local_context['quit'] = lambda *args: None
            
            # Exécuter le script
            exec(self.script, local_context, local_context)
            
            self._execution_result = {
                "ok": True,
                "message": "Script exécuté avec succès.",
                "traceback": ""
            }
        except NameError as exc:
            # Erreur de fonction non définie - très commune avec les LLM
            error_message = traceback.format_exc()
            func_name = str(exc).split("'")[1] if "'" in str(exc) else "inconnue"
            helpful_message = (
                f"ERREUR: Fonction '{func_name}' n'existe pas dans PyQGIS.\n\n"
                f"Causes possibles:\n"
                f"- Le LLM a halluciné une fonction inexistante\n"
                f"- Cette fonction n'est pas disponible dans l'API PyQGIS standard\n"
                f"- Il faut utiliser une approche différente\n\n"
                f"Conseil: Redemandez au LLM de corriger le script en utilisant UNIQUEMENT\n"
                f"les classes et méthodes réelles de l'API QGIS (QgsProject, QgsVectorLayer, etc.)"
            )
            QgsMessageLog.logMessage(
                f"Erreur NameError (fonction inexistante) : {error_message}",
                "QGISAI+",
                level=Qgis.Warning,
            )
            self._execution_result = {
                "ok": False,
                "message": helpful_message,
                "traceback": error_message
            }
        except Exception as exc:
            error_message = traceback.format_exc()
            QgsMessageLog.logMessage(
                f"Erreur script IA (worker thread) :\n{error_message}",
                "QGISAI+",
                level=Qgis.Critical,
            )
            self._execution_result = {
                "ok": False,
                "message": f"Erreur lors de l'exécution : {exc}",
                "traceback": error_message
            }


class MainThreadExecutor(QObject):
    execute_requested = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        # Qt6: utiliser Qt.ConnectionType.QueuedConnection
        self.execute_requested.connect(self._execute, Qt.ConnectionType.QueuedConnection)

    @pyqtSlot(object)
    def _execute(self, request):
        try:
            request["result"] = request["callable"]()
        except Exception as exc:
            request["error"] = exc
            request["traceback"] = traceback.format_exc()
        finally:
            request["event"].set()

    def run(self, callback, timeout=15):
        request = {
            "callable": callback,
            "event": threading.Event(),
        }
        self.execute_requested.emit(request)
        if not request["event"].wait(timeout):
            raise TimeoutError("L'appel QGIS a expiré.")

        if "error" in request:
            raise RuntimeError(request.get("traceback") or str(request["error"]))

        return request.get("result")


class ThreadedAssetServer:
    def __init__(self, directory, bridge, executor, request_timeout=120):
        self.directory = directory
        self.bridge = bridge
        self.executor = executor
        self.httpd = None
        self.thread = None
        self.port = None
        self.request_timeout = request_timeout  # Configurable timeout (défaut 120s pour raster)
        # Rate-limiter anti boucle d'agent runaway / abus local. Limite haute
        # pour ne pas pénaliser le tool-calling légitime (nombreux appels rapides).
        self.security = (
            SecurityMiddleware(max_requests=1200, window_seconds=60.0)
            if SecurityMiddleware is not None else None
        )

    def _enforce_rate_limit(self, handler):
        """Renvoie True si la requête est autorisée, sinon répond 429 et False."""
        if self.security is None:
            return True
        client = handler.client_address[0] if handler.client_address else "local"
        allowed, err = self.security.check_rate(client)
        if not allowed:
            self._send_json(handler, 429, {"ok": False, "error": err})
            return False
        return True

    def _send_json(self, handler, status_code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        handler.send_response(status_code)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        _send_cors_headers(handler)
        handler.end_headers()
        handler.wfile.write(body)

    def _read_json_body(self, handler):
        def _log(msg):
            try:
                QgsMessageLog.logMessage(msg, "QGISAI+", level=Qgis.Warning)
            except Exception:
                pass

        return bridge_http.read_json_body(handler, bridge_http.MAX_REQUEST_BYTES, _log)

    def _bridge_call(self, method_name, *args):
        method = getattr(self.bridge, method_name)
        return self.executor.run(lambda: method(*args))

    def _handle_api_request(self, handler, request_method):
        parsed = urlparse(handler.path)
        route = parsed.path
        query = parse_qs(parsed.query)
        body = self._read_json_body(handler) if request_method == "POST" else {}

        try:
            if route == "/api/qgis/health":
                self._send_json(handler, 200, {"ok": True})
                return True

            if route == "/api/qgis/serverInfo":
                self._send_json(handler, 200, {
                    "ok": True,
                    "port": self.port,
                    "url": f"http://127.0.0.1:{self.port}",
                    "bridge_status": "connected",
                    "timestamp": time.time(),
                })
                return True

            if route == "/api/qgis/getLayersList":
                result = self._bridge_call("getLayersList")
            elif route == "/api/qgis/getLayersCatalog":
                result = self._bridge_call("getLayersCatalog")
            elif route == "/api/qgis/getLayerFields":
                result = self._bridge_call(
                    "getLayerFields",
                    query.get("layerId", [""])[0],
                )
            elif route == "/api/qgis/getLayerDiagnostics":
                result = self._bridge_call(
                    "getLayerDiagnostics",
                    query.get("layerId", [""])[0],
                )
            elif route == "/api/qgis/getLayerStatistics":
                result = self._bridge_call(
                    "getLayerStatistics",
                    query.get("layerId", [""])[0],
                    query.get("field", [""])[0],
                )
            elif route == "/api/qgis/openLayers":
                result = self._bridge_call("openLayers")
            elif route == "/api/qgis/openSettings":
                result = self._bridge_call("openSettings")
            elif route == "/api/qgis/pickFile":
                result = self._bridge_call(
                    "pickFile",
                    body.get("fileFilter", ""),
                    body.get("title", ""),
                )
            elif route == "/api/qgis/filterLayer":
                result = self._bridge_call(
                    "filterLayer",
                    body.get("layerId", ""),
                    body.get("subsetString", ""),
                )
            elif route == "/api/qgis/setLayerVisibility":
                result = self._bridge_call(
                    "setLayerVisibility",
                    body.get("layerId", ""),
                    bool(body.get("visible", True)),
                )
            elif route == "/api/qgis/setLayerOpacity":
                result = self._bridge_call(
                    "setLayerOpacity",
                    body.get("layerId", ""),
                    float(body.get("opacity", 1.0)),
                )
            elif route == "/api/qgis/zoomToLayer":
                result = self._bridge_call(
                    "zoomToLayer",
                    body.get("layerId", ""),
                )
            elif route == "/api/qgis/setMapExtent":
                result = self._bridge_call(
                    "setMapExtent",
                    body.get("bbox", ""),
                )
            elif route == "/api/qgis/renameLayer":
                result = self._bridge_call(
                    "renameLayer",
                    body.get("layerId", ""),
                    body.get("name", ""),
                )
            elif route == "/api/qgis/setLayerGroup":
                result = self._bridge_call(
                    "setLayerGroup",
                    body.get("layerId", ""),
                    body.get("groupName", ""),
                )
            elif route == "/api/qgis/reprojectLayer":
                result = self._bridge_call(
                    "reprojectLayer",
                    body.get("layerId", ""),
                    body.get("targetCrs", ""),
                )
            elif route == "/api/qgis/addServiceLayer":
                result = self._bridge_call(
                    "addServiceLayer",
                    body.get("config", ""),
                )
            elif route == "/api/qgis/addDataSource":
                result = self._bridge_call(
                    "addDataSource",
                    body.get("sourceId", ""),
                    body.get("name", ""),
                )
            elif route == "/api/qgis/listDataSources":
                try:
                    from data_catalog import list_sources
                except ImportError:
                    from .data_catalog import list_sources
                category = body.get("category") or (query.get("category", [None])[0])
                result = json.dumps(
                    {"sources": list_sources(category)}, ensure_ascii=False)
            elif route == "/api/qgis/runDossier":
                result = self._bridge_call("runDossier", body.get("dossierId", ""))
            elif route == "/api/qgis/listDossiers":
                try:
                    from dossier_blueprint import list_dossiers
                except ImportError:
                    from .dossier_blueprint import list_dossiers
                result = json.dumps({"dossiers": list_dossiers()}, ensure_ascii=False)
            elif route == "/api/qgis/addRasterFile":
                result = self._bridge_call(
                    "addRasterFile",
                    body.get("filePath", ""),
                    body.get("layerName", ""),
                )
            elif route == "/api/qgis/addRemoteRaster":
                result = self._bridge_call(
                    "addRemoteRaster",
                    body.get("url", ""),
                    body.get("layerName", ""),
                )
            elif route == "/api/qgis/loadSatelliteBands":
                bands = body.get("bands", "")
                if isinstance(bands, (list, tuple)):
                    bands = json.dumps(list(bands))
                result = self._bridge_call(
                    "loadSatelliteBands",
                    body.get("bbox", ""),
                    body.get("collection", "sentinel-2-l2a"),
                    bands,
                    body.get("datetime", ""),
                )
            elif route == "/api/qgis/addGeoJsonLayer":
                result = self._bridge_call(
                    "addGeoJsonLayer",
                    body.get("geojson", ""),
                    body.get("layerName", ""),
                )
            elif route == "/api/qgis/segmentRasterWithSAM":
                result = self._bridge_call(
                    "segmentRasterWithSAM",
                    body.get("options", ""),
                )
            elif route == "/api/qgis/forecastWeatherWithEarth2":
                result = self._bridge_call(
                    "forecastWeatherWithEarth2",
                    body.get("options", ""),
                )
            elif route == "/api/qgis/exportProjectReport":
                result = self._bridge_call(
                    "exportProjectReport",
                    body.get("options", ""),
                )
            elif route == "/api/qgis/calculateRasterFormula":
                result = self._bridge_call(
                    "calculateRasterFormula",
                    body.get("layerIds", "[]"),
                    body.get("formula", ""),
                    body.get("outputName", ""),
                    body.get("outputPath", ""),
                )
            elif route == "/api/qgis/computeSpectralIndex":
                band_map = body.get("bandMap", "{}")
                if isinstance(band_map, (dict, list)):
                    band_map = json.dumps(band_map)
                result = self._bridge_call(
                    "computeSpectralIndex",
                    body.get("layerId", ""),
                    body.get("indexId", ""),
                    band_map,
                    body.get("outputPath", ""),
                )
            elif route == "/api/qgis/computeRasterDifference":
                result = self._bridge_call(
                    "computeRasterDifference",
                    body.get("layerA", ""),
                    body.get("layerB", ""),
                    body.get("outputPath", ""),
                )
            elif route == "/api/qgis/zonalStatistics":
                result = self._bridge_call(
                    "zonalStatistics",
                    body.get("rasterId", ""),
                    body.get("polygonId", ""),
                    body.get("prefix", ""),
                )
            elif route == "/api/qgis/bufferLayer":
                result = self._bridge_call(
                    "bufferLayer",
                    body.get("layerId", ""),
                    str(body.get("distance", "0")),
                    body.get("outputName", ""),
                )
            elif route == "/api/qgis/saveVectorLayer":
                result = self._bridge_call(
                    "saveVectorLayer",
                    body.get("layerId", ""),
                    body.get("outputPath", ""),
                    body.get("driver", "GPKG"),
                )
            elif route == "/api/qgis/exportPrintLayout":
                result = self._bridge_call(
                    "exportPrintLayout",
                    body.get("title", ""),
                    body.get("outputPath", ""),
                    body.get("format", "png"),
                    body.get("template", ""),
                )
            elif route == "/api/qgis/exportLayoutSpec":
                spec = body.get("spec", "{}")
                if isinstance(spec, (dict, list)):
                    spec = json.dumps(spec)
                result = self._bridge_call(
                    "exportLayoutSpec",
                    body.get("title", ""),
                    body.get("outputPath", ""),
                    body.get("format", "png"),
                    spec,
                )
            elif route == "/api/qgis/classifyRaster":
                result = self._bridge_call(
                    "classifyRaster",
                    body.get("layerId", ""),
                    body.get("schemeId", ""),
                )
            elif route == "/api/qgis/renderMapView":
                result = self._bridge_call(
                    "renderMapView",
                    body.get("outputPath", ""),
                    str(body.get("width", "")),
                    str(body.get("height", "")),
                )
            elif route == "/api/qgis/classifyChange":
                result = self._bridge_call(
                    "classifyChange",
                    body.get("layerId", ""),
                    body.get("schemeId", ""),
                )
            elif route == "/api/qgis/exportAtlas":
                result = self._bridge_call(
                    "exportAtlas",
                    body.get("coverageId", ""),
                    body.get("outputPath", ""),
                    body.get("atlasId", ""),
                    body.get("pageField", ""),
                )
            elif route == "/api/qgis/suitabilityAnalysis":
                criteria = body.get("criteria", "[]")
                if isinstance(criteria, (list, dict)):
                    criteria = json.dumps(criteria)
                result = self._bridge_call(
                    "suitabilityAnalysis", criteria, body.get("outputPath", ""))
            elif route == "/api/qgis/hotspotAnalysis":
                result = self._bridge_call(
                    "hotspotAnalysis",
                    body.get("pointId", ""),
                    str(body.get("radius", "")),
                    body.get("outputPath", ""),
                )
            elif route == "/api/qgis/computeTerrain":
                result = self._bridge_call(
                    "computeTerrain",
                    body.get("demId", ""),
                    body.get("analysis", "slope"),
                    body.get("outputPath", ""),
                )
            elif route == "/api/qgis/clusterPoints":
                result = self._bridge_call(
                    "clusterPoints",
                    body.get("pointId", ""),
                    str(body.get("eps", "")),
                    str(body.get("minPts", "")),
                )
            elif route == "/api/qgis/mergeRasterBands":
                result = self._bridge_call(
                    "mergeRasterBands",
                    body.get("layerIds", "[]"),
                    body.get("outputName", ""),
                    body.get("outputPath", ""),
                )
            elif route == "/api/qgis/createInventoryGrid":
                result = self._bridge_call(
                    "createInventoryGrid",
                    body.get("layerRef", body.get("layerId", "")),
                    float(body.get("cellWidth", 0) or 0),
                    float(body.get("cellHeight", 0) or 0),
                    body.get("gridName", ""),
                    body.get("centroidsName", ""),
                    bool(body.get("clipToSource", True)),
                )
            elif route == "/api/qgis/calculateMnh":
                result = self._bridge_call(
                    "calculateMnh",
                    body.get("mnsLayerId", ""),
                    body.get("mntLayerId", ""),
                    body.get("outputName", ""),
                    body.get("outputPath", ""),
                    bool(body.get("clampNegative", True)),
                )
            elif route == "/api/qgis/applyParcelStylePreset":
                result = self._bridge_call(
                    "applyParcelStylePreset",
                    body.get("layerId", ""),
                    body.get("presetId", ""),
                )
            elif route == "/api/qgis/setLayerLabels":
                result = self._bridge_call(
                    "setLayerLabels",
                    body.get("layerId", ""),
                    body.get("fieldName", ""),
                    bool(body.get("enabled", True)),
                )
            elif route == "/api/qgis/applyQmlStyle":
                result = self._bridge_call(
                    "applyQmlStyle",
                    body.get("layerId", ""),
                    body.get("qml", ""),
                )
            elif route == "/api/qgis/applySymbologyPreset":
                result = self._bridge_call(
                    "applySymbologyPreset",
                    body.get("layerId", ""),
                    body.get("presetId", ""),
                    body.get("field", ""),
                )
            elif route == "/api/qgis/splitSelectedLayerByLine":
                result = self._bridge_call(
                    "splitSelectedLayerByLine",
                    body.get("layerId", ""),
                    body.get("lineWkt", ""),
                    body.get("outputName", ""),
                )
            elif route == "/api/qgis/runScript":
                result = self._bridge_call(
                    "runScript",
                    body.get("script", ""),
                )
            elif route == "/api/qgis/runScriptDirect":
                result = self._bridge_call(
                    "runScriptDirect",
                    body.get("script", ""),
                )
            elif route == "/api/qgis/runScriptDetailed":
                result = self._bridge_call(
                    "runScriptDetailed",
                    body.get("script", ""),
                    bool(body.get("requireConfirmation", True)),
                )
            elif route == "/api/qgis/getSystemSpecs":
                # Retourne les vraies specs système (RAM, CPU, GPU) via psutil + nvidia-smi
                if system_capabilities is not None:
                    info = system_capabilities.system_info
                    gpu = info.get("gpu", {})
                    self._send_json(handler, 200, {
                        "ok": True,
                        "ram_total_gb": info.get("ram_total_gb", 0),
                        "ram_available_gb": info.get("ram_available_gb", 0),
                        "cpu_logical": info.get("cpu_count", 0),
                        "cpu_physical": info.get("cpu_physical_count", 0),
                        "processor": info.get("processor", ""),
                        "platform": info.get("platform", ""),
                        "gpu_name": gpu.get("gpu_name") or "",
                        "gpu_vram_gb": gpu.get("gpu_memory_gb") or 0,
                        "gpu_has_cuda": gpu.get("supports_cuda", False),
                        "source": "python_psutil",
                    })
                    return True
                else:
                    self._send_json(handler, 200, {"ok": False, "source": "unavailable"})
                    return True
            elif route == "/api/qgis/getLayerImportLogs":
                result = self._bridge_call("getLayerImportLogs")
                self._send_json(handler, 200, {"ok": True, "result": result})
                return True
            elif route == "/api/qgis/clearLayerImportLogs":
                result = self._bridge_call("clearLayerImportLogs")
                self._send_json(handler, 200, {"ok": True, "result": result})
                return True
            elif route == "/api/qgis/captureMapSnapshot":
                result = self._bridge_call("captureMapSnapshot")
                self._send_json(handler, 200, {"ok": True, "result": result})
                return True
            else:
                return False
        except Exception as exc:
            self._send_json(
                handler,
                500,
                {
                    "ok": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            return True

        self._send_json(handler, 200, {"ok": True, "result": result})
        return True

    # ========================================================================
    # LLM Gateway (Sprint 1) — endpoints /api/llm/*
    # ========================================================================
    def _handle_llm_request(self, handler, request_method):
        parsed = urlparse(handler.path)
        route = parsed.path
        body = self._read_json_body(handler) if request_method == "POST" else {}

        # Clés API : persistance transparente + réinjection. La 1ère clé fournie
        # par le frontend est mémorisée (QgsSettings) ; ensuite chaque requête est
        # complétée depuis le stockage/env si le frontend n'en envoie pas.
        if isinstance(body, dict) and route != "/api/llm/credentials":
            body_keys = body.get("api_keys") or {}
            if isinstance(body_keys, dict):
                for provider, value in body_keys.items():
                    if value and provider in _API_KEY_PROVIDERS:
                        _store_api_key(provider, value)
                merged = dict(_stored_api_keys())
                merged.update({k: v for k, v in body_keys.items() if v})
                if merged:
                    body["api_keys"] = merged

        try:
            try:
                from . import llm_gateway, llm_installer
            except ImportError as exc:
                self._send_json(handler, 500, {"ok": False, "error": f"llm_gateway indisponible: {exc}"})
                return True

            if route == "/api/llm/credentials":
                # GET : présence des clés (jamais le secret). POST : enregistre une clé.
                if request_method == "GET":
                    stored = _stored_api_keys()
                    self._send_json(handler, 200, {
                        "ok": True,
                        "configured": {p: bool(stored.get(p)) for p in _API_KEY_PROVIDERS},
                    })
                    return True
                provider = body.get("provider", "")
                if provider not in _API_KEY_PROVIDERS:
                    self._send_json(handler, 400, {"ok": False, "error": "provider invalide"})
                    return True
                _store_api_key(provider, body.get("key", ""))
                self._send_json(handler, 200, {"ok": True})
                return True

            if route == "/api/llm/health":
                status = llm_gateway.health()
                self._send_json(handler, 200, {"ok": True, **status})
                return True

            if route == "/api/llm/install":
                # Verifier si deja installe
                if llm_installer.is_vendor_ready():
                    self._send_json(handler, 200, {"ok": True, "status": "ready", "already_installed": True})
                    return True
                # Lance l'install vendor en tache de fond avec log immédiat
                llm_installer._log("api", "Endpoint /api/llm/install appelé - démarrage thread")
                thread = llm_installer.install_async()
                self._send_json(handler, 202, {"ok": True, "status": "installing", "thread_started": thread.is_alive()})
                return True

            if route == "/api/llm/install_status":
                # Retourne le statut détaillé avec logs pour debug UI
                status = llm_installer.get_install_status()
                self._send_json(handler, 200, {"ok": True, **status})
                return True

            if route == "/api/llm/install_sync":
                # Installation synchrone pour debug (bloquant mais informatif)
                try:
                    result = llm_installer.install_if_needed()
                    self._send_json(handler, 200, {"ok": True, **result})
                except Exception as e:
                    self._send_json(handler, 500, {"ok": False, "error": str(e)})
                return True

            if route == "/api/llm/diagnostic":
                # Endpoint de diagnostic complet
                import sys
                import platform
                diag = {
                    "python_version": sys.version,
                    "platform": platform.platform(),
                    "plugin_dir": str(llm_installer.PLUGIN_DIR),
                    "vendor_dir": str(llm_installer.VENDOR_DIR),
                    "vendor_exists": llm_installer.VENDOR_DIR.exists(),
                    "marker_exists": llm_installer.MARKER_FILE.exists(),
                    "vendor_ready": llm_installer.is_vendor_ready(),
                    "sys_path": sys.path[:5],  # First 5 entries
                    "pip_path": None,
                    "layer_import_logs": getattr(self, '_layer_import_logs', []),
                    "layer_import_error_count": len(getattr(self, '_layer_import_logs', [])),
                }
                try:
                    import subprocess
                    r = subprocess.run([sys.executable, "-m", "pip", "--version"],
                                     capture_output=True, text=True, timeout=10)
                    diag["pip_path"] = r.stdout.strip() if r.returncode == 0 else f"error: {r.stderr}"
                except Exception as e:
                    diag["pip_path"] = f"exception: {e}"
                self._send_json(handler, 200, {"ok": True, **diag})
                return True

            # ── Agent endpoints (Sprint 2) ────────────────────────────────
            if route == "/api/agent/memory":
                try:
                    from .agent_memory import get_memory
                    mem = get_memory()
                    self._send_json(handler, 200, {"ok": True, **mem.stats()})
                except Exception as e:
                    self._send_json(handler, 500, {"ok": False, "error": str(e)})
                return True

            if route == "/api/agent/memory/search":
                try:
                    from .agent_memory import get_memory
                    query = body.get("query", "")
                    mem = get_memory()
                    results = mem.search(query, top_k=body.get("top_k", 5))
                    self._send_json(handler, 200, {"ok": True, "results": [
                        {"key": e.key, "value": e.value, "category": e.category,
                         "confidence": e.confidence, "tags": e.tags}
                        for e in results
                    ]})
                except Exception as e:
                    self._send_json(handler, 500, {"ok": False, "error": str(e)})
                return True

            if route == "/api/agent/guardrails/check":
                try:
                    from .agent_guardrails import get_guardrails
                    code = body.get("code", "")
                    user_msg = body.get("user_message", "")
                    gr = get_guardrails()
                    if code:
                        result = gr.check_pyqgis_code(code)
                    else:
                        result = gr.check_input(user_msg)
                    self._send_json(handler, 200, {"ok": True,
                        "passed": result.passed,
                        "risk_level": result.risk_level.value,
                        "rule": result.rule_triggered,
                        "message": result.message,
                        "alternative": result.suggested_alternative,
                    })
                except Exception as e:
                    self._send_json(handler, 500, {"ok": False, "error": str(e)})
                return True

            if route == "/api/agent/plan":
                try:
                    from .agent_runner import AgentRunner, AgentMode
                    user_request = body.get("user_request", "")
                    layer_context = body.get("layer_context", "")
                    auto_mode = bool(body.get("auto_mode", False))
                    api_keys = body.get("api_keys", {})
                    model = body.get("model", "smart-default")

                    runner = AgentRunner(
                        mode=AgentMode.AUTO if auto_mode else AgentMode.PLAN_CONFIRM
                    )
                    runner.set_llm_chat(llm_gateway.chat)

                    guard_result = runner.validate_input(user_request)
                    if not guard_result.passed:
                        self._send_json(handler, 400, {
                            "ok": False,
                            "blocked": True,
                            "risk_level": guard_result.risk_level.value,
                            "message": guard_result.message,
                            "alternative": guard_result.suggested_alternative,
                        })
                        return True

                    plan = runner.build_plan(user_request, layer_context, api_keys, model)
                    self._send_json(handler, 200, {"ok": True,
                        "plan_id": plan.plan_id,
                        "status": plan.status,
                        "summary": plan.summary,
                        "steps": [
                            {
                                "step_id": s.step_id,
                                "description": s.description,
                                "action_type": s.action_type,
                                "risk_level": s.risk_level.value,
                                "status": s.status.value,
                                "has_code": bool(s.code),
                            }
                            for s in plan.steps
                        ],
                    })
                except Exception as e:
                    self._send_json(handler, 500, {"ok": False, "error": str(e)})
                return True

            # ── RAG endpoints (Sprint 3) ──────────────────────────────
            if route == "/api/rag/stats":
                try:
                    from .rag_indexer import get_indexer
                    self._send_json(handler, 200, {"ok": True, **get_indexer().stats()})
                except Exception as e:
                    self._send_json(handler, 500, {"ok": False, "error": str(e)})
                return True

            if route == "/api/rag/search":
                try:
                    from .rag_indexer import get_indexer
                    query = body.get("query", "")
                    top_k = int(body.get("top_k", 5))
                    collections = body.get("collections")
                    # Active les embeddings sémantiques NIM si une clé est fournie.
                    nim_key = (body.get("api_keys") or {}).get("nvidia_nim")
                    get_indexer()._store.configure(nim_key)
                    context = get_indexer().search_for_prompt(query, top_k=top_k, collections=collections)
                    results_raw = get_indexer()._store.search(query, top_k=top_k)
                    self._send_json(handler, 200, {"ok": True,
                        "context": context,
                        "results": [
                            {"doc_id": r.doc_id, "content": r.content[:300],
                             "score": r.score, "collection": r.collection,
                             "metadata": r.metadata}
                            for r in results_raw
                        ],
                    })
                except Exception as e:
                    self._send_json(handler, 500, {"ok": False, "error": str(e)})
                return True

            if route == "/api/rag/index/pyqgis":
                try:
                    from .rag_indexer import get_indexer
                    force = bool(body.get("force", False))
                    nim_key = (body.get("api_keys") or {}).get("nvidia_nim")
                    get_indexer()._store.configure(nim_key)
                    n = get_indexer().index_pyqgis_knowledge(force=force)
                    self._send_json(handler, 200, {"ok": True, "indexed": n})
                except Exception as e:
                    self._send_json(handler, 500, {"ok": False, "error": str(e)})
                return True

            if route == "/api/rag/index/layers":
                try:
                    from .rag_indexer import get_indexer
                    layers_info = body.get("layers", [])
                    n = get_indexer().index_project_layers(layers_info)
                    self._send_json(handler, 200, {"ok": True, "indexed": n})
                except Exception as e:
                    self._send_json(handler, 500, {"ok": False, "error": str(e)})
                return True

            if route == "/api/rag/note":
                try:
                    from .rag_indexer import get_indexer
                    content = body.get("content", "")
                    title = body.get("title", "")
                    tags = body.get("tags", [])
                    ids = get_indexer().add_user_note(content, title=title, tags=tags)
                    self._send_json(handler, 200, {"ok": True, "doc_ids": ids})
                except Exception as e:
                    self._send_json(handler, 500, {"ok": False, "error": str(e)})
                return True

            if route == "/api/llm/models":
                if not llm_installer.is_vendor_ready():
                    self._send_json(handler, 503, {"ok": False, "error": "gateway_not_ready"})
                    return True
                self._send_json(handler, 200, {"ok": True, "aliases": llm_gateway.list_aliases()})
                return True

            if route == "/api/llm/budget":
                self._send_json(handler, 200, {"ok": True, **llm_gateway.get_budget()})
                return True

            if route == "/api/llm/chat":
                if not llm_installer.is_vendor_ready():
                    self._send_json(handler, 503, {"ok": False, "error": "gateway_not_ready"})
                    return True

                model = body.get("model", "smart-default")
                messages = body.get("messages", [])
                stream = bool(body.get("stream", False))
                api_keys = body.get("api_keys", {}) or {}
                temperature = body.get("temperature")
                max_tokens = body.get("max_tokens")
                tools = body.get("tools")

                if stream:
                    self._stream_llm_response(
                        handler, model, messages, api_keys,
                        temperature, max_tokens, tools,
                    )
                    return True

                result = llm_gateway.chat(
                    model=model,
                    messages=messages,
                    api_keys=api_keys,
                    stream=False,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                )
                self._send_json(handler, 200, {"ok": True, "response": result})
                return True

            if route == "/api/llm/smart":
                # Federation multi-agents : routage -> agent specialise -> safety.
                if not llm_installer.is_vendor_ready():
                    self._send_json(handler, 503, {"ok": False, "error": "gateway_not_ready"})
                    return True

                query = body.get("query") or body.get("message") or ""
                if not query:
                    self._send_json(handler, 400, {"ok": False, "error": "missing 'query'"})
                    return True

                api_keys = body.get("api_keys", {}) or {}
                context = body.get("context") or {}
                auto_route = bool(body.get("auto_route", True))
                stream = bool(body.get("stream", False))

                try:
                    from agent_federation import AgentFederation
                except ImportError:
                    from .agent_federation import AgentFederation

                if stream:
                    self._stream_smart_response(
                        handler, query, api_keys, context=context, auto_route=auto_route,
                    )
                    return True

                logs = []
                federation = AgentFederation(api_keys)
                result = federation.process(
                    query,
                    auto_route=auto_route,
                    context=context,
                    progress_callback=lambda m: logs.append({"i": len(logs), "message": m}),
                )
                # AgentResult (dataclass) -> dict JSON-serialisable
                result["agent_results"] = [
                    {
                        "agent_type": r.agent_type.value,
                        "success": r.success,
                        "content": r.content,
                        "latency_ms": r.latency_ms,
                        "model_used": r.model_used,
                        "error": r.error,
                    }
                    for r in result.get("agent_results", [])
                ]
                result["progress_logs"] = logs
                self._send_json(handler, 200, {"ok": True, "result": result})
                return True

            if route == "/api/llm/agent":
                # Boucle agentique tool-calling : LLM -> outils QGIS -> LLM -> reponse.
                if not llm_installer.is_vendor_ready():
                    self._send_json(handler, 503, {"ok": False, "error": "gateway_not_ready"})
                    return True

                messages = body.get("messages") or []
                if not messages:
                    query = body.get("query") or body.get("message") or ""
                    if query:
                        messages = [{"role": "user", "content": query}]
                if not messages:
                    self._send_json(handler, 400, {"ok": False, "error": "missing 'messages' or 'query'"})
                    return True

                api_keys = body.get("api_keys", {}) or {}
                model = body.get("model", "smart-default")
                # Autonomie multi-etapes : defaut genereux, plafond dur a 100.
                max_iters = min(int(body.get("max_iters", 30)), 100)
                auto_mode = bool(body.get("auto_mode", False))
                system = body.get("system")
                stream = bool(body.get("stream", False))
                # Le bridge QGIS est servi par ce meme serveur (multi-thread) : on
                # route les appels d'outils vers notre propre hote.
                host = handler.headers.get("Host", "127.0.0.1")
                bridge_url = f"http://{host}"

                try:
                    from agent_tools import run_tool_loop
                except ImportError:
                    from .agent_tools import run_tool_loop

                if stream:
                    self._stream_agent_response(
                        handler, messages, api_keys,
                        model=model, max_iters=max_iters, auto_mode=auto_mode,
                        system=system, bridge_url=bridge_url,
                    )
                    return True

                result = run_tool_loop(
                    messages, api_keys,
                    model=model, max_iters=max_iters, auto_mode=auto_mode,
                    system=system, bridge_url=bridge_url,
                )
                self._send_json(handler, 200, {"ok": True, "result": result})
                return True

            if route == "/api/llm/agent/respond":
                # Reprise d'une boucle agentique interrompue par ask_user.
                session_id = body.get("session_id", "")
                selected_option = body.get("selected_option", "")
                if not session_id or not selected_option:
                    self._send_json(handler, 400, {"ok": False, "error": "session_id et selected_option requis"})
                    return True
                try:
                    from agent_tools import resume_tool_loop
                except ImportError:
                    from .agent_tools import resume_tool_loop
                result = resume_tool_loop(session_id, selected_option)
                if "error" in result:
                    self._send_json(handler, 404, {"ok": False, "error": result["error"]})
                    return True
                self._send_json(handler, 200, {"ok": True, "result": result})
                return True

            if route == "/api/llm/critiqueView":
                # BOUCLE VISION fermee : rend la vue carte -> envoie l'image au VLM
                # (modele vision NVIDIA) -> critique + score + correctifs.
                if not llm_installer.is_vendor_ready():
                    self._send_json(handler, 503, {"ok": False, "error": "gateway_not_ready"})
                    return True

                api_keys = body.get("api_keys", {}) or {}
                intent = body.get("intent", "") or "carte cartographique"
                layout_meta = body.get("layout_meta") or {}
                model = body.get("model") or "nvidia_nim/meta/llama-3.2-90b-vision-instruct"

                tmp_base = os.path.realpath(tempfile.gettempdir())
                image_path = body.get("imagePath")
                if image_path:
                    # Securite : un chemin fourni par le client doit etre un PNG/JPG situe
                    # dans le repertoire temporaire (pas de path traversal ni de symlink).
                    real = os.path.realpath(image_path)
                    if (not (real == tmp_base or real.startswith(tmp_base + os.sep))
                            or os.path.splitext(real)[1].lower() not in (".png", ".jpg", ".jpeg")
                            or os.path.islink(image_path)):
                        self._send_json(handler, 400, {"ok": False, "error": "invalid_image_path"})
                        return True
                    image_path = real
                else:
                    image_path = os.path.join(tmp_base, "critique_view.png")
                    self._bridge_call("renderMapView", image_path,
                                      str(body.get("width", "")), str(body.get("height", "")))
                if not image_path or not os.path.exists(image_path):
                    self._send_json(handler, 500, {"ok": False, "error": "render_failed"})
                    return True

                import base64
                with open(image_path, "rb") as fh:
                    b64 = base64.b64encode(fh.read()).decode("ascii")

                try:
                    from vision_critique import (
                        build_critique_prompt, completeness_score, suggest_fixes)
                except ImportError:
                    from .vision_critique import (
                        build_critique_prompt, completeness_score, suggest_fixes)

                prompt = build_critique_prompt(intent, layout_meta)
                messages = llm_gateway.build_vision_messages(prompt, b64)
                resp = llm_gateway.chat(
                    model, messages, api_keys=api_keys,
                    max_tokens=int(body.get("max_tokens", 400)))
                msg = (resp.get("choices") or [{}])[0].get("message", {})
                critique = msg.get("content") or msg.get("reasoning_content") or ""
                score = completeness_score(layout_meta)
                self._send_json(handler, 200, {
                    "ok": True,
                    "critique": critique,
                    "model_used": resp.get("_gateway", {}).get("model_used"),
                    "score": score["score"],
                    "missing": score["missing"],
                    "fixes": suggest_fixes(layout_meta),
                    "render_path": image_path,
                })
                return True

            if route == "/api/llm/autoImproveLayout":
                # AUTO-AMELIORATION MULTI-TOURS : part du meilleur gabarit, ajoute a chaque
                # tour les elements manquants et re-rend jusqu'au score cible, puis critique
                # le rendu final via le VLM (boucle vision autonome).
                if not llm_installer.is_vendor_ready() and bool(body.get("with_vlm", True)):
                    self._send_json(handler, 503, {"ok": False, "error": "gateway_not_ready"})
                    return True

                api_keys = body.get("api_keys", {}) or {}
                intent = body.get("intent", "") or "carte cartographique"
                title = body.get("title", "") or "Carte QGISIA+"
                model = body.get("model") or "nvidia_nim/meta/llama-3.2-90b-vision-instruct"
                target = float(body.get("target_score", 1.0))
                max_iters = max(1, min(int(body.get("max_iters", 4)), 8))
                with_vlm = bool(body.get("with_vlm", True))
                try:
                    from layout_auto import (
                        pick_best_template, augment_to_complete, score_elements)
                    from layout_specs import get_template
                    from vision_critique import build_critique_prompt, suggest_fixes
                except ImportError:
                    from .layout_auto import (
                        pick_best_template, augment_to_complete, score_elements)
                    from .layout_specs import get_template
                    from .vision_critique import build_critique_prompt, suggest_fixes

                best = pick_best_template(prefer=body.get("prefer"))
                tmpl = get_template(best["template"]) or {}
                elements = list(tmpl.get("elements", []))
                page_size = tmpl.get("page_size", "A4")
                orientation = tmpl.get("orientation", "landscape")
                out = os.path.join(os.path.realpath(tempfile.gettempdir()), "auto_layout.png")

                iterations = []
                final_payload = None
                for i in range(max_iters):
                    sc = score_elements(elements)
                    iterations.append({"iter": i, "score": sc["score"], "missing": sc["missing"]})
                    spec = {"page_size": page_size, "orientation": orientation,
                            "elements": elements}
                    raw = self._bridge_call(
                        "exportLayoutSpec", title, out, "png", json.dumps(spec))
                    try:
                        final_payload = json.loads(raw) if raw else None
                    except (ValueError, TypeError):
                        final_payload = None
                    if sc["score"] >= target:
                        break
                    elements = augment_to_complete(elements)

                if final_payload is None or not os.path.exists(out):
                    self._send_json(handler, 500, {
                        "ok": False, "error": "export_failed", "iterations": iterations})
                    return True

                layout_meta = final_payload.get("layout_meta") or {}
                final_score = score_elements(elements)
                critique, model_used = "", None
                if with_vlm:
                    import base64
                    with open(out, "rb") as fh:
                        b64 = base64.b64encode(fh.read()).decode("ascii")
                    prompt = build_critique_prompt(intent, layout_meta)
                    try:
                        resp = llm_gateway.chat(
                            model, llm_gateway.build_vision_messages(prompt, b64),
                            api_keys=api_keys, max_tokens=int(body.get("max_tokens", 400)))
                        msg = (resp.get("choices") or [{}])[0].get("message", {})
                        critique = msg.get("content") or msg.get("reasoning_content") or ""
                        model_used = resp.get("_gateway", {}).get("model_used")
                    except Exception as exc:  # noqa: BLE001
                        critique = f"(VLM indisponible: {exc})"

                self._send_json(handler, 200, {
                    "ok": True,
                    "chosen_template": best["template"],
                    "iterations": iterations,
                    "turns": len(iterations),
                    "final_score": final_score["score"],
                    "final_missing": final_score["missing"],
                    "fixes": suggest_fixes(layout_meta),
                    "critique": critique,
                    "model_used": model_used,
                    "render_path": out,
                    "layout_meta": layout_meta,
                })
                return True

            if route == "/api/llm/autoStudy":
                # ETUDE TERRITORIALE AUTONOME : deroule un plan (study_plan) en enchainant
                # les outils QGIS, puis produit une planche + un rapport + une critique vision.
                api_keys = body.get("api_keys", {}) or {}
                theme = (body.get("theme") or "vegetation").strip()
                context = body.get("context") or {}
                bbox = body.get("bbox") or context.get("bbox") or ""
                try:
                    from study_plan import build_plan
                    from study_actions import REPORT_TEMPLATE_BY_THEME
                    from report_templates import render_report
                except ImportError:
                    from .study_plan import build_plan
                    from .study_actions import REPORT_TEMPLATE_BY_THEME
                    from .report_templates import render_report

                plan = build_plan(theme, context)
                if not plan:
                    self._send_json(handler, 400, {"ok": False, "error": f"theme inconnu: {theme}"})
                    return True

                st = {"bands": {}, "indices": [], "last_raster": None,
                      "layout": None, "layout_meta": None, "report": ""}
                steps_report = []
                for step in plan:
                    action = step.get("action")
                    p = step.get("params", {}) or {}
                    ok, detail = False, ""
                    try:
                        if action == "add_basemap":
                            msg = self.addDataSource(p.get("sourceId", "osm-standard"), "")
                            ok = "ajout" in msg.lower()
                            detail = msg
                        elif action == "load_satellite":
                            raw = self.loadSatelliteBands(
                                bbox or p.get("bbox", ""), p.get("collection", "sentinel-2-l2a"),
                                json.dumps(p.get("bands", ["RED", "NIR"])), p.get("datetime", ""))
                            d = json.loads(raw) if raw else {}
                            st["bands"] = d.get("bands", {}) or {}
                            ok = d.get("ok") is True
                            detail = f"item={d.get('item')} bands={list(st['bands'])}"
                        elif action == "compute_index":
                            b = st["bands"]
                            if "NIR" in b and "RED" in b:
                                bm = json.dumps({"NIR": b["NIR"], "RED": b["RED"]})
                                raw = self.computeSpectralIndex("scene", p.get("index", "ndvi"), bm, "")
                                d = json.loads(raw) if raw else {}
                                if d.get("ok"):
                                    st["last_raster"] = d.get("outputLayerName")
                                    st["indices"].append(d.get("outputLayerName"))
                                ok = d.get("ok") is True
                                detail = d.get("outputLayerName", "")
                            else:
                                detail = "bandes NIR/RED indisponibles (skip)"
                        elif action == "detect_change":
                            if len(st["indices"]) >= 2:
                                raw = self.computeRasterDifference(
                                    st["indices"][-1], st["indices"][-2], "")
                                d = json.loads(raw) if raw else {}
                                ok = d.get("ok") is True
                                detail = d.get("outputLayerName", "")
                            else:
                                detail = "2 dates requises (skip)"
                        elif action == "classify":
                            if st["last_raster"]:
                                raw = self.classifyRaster(st["last_raster"], "ndvi_vegetation")
                                ok = bool(raw)
                                detail = st["last_raster"]
                            else:
                                detail = "aucun raster a classer (skip)"
                        elif action == "zonal_stats":
                            detail = "necessite une couche de polygones (skip)"
                        elif action == "layout":
                            out = os.path.join(os.path.realpath(tempfile.gettempdir()), "study_layout.png")
                            raw = self.exportPrintLayout(f"Etude {theme}", out, "png", "a4_paysage_pro")
                            d = json.loads(raw) if raw else {}
                            ok = d.get("ok") is True
                            st["layout"] = out if ok else None
                            st["layout_meta"] = d.get("layout_meta")
                            detail = out
                        elif action == "report":
                            tpl = REPORT_TEMPLATE_BY_THEME.get(theme, "diagnostic_vegetation")
                            md = render_report(tpl, context)
                            st["report"] = md
                            ok = bool(md)
                            detail = f"{len(md)} caracteres"
                        else:
                            detail = "action inconnue"
                    except Exception as exc:  # noqa: BLE001
                        detail = str(exc)[:200]
                    steps_report.append({"action": action, "ok": ok, "detail": detail})

                critique = ""
                if bool(body.get("with_vlm", True)) and st["layout"] and os.path.exists(st["layout"]):
                    try:
                        import base64
                        from vision_critique import build_critique_prompt
                        with open(st["layout"], "rb") as fh:
                            b64 = base64.b64encode(fh.read()).decode("ascii")
                        prompt = build_critique_prompt(f"etude {theme}", st["layout_meta"] or {})
                        resp = llm_gateway.chat(
                            body.get("model") or "nvidia_nim/meta/llama-3.2-90b-vision-instruct",
                            llm_gateway.build_vision_messages(prompt, b64),
                            api_keys=api_keys, max_tokens=300)
                        m = (resp.get("choices") or [{}])[0].get("message", {})
                        critique = m.get("content") or m.get("reasoning_content") or ""
                    except Exception as exc:  # noqa: BLE001
                        critique = f"(VLM indisponible: {exc})"

                done = sum(1 for s in steps_report if s["ok"])
                self._send_json(handler, 200, {
                    "ok": True, "theme": theme, "steps": steps_report,
                    "completed": done, "total": len(steps_report),
                    "layout": st["layout"], "report_markdown": st["report"],
                    "critique": critique,
                })
                return True

            # ── Outils natifs en-process (sans bridge QGIS) ───────────────
            # IMPLÉMENTÉ PAR DEVIN CLI (Cognition AI)
            # Superviseur : Claude Code 4.8 — Camil | 2026-06-08
            if route.startswith("/api/native/"):
                tool_name = route.split("/api/native/")[-1]
                try:
                    from native_tools import NATIVE_TOOLS, _default_get_json
                except ImportError:
                    from .native_tools import NATIVE_TOOLS, _default_get_json
                native_map = {t.name: t for t in NATIVE_TOOLS}
                tool = native_map.get(tool_name)
                if tool is None:
                    self._send_json(handler, 404, {
                        "ok": False,
                        "error": f"Outil natif inconnu: {tool_name}",
                        "available": list(native_map.keys()),
                    })
                    return True
                try:
                    native_result = tool.executor(body, _default_get_json)
                    self._send_json(handler, 200, {"ok": True, "result": native_result})
                except Exception as native_exc:  # noqa: BLE001
                    self._send_json(handler, 500, {
                        "ok": False,
                        "error": str(native_exc),
                        "tool": tool_name,
                    })
                return True

            return False
        except Exception as exc:
            self._send_json(handler, 500, {
                "ok": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            })
            return True

    def _sse_start(self, handler) -> None:
        """Envoie les headers SSE communs (text/event-stream, no-cache, CORS)."""
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        _send_cors_headers(handler)
        handler.send_header("X-Accel-Buffering", "no")
        handler.end_headers()

    def _sse_emit(self, handler, payload: dict) -> None:
        """Sérialise et envoie un événement SSE, flush immédiat."""
        line = json.dumps(payload, ensure_ascii=False)
        handler.wfile.write(f"data: {line}\n\n".encode("utf-8"))
        handler.wfile.flush()

    def _stream_agent_response(
        self, handler, messages, api_keys, *,
        model, max_iters, auto_mode, system, bridge_url,
    ):
        """Stream SSE de la boucle agentique (iteration/tool_start/tool_result/final)."""
        try:
            from agent_tools import run_tool_loop
        except ImportError:
            from .agent_tools import run_tool_loop

        self._sse_start(handler)
        try:
            def on_event(ev: dict) -> None:
                self._sse_emit(handler, ev)

            result = run_tool_loop(
                messages, api_keys,
                model=model, max_iters=max_iters, auto_mode=auto_mode,
                system=system, bridge_url=bridge_url,
                on_event=on_event,
            )
            self._sse_emit(handler, {
                "type": "final",
                "content": result.get("content", ""),
                "iterations": result.get("iterations", 0),
                "trace_len": len(result.get("trace", [])),
            })
        except Exception as exc:  # noqa: BLE001
            try:
                self._sse_emit(handler, {"type": "error", "error": str(exc)})
            except Exception:  # noqa: BLE001
                pass
        finally:
            try:
                handler.wfile.write(b"data: [DONE]\n\n")
                handler.wfile.flush()
            except Exception:  # noqa: BLE001
                pass

    def _stream_smart_response(
        self, handler, query: str, api_keys: dict, *, context: dict, auto_route: bool,
    ):
        """Stream SSE de la federation multi-agents (progress/final)."""
        try:
            from agent_federation import AgentFederation
        except ImportError:
            from .agent_federation import AgentFederation

        self._sse_start(handler)
        try:
            def progress_cb(message: str) -> None:
                self._sse_emit(handler, {"type": "progress", "message": message})

            result = AgentFederation(api_keys).process(
                query,
                auto_route=auto_route,
                context=context,
                progress_callback=progress_cb,
            )
            serialized = {
                k: v for k, v in result.items() if k != "agent_results"
            }
            serialized["agent_results"] = [
                {
                    "agent_type": r.agent_type.value,
                    "success": r.success,
                    "content": r.content,
                    "latency_ms": r.latency_ms,
                    "model_used": r.model_used,
                    "error": r.error,
                }
                for r in result.get("agent_results", [])
            ]
            self._sse_emit(handler, {"type": "final", "result": serialized})
        except Exception as exc:  # noqa: BLE001
            try:
                self._sse_emit(handler, {"type": "error", "error": str(exc)})
            except Exception:  # noqa: BLE001
                pass
        finally:
            try:
                handler.wfile.write(b"data: [DONE]\n\n")
                handler.wfile.flush()
            except Exception:  # noqa: BLE001
                pass

    def _stream_llm_response(self, handler, model, messages, api_keys,
                              temperature, max_tokens, tools):
        """Stream SSE compatible text/event-stream."""
        from . import llm_gateway
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        _send_cors_headers(handler)
        handler.send_header("X-Accel-Buffering", "no")
        handler.end_headers()

        try:
            generator = llm_gateway.chat(
                model=model,
                messages=messages,
                api_keys=api_keys,
                stream=True,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
            )
            for chunk in generator:
                payload = json.dumps(chunk, ensure_ascii=False)
                handler.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                handler.wfile.flush()
            handler.wfile.write(b"data: [DONE]\n\n")
            handler.wfile.flush()
        except Exception as exc:
            err = json.dumps({"error": str(exc)}, ensure_ascii=False)
            try:
                handler.wfile.write(f"data: {err}\n\n".encode("utf-8"))
                handler.wfile.write(b"data: [DONE]\n\n")
                handler.wfile.flush()
            except Exception:
                pass

    def start(self):
        if self.httpd is not None:
            return self.port

        server_instance = self

        class AssetRequestHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=server_instance.directory, **kwargs)

            def do_OPTIONS(self):
                self.send_response(200)
                _send_cors_headers(self)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path.startswith("/api/"):
                    if not server_instance._enforce_rate_limit(self):
                        return
                if parsed.path.startswith("/api/qgis/"):
                    if server_instance._handle_api_request(self, "GET"):
                        return
                if parsed.path.startswith("/api/llm/"):
                    if server_instance._handle_llm_request(self, "GET"):
                        return

                self.path = parsed.path
                super().do_GET()

            def do_POST(self):
                parsed = urlparse(self.path)
                if parsed.path.startswith("/api/"):
                    if not server_instance._enforce_rate_limit(self):
                        return
                if parsed.path.startswith("/api/llm/"):
                    if server_instance._handle_llm_request(self, "POST"):
                        return
                if server_instance._handle_api_request(self, "POST"):
                    return

                self.send_error(404)

            def log_message(self, format, *args):
                return

        class QuietThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True
            allow_reuse_address = True
            timeout = None  # Set per-request

        # Port DÉTERMINISTE : l'origine (127.0.0.1:PORT) doit rester stable entre
        # deux lancements, sinon le localStorage du navigateur (clés API chiffrées,
        # réglages) est cloisonné par port et reparti de zéro à chaque session.
        # On essaie une liste fixe (surchageable via QGISIA_PORT), repli aléatoire.
        candidate_ports = []
        env_port = os.environ.get("QGISIA_PORT")
        if env_port and env_port.isdigit():
            candidate_ports.append(int(env_port))
        candidate_ports += [8157, 8158, 8159, 8160, 8161]
        candidate_ports.append(0)  # dernier recours : port libre aléatoire

        self.httpd = None
        for candidate in candidate_ports:
            try:
                self.httpd = QuietThreadingServer(("127.0.0.1", candidate), AssetRequestHandler)
                break
            except OSError:
                continue  # port occupé → essayer le suivant

        self.httpd.timeout = self.request_timeout
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self.port

    def stop(self):
        if self.httpd is None:
            return

        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd = None
        self.thread = None
        self.port = None


class GeoAIAssistant:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.asset_server = None
        self.bridge = None
        self.channel = None
        self.dock = None
        self.view = None
        self.external_ui_url = None
        self.main_thread_executor = MainThreadExecutor()
        self.plugin_dir = os.path.dirname(__file__)
        self.debug_log = os.environ.get("GEOAI_PLUGIN_DEBUG_LOG")

    def _debug(self, message):
        if not self.debug_log:
            return

        with open(self.debug_log, "a", encoding="utf-8") as handle:
            handle.write(f"{message}\n")

    def _web_entrypoint(self):
        return os.path.join(self.plugin_dir, "web", "index.html")

    def _web_directory(self):
        return os.path.join(self.plugin_dir, "web")

    def _ensure_bridge(self):
        if self.bridge is None:
            self.bridge = QgisBridge(self.iface)

    def _ensure_asset_server(self):
        web_dir = self._web_directory()
        if not os.path.exists(self._web_entrypoint()):
            return None

        if self.asset_server is None:
            self._ensure_bridge()
            request_timeout = float(os.environ.get("QGIS_BRIDGE_TIMEOUT", "120"))
            self.asset_server = ThreadedAssetServer(
                web_dir,
                self.bridge,
                self.main_thread_executor,
                request_timeout=request_timeout,
            )

        return self.asset_server.start()

    def _web_url(self, bridge_mode=None):
        port = self._ensure_asset_server()
        if port is None:
            return None

        page_name = os.environ.get("GEOAI_TEST_PAGE", "index.html")
        bridge_query = f"?bridge={bridge_mode}" if bridge_mode else ""
        return f"http://127.0.0.1:{port}/{page_name}{bridge_query}"

    def _open_external_ui(self):
        self.external_ui_url = self._web_url("http")
        if not self.external_ui_url:
            return False

        self._debug(f"external_ui:url={self.external_ui_url}")
        if os.environ.get("GEOAI_DISABLE_BROWSER_LAUNCH") != "1":
            QDesktopServices.openUrl(QUrl(self.external_ui_url))

        self.iface.messageBar().pushMessage(
            "QGISAI+",
            "Interface ouverte dans votre navigateur.",
            level=Qgis.Info,
            duration=5,
        )
        return True

    def _copy_to_clipboard(self, value):
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(value)
            self.iface.messageBar().pushMessage(
                "QGISAI+",
                "URL QGISAI+ copiée dans le presse-papier.",
                level=Qgis.Success,
                duration=4,
            )

    def _create_external_fallback_widget(self, url, error):
        container = QWidget()
        container.setObjectName("geoaiFallbackContainer")
        container.setStyleSheet(
            """
            QWidget#geoaiFallbackContainer {
                background: #08111f;
            }
            QFrame#geoaiFallbackCard {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #0d1b2a,
                    stop: 0.55 #10253b,
                    stop: 1 #15334b
                );
                border: 1px solid rgba(140, 183, 255, 0.18);
                border-radius: 18px;
            }
            QLabel#geoaiHeroTitle {
                color: #f8fbff;
                font-size: 19px;
                font-weight: 700;
            }
            QLabel#geoaiHeroBody {
                color: rgba(235, 244, 255, 0.88);
                font-size: 12px;
                line-height: 1.45em;
            }
            QLabel#geoaiBadge {
                background: rgba(96, 165, 250, 0.16);
                color: #bfdbfe;
                border: 1px solid rgba(147, 197, 253, 0.18);
                border-radius: 999px;
                padding: 5px 10px;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 0.12em;
                text-transform: uppercase;
            }
            QLabel#geoaiSectionTitle {
                color: #dbeafe;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.12em;
                text-transform: uppercase;
            }
            QTextBrowser#geoaiUrlBox, QTextBrowser#geoaiDetailBox {
                background: rgba(5, 10, 18, 0.55);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
                color: #f8fbff;
                padding: 10px;
                selection-background-color: #2563eb;
            }
            QPushButton#geoaiPrimaryButton {
                background: #0f6dff;
                color: white;
                border: none;
                border-radius: 12px;
                padding: 10px 14px;
                font-weight: 700;
            }
            QPushButton#geoaiPrimaryButton:hover {
                background: #1f7cff;
            }
            QPushButton#geoaiSecondaryButton {
                background: rgba(255, 255, 255, 0.06);
                color: #e5efff;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
                padding: 10px 14px;
                font-weight: 600;
            }
            QPushButton#geoaiSecondaryButton:hover {
                background: rgba(255, 255, 255, 0.1);
            }
            """
        )

        root_layout = QVBoxLayout(container)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(16)

        card = QFrame()
        card.setObjectName("geoaiFallbackCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(14)

        hero_layout = QHBoxLayout()
        hero_layout.setSpacing(14)

        icon_label = QLabel()
        icon_label.setFixedSize(164, 58)
        icon_label.setPixmap(QIcon(os.path.join(self.plugin_dir, "icon.svg")).pixmap(164, 58))
        hero_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        hero_text_layout = QVBoxLayout()
        hero_text_layout.setSpacing(6)

        badge = QLabel("Mode navigateur")
        badge.setObjectName("geoaiBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_text_layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)

        title = QLabel("QGISAI+ fonctionne, mais via le navigateur externe")
        title.setWordWrap(True)
        title.setObjectName("geoaiHeroTitle")
        hero_text_layout.addWidget(title)

        body = QLabel(
            "Le moteur Web Qt embarqué de cette installation QGIS n'est pas disponible. "
            "L'interface QGISAI+ a donc été ouverte automatiquement dans votre navigateur, "
            "avec le bridge local QGIS déjà actif."
        )
        body.setWordWrap(True)
        body.setObjectName("geoaiHeroBody")
        hero_text_layout.addWidget(body)

        hero_layout.addLayout(hero_text_layout, 1)
        card_layout.addLayout(hero_layout)

        url_title = QLabel("URL active")
        url_title.setObjectName("geoaiSectionTitle")
        card_layout.addWidget(url_title)

        url_box = QTextBrowser()
        url_box.setObjectName("geoaiUrlBox")
        url_box.setOpenExternalLinks(True)
        url_box.setMaximumHeight(74)
        url_box.setHtml(
            f'<a href="{url}">{url}</a>' if url else "<span>URL indisponible</span>"
        )
        card_layout.addWidget(url_box)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(10)

        open_button = QPushButton("Ouvrir QGISAI+")
        open_button.setObjectName("geoaiPrimaryButton")
        open_button.setEnabled(bool(url))
        open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        actions_layout.addWidget(open_button)

        copy_button = QPushButton("Copier l'URL")
        copy_button.setObjectName("geoaiSecondaryButton")
        copy_button.setEnabled(bool(url))
        copy_button.clicked.connect(lambda: self._copy_to_clipboard(url))
        actions_layout.addWidget(copy_button)

        toggle_button = QPushButton("Voir le détail technique")
        toggle_button.setObjectName("geoaiSecondaryButton")
        actions_layout.addWidget(toggle_button)
        card_layout.addLayout(actions_layout)

        detail_box = QTextBrowser()
        detail_box.setObjectName("geoaiDetailBox")
        detail_box.setVisible(False)
        detail_box.setMinimumHeight(180)
        detail_box.setPlainText(str(error) if error else "Aucun détail supplémentaire.")
        card_layout.addWidget(detail_box)

        def toggle_details():
            is_visible = not detail_box.isVisible()
            detail_box.setVisible(is_visible)
            toggle_button.setText(
                "Masquer le détail technique" if is_visible else "Voir le détail technique"
            )

        toggle_button.clicked.connect(toggle_details)

        root_layout.addWidget(card)
        root_layout.addStretch(1)
        return container

    def _attach_web_channel(self, ok):
        self._debug(f"attach_web_channel:start:{ok}")
        if not ok or self.view is None or self.channel is None:
            return

        self.view.page().setWebChannel(self.channel)
        self._debug("attach_web_channel:webchannel_set")
        self.view.page().runJavaScript(
            """
            if (typeof QWebChannel !== 'undefined' && window.qt && window.qt.webChannelTransport) {
              new QWebChannel(window.qt.webChannelTransport, function(channel) {
                window.qgis = channel.objects.qgis;
              });
            }
            """
        )
        self._debug("attach_web_channel:init_js_sent")

    def _create_dock(self):
        self._debug("create_dock:start")
        self.dock = QDockWidget("QGISAI+", self.iface.mainWindow())
        self._debug("create_dock:dock_created")
        self.dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.dock.setMinimumWidth(420)
        self.dock.setWindowIcon(QIcon(os.path.join(self.plugin_dir, "icon.svg")))

        container = QWidget()
        self._debug("create_dock:container_created")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        if QWebEngineView is None or QWebChannel is None:
            self._open_external_ui()
            self._debug(f"create_dock:web_import_error={WEB_IMPORT_ERROR!r}")
            layout.addWidget(
                self._create_external_fallback_widget(
                    self.external_ui_url or "",
                    WEB_IMPORT_ERROR,
                )
            )
            self.dock.setWidget(container)
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            self._debug("create_dock:web_runtime_unavailable")
            return

        self.view = QWebEngineView()
        self._debug("create_dock:view_created")
        self.channel = QWebChannel()
        self._debug("create_dock:channel_created")
        self._ensure_bridge()
        self._debug("create_dock:bridge_created")
        self.channel.registerObject("qgis", self.bridge)
        self._debug("create_dock:object_registered")
        self.view.loadFinished.connect(self._attach_web_channel)
        self._debug("create_dock:load_signal_connected")

        entrypoint = self._web_entrypoint()
        self._debug(f"create_dock:entrypoint={entrypoint}")
        web_url = self._web_url()
        if web_url is not None:
            self._debug(f"create_dock:web_url={web_url}")
            self.view.setUrl(WebQUrl(web_url))
            self._debug("create_dock:url_set")
        else:
            self.view.setHtml(
                """
                <html>
                  <body style="font-family: sans-serif; padding: 24px; background: #131314; color: #e3e3e3;">
                    <h2>Build web introuvable</h2>
                    <p>Exécutez <code>npm install</code> puis <code>npm run build</code> pour générer le dossier <code>qgis_plugin/web</code>.</p>
                  </body>
                </html>
                """,
                WebQUrl.fromLocalFile(self.plugin_dir + os.sep),
            )
            self._debug("create_dock:html_fallback_set")

        layout.addWidget(self.view)
        self._debug("create_dock:view_added")
        self.dock.setWidget(container)
        self._debug("create_dock:widget_set")
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self._debug("create_dock:dock_added")

    def initGui(self):
        self._debug("initGui:start")
        icon_path = os.path.join(self.plugin_dir, "icon.svg")

        # Action principale avec configuration
        action_name = ICON_CONFIG.get("name", "QGISAI+")
        action_tooltip = ICON_CONFIG.get("tooltip", "Ouvrir l'assistant IA QGISAI+")
        action_status_tip = ICON_CONFIG.get("status_tip", "Assistant IA pour QGIS")
        action_whats_this = ICON_CONFIG.get("whats_this", "")
        action_shortcut = ICON_CONFIG.get("shortcut", "Ctrl+Shift+G")
        action_text = ICON_CONFIG.get("text", "QGISAI+")
        show_text = ICON_CONFIG.get("show_text", True)
        icon_size = ICON_CONFIG.get("icon_size", 24)

        self.action = QAction(QIcon(icon_path), action_name, self.iface.mainWindow())
        self.action.setObjectName("GeoAIAssistantAction")
        self.action.setToolTip(action_tooltip)
        self.action.setStatusTip(action_status_tip)
        if action_whats_this:
            self.action.setWhatsThis(action_whats_this)
        self.action.triggered.connect(self.run)

        # Raccourci clavier
        if action_shortcut:
            self.action.setShortcut(action_shortcut)
            shortcut_context = ICON_CONFIG.get("shortcut_context", "window")
            if shortcut_context == "window":
                self.action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            else:
                self.action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        
        # Ajouter à la barre d'outils
        self.iface.addToolBarIcon(self.action)
        
        # Ajouter au menu avec configuration
        menu_name = MENU_CONFIG.get("name", "&QGISAI+")
        use_submenu = MENU_CONFIG.get("submenu", True)
        show_icon = MENU_CONFIG.get("icon", True)
        
        self.menu = self.iface.pluginMenu()
        
        if use_submenu:
            self.geoai_menu = self.menu.addMenu(menu_name)
            self.geoai_menu.setObjectName("GeoAIMenu")
            if show_icon:
                self.geoai_menu.setIcon(QIcon(icon_path))
            
            # Action principale dans le sous-menu
            self.geoai_menu.addAction(self.action)
            
            # Ajouter les items du menu
            menu_items = MENU_CONFIG.get("items", [])
            for item in menu_items:
                if item.get("separator"):
                    self.geoai_menu.addSeparator()
                else:
                    item_name = item.get("name", "")
                    item_tooltip = item.get("tooltip", "")
                    item_icon = item.get("icon", "")
                    item_shortcut = item.get("shortcut", "")
                    
                    if item_name == "Ouvrir":
                        # L'action principale est déjà ajoutée
                        continue
                    elif item_name == "Paramètres...":
                        self.settings_action = QAction(item_name, self.iface.mainWindow())
                        if item_icon and item_icon != "icon.svg":
                            self.settings_action.setIcon(QIcon.fromTheme(item_icon))
                        self.settings_action.setToolTip(item_tooltip)
                        self.settings_action.triggered.connect(self._open_settings)
                        self.geoai_menu.addAction(self.settings_action)
                    elif item_name == "Aide & Documentation":
                        self.help_action = QAction(item_name, self.iface.mainWindow())
                        if item_icon:
                            self.help_action.setIcon(QIcon.fromTheme(item_icon))
                        self.help_action.setToolTip(item_tooltip)
                        self.help_action.triggered.connect(self._open_help)
                        self.geoai_menu.addAction(self.help_action)
                    elif item_name == "À propos":
                        self.about_action = QAction(item_name, self.iface.mainWindow())
                        if item_icon:
                            self.about_action.setIcon(QIcon.fromTheme(item_icon))
                        self.about_action.setToolTip(item_tooltip)
                        self.about_action.triggered.connect(self._open_about)
                        self.geoai_menu.addAction(self.about_action)
        else:
            # Ajouter directement au menu sans sous-menu
            self.iface.addPluginToMenu(menu_name, self.action)
        
        # Ajouter au menu Processing si configuré
        processing_config = getattr(self, 'PROCESSING_MENU_CONFIG', {})
        if processing_config.get("add", False):
            try:
                processing_menu = self.iface.processingMenu()
                if processing_menu:
                    if processing_config.get("separator_before", False):
                        processing_menu.addSeparator()
                    processing_menu.addAction(self.action)
            except Exception:
                pass

        # Auto-show dock au démarrage QGIS (configurable)
        show_dock_on_startup = os.environ.get("QGIS_PLUGIN_SHOW_DOCK_ON_STARTUP", "1") == "1"
        if show_dock_on_startup:
            try:
                if self.dock is None:
                    self._create_dock()
                # Délai pour que QGIS se stabilise avant d'afficher le dock
                from qgis.PyQt.QtCore import QTimer
                QTimer.singleShot(500, lambda: self.dock.show() if self.dock else None)
                self._debug("initGui:dock_scheduled_for_display")
            except Exception as e:
                self._debug(f"initGui:dock_show_error {e}")

        self._debug("initGui:end")

    def run(self):
        """Lance l'interface QGISAI+ dans le navigateur externe"""
        self._debug("run:start")

        try:
            # Priorité 1: servir les assets buildés depuis le plugin (bridge QGIS intégré)
            if self._open_external_ui():
                self._debug("run:external_ui_opened")
                return

            # Priorité 2: fallback sur Vite dev server si les assets ne sont pas buildés
            self._debug("run:fallback_vite")
            import webbrowser
            import subprocess
            import time
            server_url = "http://localhost:5173"
            project_path = r"c:\Users\camil\Desktop\Micro Entreprise\04_PROJETS_EN_COURS\Projet\GeoSylva_AI_QGIS_OpenRouter"

            # Vérifier si le serveur Vite est déjà en cours
            server_running = False
            try:
                import urllib.request
                urllib.request.urlopen(server_url, timeout=2)
                server_running = True
            except:
                pass

            if not server_running:
                self.iface.messageBar().pushMessage(
                    "QGISAI+",
                    "Démarrage du serveur de développement...",
                    Qgis.MessageLevel.Info,
                    3
                )
                try:
                    subprocess.Popen(
                        "npm run dev",
                        cwd=project_path,
                        shell=True,
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                    from qgis.PyQt.QtWidgets import QApplication
                    for i in range(30):
                        time.sleep(1)
                        QApplication.processEvents()
                        try:
                            urllib.request.urlopen(server_url, timeout=2)
                            server_running = True
                            break
                        except:
                            pass
                except Exception as e:
                    self.iface.messageBar().pushMessage(
                        "QGISAI+",
                        f"Serveur non démarré: {str(e)} — lancez 'npm run dev' manuellement",
                        Qgis.MessageLevel.Warning,
                        8
                    )

            webbrowser.open(server_url)
            self.iface.messageBar().pushMessage(
                "QGISAI+",
                "Interface QGISAI+ ouverte dans votre navigateur.",
                Qgis.MessageLevel.Success,
                3
            )
            self._debug("run:browser_opened")

        except Exception as e:
            self._debug(f"run:error {e}")
            self.iface.messageBar().pushMessage(
                "QGISAI+",
                f"Erreur: {str(e)}",
                Qgis.MessageLevel.Critical,
                5
            )

        self._debug("run:end")
    
    def _open_settings(self):
        """Ouvre les paramètres du plugin"""
        self._debug("open_settings:start")

        # Ouvrir le dock et afficher un message
        if self.dock is None:
            self._create_dock()

        self.dock.show()
        self.dock.raise_()

        # Informer l'utilisateur que les paramètres sont dans l'interface web
        self.iface.messageBar().pushMessage(
            "QGISAI+",
            "Les paramètres sont accessibles depuis l'interface web (icône ⚙️ en bas à droite).",
            level=Qgis.Info,
            duration=5,
        )

        # Si le bridge est disponible, envoyer un signal pour ouvrir les paramètres
        if self.bridge and hasattr(self.bridge, 'open_settings'):
            try:
                self.bridge.open_settings()
                self._debug("open_settings:signal_sent")
            except Exception as e:
                self._debug(f"open_settings:signal_error={e}")

        self._debug("open_settings:end")
    
    def _open_help(self):
        """Ouvre la documentation"""
        self._debug("open_help:start")
        # Chercher le fichier README.md
        readme_path = os.path.join(self.plugin_dir, "README.md")
        if os.path.exists(readme_path):
            # Ouvrir avec le navigateur par défaut
            QDesktopServices.openUrl(QUrl.fromLocalFile(readme_path))
            self._debug("open_help:readme_opened")
        else:
            # Fallback: ouvrir la documentation en ligne
            QDesktopServices.openUrl(QUrl("https://github.com/NeooeN45/QGISIA2"))
            self.iface.messageBar().pushMessage(
                "QGISAI+",
                "Documentation en ligne ouverte dans votre navigateur.",
                level=Qgis.Info,
                duration=3,
            )
            self._debug("open_help:online_opened")
        self._debug("open_help:end")
    
    def _open_about(self):
        """Affiche la boîte de dialogue À propos"""
        self._debug("open_about:start")
        from qgis.PyQt.QtWidgets import QMessageBox
        
        about_text = """
        <h2>QGISAI+</h2>
        <p><b>Assistant IA pour QGIS</b></p>
        <p>QGISAI+ est un assistant intelligent qui vous aide à accomplir 
        des tâches SIG complexes en langage naturel.</p>
        
        <h3>Fonctionnalités:</h3>
        <ul>
            <li>Commandes en langage naturel</li>
            <li>Gestion de couches QGIS</li>
            <li>Exécution de scripts PyQGIS</li>
            <li>Intégration avec OpenRouter, Google Gemini, Ollama</li>
        </ul>
        
        <h3>Raccourci clavier:</h3>
        <p>Ctrl+Shift+G pour ouvrir le panneau</p>
        
        <p><i>Version 2.0.0</i></p>
        """
        
        QMessageBox.about(
            self.iface.mainWindow(),
            "À propos de QGISAI+",
            about_text
        )
        self._debug("open_about:end")

    def unload(self):
        self._debug("unload:start")
        
        # Arrêter le serveur d'assets
        if self.asset_server is not None:
            self.asset_server.stop()
            self.geoai_menu.deleteLater()
        
        # Supprimer l'action principale
        if self.action is not None:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu("&QGISAI+", self.action)
            self.action.deleteLater()
            self.action = None
        
        # Nettoyer les autres actions
        if hasattr(self, 'settings_action'):
            self.settings_action.deleteLater()
        if hasattr(self, 'help_action'):
            self.help_action.deleteLater()
        if hasattr(self, 'about_action'):
            self.about_action.deleteLater()

        self._debug("unload:end")
