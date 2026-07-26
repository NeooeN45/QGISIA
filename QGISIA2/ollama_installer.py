# -*- coding: utf-8 -*-
"""
Installation et gestion d'Ollama
"""
import os
import subprocess
import sys
import platform
import urllib.request
import tempfile
import shutil
from typing import Dict, Optional, List
from pathlib import Path

from .system_capabilities import system_capabilities
from .error_handler import plugin_logger, with_error_handling


class OllamaInstaller:
    """Gestionnaire d'installation d'Ollama"""
    
    def __init__(self):
        self.logger = plugin_logger
        self.system = system_capabilities
        self.ollama_path = self._find_ollama()
    
    def _find_ollama(self) -> Optional[str]:
        """Cherche si Ollama est déjà installé"""
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                self.logger.info(f"Ollama détecté: {result.stdout.strip()}")
                return "ollama"
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass
        
        return None
    
    def is_installed(self) -> bool:
        """Vérifie si Ollama est installé"""
        return self.ollama_path is not None
    
    def is_running(self) -> bool:
        """Vérifie si le service Ollama est en cours d'exécution"""
        try:
            # Essayer d'abord via l'API HTTP (plus rapide)
            import urllib.request
            import socket
            try:
                req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
                with urllib.request.urlopen(req, timeout=2) as response:
                    return response.status == 200
            except (urllib.error.URLError, socket.timeout):
                pass
            
            # Fallback via commande ollama
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def start_ollama(self) -> Dict:
        """
        Tente de démarrer le service Ollama
        
        Returns:
            Dict avec success (bool), message (str), error (str optionnel)
        """
        if not self.is_installed():
            return {
                "success": False,
                "message": "Ollama n'est pas installé",
                "error": "INSTALLATION_REQUIRED"
            }
        
        if self.is_running():
            return {
                "success": True,
                "message": "Ollama est déjà en cours d'exécution"
            }
        
        try:
            platform_name = platform.system()
            
            if platform_name == "Windows":
                # Sur Windows, tenter de lancer Ollama via le menu démarrer ou le chemin par défaut
                ollama_exe_paths = [
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
                    os.path.expandvars(r"%ProgramFiles%\Ollama\ollama.exe"),
                    os.path.expandvars(r"%ProgramFiles(x86)%\Ollama\ollama.exe"),
                    os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "Ollama", "ollama.exe"),
                ]
                
                ollama_path = None
                for path in ollama_exe_paths:
                    if os.path.exists(path):
                        ollama_path = path
                        break
                
                if ollama_path:
                    # Lancer Ollama en arrière-plan (serveur)
                    subprocess.Popen(
                        [ollama_path, "serve"],
                        creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, 'CREATE_NEW_CONSOLE') else 0,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )
                else:
                    # Tenter de lancer via la commande générique
                    subprocess.Popen(
                        ["ollama", "serve"],
                        creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, 'CREATE_NEW_CONSOLE') else 0,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )
            else:
                # macOS et Linux
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            
            # Attendre que le service démarre (max 10 secondes)
            import time
            for i in range(20):
                time.sleep(0.5)
                if self.is_running():
                    self.logger.info("Ollama démarré avec succès")
                    return {
                        "success": True,
                        "message": "Ollama a été démarré avec succès"
                    }
            
            # Si on arrive ici, le service n'a pas démarré dans le temps imparti
            return {
                "success": False,
                "message": "Le démarrage d'Ollama a pris trop de temps",
                "error": "STARTUP_TIMEOUT"
            }
            
        except Exception as e:
            self.logger.error(f"Erreur lors du démarrage d'Ollama: {e}")
            return {
                "success": False,
                "message": f"Erreur lors du démarrage: {str(e)}",
                "error": "STARTUP_ERROR"
            }
    
    def ensure_running(self, auto_start: bool = True) -> Dict:
        """
        Vérifie qu'Ollama est en cours d'exécution et tente de le démarrer si nécessaire
        
        Args:
            auto_start: Si True, tente de démarrer Ollama automatiquement
        
        Returns:
            Dict avec status (running, started, error), message, et error_code
        """
        # Vérifier si déjà en cours d'exécution
        if self.is_running():
            return {
                "status": "running",
                "installed": True,
                "message": "Ollama est en cours d'exécution",
                "can_proceed": True
            }
        
        # Vérifier si installé
        if not self.is_installed():
            instructions = self.get_installation_instructions()
            return {
                "status": "not_installed",
                "installed": False,
                "message": "Ollama n'est pas installé sur ce système",
                "can_proceed": False,
                "installation": instructions,
                "error_code": "INSTALLATION_REQUIRED"
            }
        
        # Tenter de démarrer si auto_start est activé
        if auto_start:
            self.logger.info("Tentative de démarrage automatique d'Ollama...")
            start_result = self.start_ollama()
            
            if start_result["success"]:
                return {
                    "status": "started",
                    "installed": True,
                    "message": start_result["message"],
                    "can_proceed": True
                }
            else:
                return {
                    "status": "start_failed",
                    "installed": True,
                    "message": start_result["message"],
                    "can_proceed": False,
                    "error_code": start_result.get("error", "STARTUP_ERROR")
                }
        
        # Installé mais pas en cours d'exécution et auto_start désactivé
        return {
            "status": "not_running",
            "installed": True,
            "message": "Ollama est installé mais n'est pas en cours d'exécution",
            "can_proceed": False,
            "error_code": "NOT_RUNNING"
        }
    
    def get_installation_instructions(self) -> Dict:
        """Retourne les instructions d'installation pour la plateforme actuelle"""
        platform_name = platform.system()
        
        instructions = {
            "platform": platform_name,
            "download_url": "",
            "install_command": "",
            "manual_steps": [],
        }
        
        if platform_name == "Windows":
            instructions["download_url"] = "https://ollama.com/download/windows"
            instructions["install_command"] = "winget install Ollama.Ollama"
            instructions["manual_steps"] = [
                "1. Téléchargez Ollama depuis https://ollama.com/download/windows",
                "2. Exécutez le fichier d'installation",
                "3. Suivez les instructions de l'installateur",
                "4. Redémarrez QGIS après l'installation",
            ]
        elif platform_name == "Darwin":  # macOS
            instructions["download_url"] = "https://ollama.com/download/mac"
            instructions["install_command"] = "brew install ollama"
            instructions["manual_steps"] = [
                "1. Installez Homebrew si ce n'est pas déjà fait",
                "2. Exécutez: brew install ollama",
                "3. Ou téléchargez depuis https://ollama.com/download/mac",
                "4. Redémarrez QGIS après l'installation",
            ]
        elif platform_name == "Linux":
            instructions["download_url"] = "https://ollama.com/download/linux"
            instructions["install_command"] = "curl -fsSL https://ollama.com/install.sh | sh"
            instructions["manual_steps"] = [
                "1. Exécutez: curl -fsSL https://ollama.com/install.sh | sh",
                "2. Ou téléchargez depuis https://ollama.com/download/linux",
                "3. Redémarrez QGIS après l'installation",
            ]
        
        return instructions
    
    def get_installed_models(self) -> List[Dict]:
        """Retourne la liste des modèles Ollama installés"""
        if not self.is_installed():
            return []
        
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                return []
            
            models = []
            lines = result.stdout.strip().split("\n")
            for line in lines[1:]:  # Skip header
                if line.strip():
                    parts = line.split()
                    if parts:
                        models.append({
                            "name": parts[0],
                            "id": parts[0],
                            "size": parts[1] if len(parts) > 1 else "Unknown",
                            "modified": parts[2] if len(parts) > 2 else "Unknown",
                        })
            
            return models
        except Exception as e:
            self.logger.error(f"Erreur lors de la récupération des modèles: {e}")
            return []
    
    def install_model(self, model_name: str, progress_callback=None) -> bool:
        """
        Installe un modèle Ollama
        
        Args:
            model_name: Nom du modèle à installer (ex: "qwen2.5:7b")
            progress_callback: Fonction de rappel pour la progression (optionnel)
            
        Returns:
            True si l'installation a réussi
        """
        if not self.is_installed():
            self.logger.error("Ollama n'est pas installé")
            return False
        
        try:
            self.logger.info(f"Installation du modèle {model_name}...")
            
            # Lancer l'installation
            process = subprocess.Popen(
                ["ollama", "pull", model_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Lire la sortie en temps réel
            for line in process.stdout:
                line = line.strip()
                if line and progress_callback:
                    progress_callback(line)
            
            process.wait()
            
            if process.returncode == 0:
                self.logger.info(f"Modèle {model_name} installé avec succès")
                return True
            else:
                error = process.stderr.read()
                self.logger.error(f"Erreur lors de l'installation: {error}")
                return False
                
        except Exception as e:
            self.logger.error(f"Erreur lors de l'installation du modèle: {e}")
            return False
    
    def remove_model(self, model_name: str) -> bool:
        """Supprime un modèle Ollama"""
        if not self.is_installed():
            return False
        
        try:
            result = subprocess.run(
                ["ollama", "rm", model_name],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                self.logger.info(f"Modèle {model_name} supprimé")
                return True
            else:
                self.logger.error(f"Erreur lors de la suppression: {result.stderr}")
                return False
        except Exception as e:
            self.logger.error(f"Erreur lors de la suppression du modèle: {e}")
            return False
    
    def get_recommendations(self) -> Dict:
        """Retourne les recommandations basées sur le système"""
        return self.system.get_ollama_recommendation()
    
    def get_available_models(self) -> List[Dict]:
        """Retourne les modèles disponibles pour le système"""
        return self.system.get_all_available_models()
    
    def auto_install_best_model(self) -> Optional[str]:
        """
        Installe automatiquement le meilleur modèle recommandé
        
        Returns:
            Nom du modèle installé ou None
        """
        recommendations = self.get_recommendations()
        
        if not recommendations["can_run_local"]:
            self.logger.warning("Le système ne peut pas exécuter de LLM locaux")
            return None
        
        for model in recommendations["recommended_models"]:
            if model.get("recommended", False):
                self.logger.info(f"Installation automatique du modèle recommandé: {model['name']}")
                if self.install_model(model["name"]):
                    return model["name"]
        
        return None


# Instance globale
ollama_installer = OllamaInstaller()
