# -*- coding: utf-8 -*-
"""
Gestion des erreurs améliorée pour le plugin GeoAI Assistant
"""
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Any

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtWidgets import QMessageBox, QWidget


class PluginLogger:
    """Logger personnalisé pour le plugin"""
    
    def __init__(self, plugin_name="GeoAI"):
        self.plugin_name = plugin_name
        self.logger = logging.getLogger(plugin_name)
        self.logger.setLevel(logging.DEBUG)
        
        # Handler pour fichier
        self._setup_file_handler()
        
        # Handler pour console
        self._setup_console_handler()
    
    def _setup_file_handler(self):
        """Configure le handler pour fichier"""
        log_dir = Path.home() / ".qgis3" / "geoai_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / f"{self.plugin_name.lower()}_{datetime.now().strftime('%Y%m%d')}.log"
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
    
    def _setup_console_handler(self):
        """Configure le handler pour console"""
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        
        formatter = logging.Formatter('%(levelname)s: %(message)s')
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(console_handler)
    
    def debug(self, message: str):
        """Log un message de debug"""
        self.logger.debug(message)
    
    def info(self, message: str):
        """Log un message d'info"""
        self.logger.info(message)
    
    def warning(self, message: str):
        """Log un avertissement"""
        self.logger.warning(message)
    
    def error(self, message: str, exc_info: bool = False):
        """Log une erreur"""
        self.logger.error(message, exc_info=exc_info)
    
    def critical(self, message: str, exc_info: bool = True):
        """Log une erreur critique"""
        self.logger.critical(message, exc_info=exc_info)


class ErrorHandler:
    """Gestionnaire d'erreurs avec messages utilisateur"""
    
    def __init__(self, logger: PluginLogger, iface=None):
        self.logger = logger
        self.iface = iface
        self.parent_widget = iface.mainWindow() if iface else None
    
    def handle_error(
        self,
        error: Exception,
        context: str = "",
        show_to_user: bool = True,
        log_level: str = "error"
    ):
        """
        Gère une erreur de manière centralisée
        
        Args:
            error: L'exception à gérer
            context: Contexte de l'erreur (ex: "Chargement de la couche")
            show_to_user: Si True, affiche un message à l'utilisateur
            log_level: Niveau de log ("debug", "info", "warning", "error", "critical")
        """
        # Log l'erreur
        log_message = f"{context}: {str(error)}" if context else str(error)
        log_method = getattr(self.logger, log_level, self.logger.error)
        log_method(log_message, exc_info=True)
        
        # Afficher dans QGIS Message Log
        QgsMessageLog.logMessage(
            f"{context}: {str(error)}" if context else str(error),
            "GeoAI",
            Qgis.Critical
        )
        
        # Afficher à l'utilisateur
        if show_to_user and self.parent_widget:
            self._show_error_to_user(error, context)
    
    def _show_error_to_user(self, error: Exception, context: str = ""):
        """Affiche l'erreur à l'utilisateur"""
        title = "Erreur GeoAI"
        if context:
            title = f"Erreur - {context}"
        
        message = str(error)
        
        # Essayer d'extraire un message plus utile
        if hasattr(error, '__cause__') and error.__cause__:
            message = f"{message}\n\nCause: {str(error.__cause__)}"
        
        QMessageBox.critical(
            self.parent_widget,
            title,
            message,
            QMessageBox.Ok
        )
    
    def handle_warning(
        self,
        message: str,
        context: str = "",
        show_to_user: bool = False
    ):
        """Gère un avertissement"""
        log_message = f"{context}: {message}" if context else message
        self.logger.warning(log_message)
        
        if show_to_user and self.parent_widget:
            title = "Avertissement GeoAI"
            if context:
                title = f"Avertissement - {context}"
            
            QMessageBox.warning(
                self.parent_widget,
                title,
                message,
                QMessageBox.Ok
            )
    
    def show_info(
        self,
        message: str,
        context: str = "",
        show_to_user: bool = True
    ):
        """Affiche un message d'information"""
        log_message = f"{context}: {message}" if context else message
        self.logger.info(log_message)
        
        if show_to_user and self.parent_widget:
            title = "GeoAI"
            if context:
                title = context
            
            QMessageBox.information(
                self.parent_widget,
                title,
                message,
                QMessageBox.Ok
            )
    
    def show_success(
        self,
        message: str,
        context: str = "",
        show_to_user: bool = True
    ):
        """Affiche un message de succès"""
        log_message = f"{context}: {message}" if context else message
        self.logger.info(log_message)
        
        if show_to_user and self.parent_widget:
            title = "Succès"
            if context:
                title = context
            
            QMessageBox.information(
                self.parent_widget,
                title,
                message,
                QMessageBox.Ok
            )


def with_error_handling(
    logger: PluginLogger,
    error_handler: ErrorHandler,
    context: str = "",
    show_to_user: bool = True
):
    """
    Décorateur pour gérer les erreurs de fonctions
    
    Args:
        logger: Logger du plugin
        error_handler: Gestionnaire d'erreurs
        context: Contexte de l'opération
        show_to_user: Si True, affiche les erreurs à l'utilisateur
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_handler.handle_error(e, context, show_to_user)
                return None
        return wrapper
    return decorator


# Instance globale du logger
plugin_logger = PluginLogger()
