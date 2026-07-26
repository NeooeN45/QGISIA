# -*- coding: utf-8 -*-
"""
Outils QGIS natifs améliorés et intégration approfondie
"""
from typing import List, Dict, Any, Optional
from pathlib import Path

from qgis.core import (
    QgsProject,
    QgsMapLayer,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsCoordinateReferenceSystem,
    QgsWkbTypes,
    QgsProcessingContext,
    QgsProcessingFeedback,
)
from qgis.PyQt.QtCore import QVariant
import processing

from .error_handler import plugin_logger, with_error_handling


class LayerManager:
    """Gestionnaire de couches avec fonctionnalités avancées"""
    
    def __init__(self, project: QgsProject = None):
        self.project = project or QgsProject.instance()
        self.logger = plugin_logger
    
    @with_error_handling(plugin_logger, None, "Liste des couches")
    def list_layers(
        self,
        layer_type: Optional[str] = None,
        geometry_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Liste toutes les couches du projet avec filtres optionnels
        
        Args:
            layer_type: "vector", "raster", ou None pour tous
            geometry_type: "Point", "Line", "Polygon", etc. ou None pour tous
            
        Returns:
            Liste de dictionnaires avec informations sur les couches
        """
        layers_info = []
        
        for layer in self.project.mapLayers().values():
            if layer_type and layer.type().name.lower() != layer_type.lower():
                continue
            
            layer_info = {
                "id": layer.id(),
                "name": layer.name(),
                "type": layer.type().name,
                "source": layer.source(),
                "crs": layer.crs().authid() if layer.crs() else None,
                "is_valid": layer.isValid(),
            }
            
            # Informations spécifiques aux vecteurs
            if isinstance(layer, QgsVectorLayer):
                layer_info["geometry_type"] = layer.wkbType()
                layer_info["feature_count"] = layer.featureCount()
                layer_info["fields"] = [field.name() for field in layer.fields()]
                
                if geometry_type:
                    geom_type_name = QgsWkbTypes.displayString(layer.wkbType())
                    if geometry_type.lower() not in geom_type_name.lower():
                        continue
            
            # Informations spécifiques aux rasters
            elif isinstance(layer, QgsRasterLayer):
                layer_info["bands"] = layer.bandCount()
                layer_info["width"] = layer.width()
                layer_info["height"] = layer.height()
            
            layers_info.append(layer_info)
        
        self.logger.info(f"Liste des couches: {len(layers_info)} couches trouvées")
        return layers_info
    
    @with_error_handling(plugin_logger, None, "Diagnostic de couche")
    def diagnose_layer(self, layer_id: str) -> Dict[str, Any]:
        """
        Diagnostic détaillé d'une couche
        
        Args:
            layer_id: ID de la couche à diagnostiquer
            
        Returns:
            Dictionnaire avec diagnostic complet
        """
        layer = self.project.mapLayer(layer_id)
        if not layer:
            raise ValueError(f"Couche {layer_id} non trouvée")
        
        diagnosis = {
            "id": layer.id(),
            "name": layer.name(),
            "type": layer.type().name,
            "is_valid": layer.isValid(),
            "error": None,
        }
        
        if not layer.isValid():
            diagnosis["error"] = layer.error().message() if layer.error() else "Erreur inconnue"
            return diagnosis
        
        # Diagnostic pour vecteurs
        if isinstance(layer, QgsVectorLayer):
            diagnosis.update({
                "feature_count": layer.featureCount(),
                "fields": [
                    {
                        "name": field.name(),
                        "type": field.typeName(),
                        "length": field.length(),
                    }
                    for field in layer.fields()
                ],
                "geometry_type": QgsWkbTypes.displayString(layer.wkbType()),
                "crs": layer.crs().authid() if layer.crs() else None,
                "editable": layer.isEditable(),
                "memory": layer.storageType() == "memory",
            })
            
            # Vérifier les géométries invalides
            invalid_geoms = 0
            for feature in layer.getFeatures():
                if not feature.geometry() or not feature.geometry().isGeosValid():
                    invalid_geoms += 1
            
            diagnosis["invalid_geometries"] = invalid_geoms
        
        # Diagnostic pour rasters
        elif isinstance(layer, QgsRasterLayer):
            diagnosis.update({
                "bands": layer.bandCount(),
                "width": layer.width(),
                "height": layer.height(),
                "extent": layer.extent().toString(),
                "crs": layer.crs().authid() if layer.crs() else None,
                "no_data_value": layer.dataProvider().sourceNoDataValue(1),
            })
        
        return diagnosis
    
    @with_error_handling(plugin_logger, None, "Calcul de statistiques")
    def calculate_statistics(
        self,
        layer_id: str,
        field_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calcule les statistiques d'une couche ou d'un champ
        
        Args:
            layer_id: ID de la couche
            field_name: Nom du champ (optionnel)
            
        Returns:
            Dictionnaire avec statistiques
        """
        layer = self.project.mapLayer(layer_id)
        if not layer:
            raise ValueError(f"Couche {layer_id} non trouvée")
        
        if not isinstance(layer, QgsVectorLayer):
            raise TypeError("Cette fonction ne supporte que les couches vectorielles")
        
        stats = {
            "layer_id": layer_id,
            "layer_name": layer.name(),
            "feature_count": layer.featureCount(),
        }
        
        if field_name:
            # Statistiques du champ
            field_idx = layer.fields().lookupField(field_name)
            if field_idx == -1:
                raise ValueError(f"Champ {field_name} non trouvé")
            
            field = layer.fields().field(field_idx)
            values = []
            
            for feature in layer.getFeatures():
                value = feature[field_name]
                if value is not None and value != NULL:
                    values.append(value)
            
            if values:
                if field.isNumeric():
                    stats["field_statistics"] = {
                        "count": len(values),
                        "min": min(values),
                        "max": max(values),
                        "mean": sum(values) / len(values),
                        "sum": sum(values),
                    }
                else:
                    stats["field_statistics"] = {
                        "count": len(values),
                        "unique": len(set(str(v) for v in values)),
                    }
        else:
            # Statistiques géométriques
            total_area = 0
            total_length = 0
            geom_types = {}
            
            for feature in layer.getFeatures():
                geom = feature.geometry()
                if geom:
                    if geom.type() in (QgsWkbTypes.PolygonGeometry, QgsWkbTypes.MultiPolygonGeometry):
                        total_area += geom.area()
                    elif geom.type() in (QgsWkbTypes.LineGeometry, QgsWkbTypes.MultiLineGeometry):
                        total_length += geom.length()
                    
                    geom_type = QgsWkbTypes.displayString(geom.wkbType())
                    geom_types[geom_type] = geom_types.get(geom_type, 0) + 1
            
            stats["geometric_statistics"] = {
                "total_area": total_area,
                "total_length": total_length,
                "geometry_types": geom_types,
            }
        
        return stats


class ProcessingTools:
    """Outils de traitement QGIS Processing"""
    
    def __init__(self):
        self.logger = plugin_logger
        self.context = QgsProcessingContext()
        self.feedback = QgsProcessingFeedback()
    
    @with_error_handling(plugin_logger, None, "Exécution d'algorithme")
    def run_algorithm(
        self,
        algorithm_name: str,
        parameters: Dict[str, Any],
        project: Optional[QgsProject] = None
    ) -> Dict[str, Any]:
        """
        Exécute un algorithme de processing QGIS
        
        Args:
            algorithm_name: Nom de l'algorithme (ex: "native:buffer")
            parameters: Paramètres de l'algorithme
            project: Projet QGIS (optionnel)
            
        Returns:
            Résultat de l'algorithme
        """
        self.context.setProject(project or QgsProject.instance())
        
        try:
            result = processing.run(
                algorithm_name,
                parameters,
                context=self.context,
                feedback=self.feedback
            )
            
            self.logger.info(f"Algorithme {algorithm_name} exécuté avec succès")
            return result
            
        except Exception as e:
            self.logger.error(f"Erreur lors de l'exécution de {algorithm_name}: {e}")
            raise
    
    def buffer_layer(
        self,
        layer_id: str,
        distance: float,
        segments: int = 5,
        dissolve: bool = False
    ) -> str:
        """
        Crée un buffer autour d'une couche
        
        Args:
            layer_id: ID de la couche source
            distance: Distance du buffer
            segments: Nombre de segments pour les courbes
            dissolve: Si True, fusionne les résultats
            
        Returns:
            ID de la couche créée
        """
        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        
        if not layer:
            raise ValueError(f"Couche {layer_id} non trouvée")
        
        parameters = {
            'INPUT': layer,
            'DISTANCE': distance,
            'SEGMENTS': segments,
            'DISSOLVE': dissolve,
            'OUTPUT': 'memory:'
        }
        
        result = self.run_algorithm('native:buffer', parameters, project)
        output_layer = result['OUTPUT']
        
        project.addMapLayer(output_layer)
        return output_layer.id()
    
    def dissolve_layer(
        self,
        layer_id: str,
        field_name: Optional[str] = None
    ) -> str:
        """
        Fusionne les entités d'une couche
        
        Args:
            layer_id: ID de la couche source
            field_name: Champ pour la fusion (optionnel)
            
        Returns:
            ID de la couche créée
        """
        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        
        if not layer:
            raise ValueError(f"Couche {layer_id} non trouvée")
        
        parameters = {
            'INPUT': layer,
            'FIELD': field_name if field_name else None,
            'OUTPUT': 'memory:'
        }
        
        result = self.run_algorithm('native:dissolve', parameters, project)
        output_layer = result['OUTPUT']
        
        project.addMapLayer(output_layer)
        return output_layer.id()


# Instances globales
layer_manager = LayerManager()
processing_tools = ProcessingTools()
