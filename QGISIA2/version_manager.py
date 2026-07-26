# -*- coding: utf-8 -*-
"""
Gestionnaire de versions multiples QGIS
Détecte et gère correctement les différentes installations de QGIS
"""
import os
import sys
from pathlib import Path
from typing import Optional, Tuple, List


class QgisVersionManager:
    """Gestionnaire pour détecter et gérer les versions multiples de QGIS"""
    
    def __init__(self):
        self.current_qgis_version = self._detect_qgis_version()
        self.current_qgis_path = self._detect_qgis_path()
        self.current_site_packages = self._detect_site_packages()
    
    def _detect_qgis_version(self) -> str:
        """Détecte la version de QGIS en cours d'exécution (compatible 3.x et 4.x)"""
        try:
            from qgis.core import Qgis
            ver = Qgis.versionInt() if callable(Qgis.versionInt) else int(Qgis.QGIS_VERSION_INT)
            return str(ver)
        except ImportError:
            return "unknown"
    
    def _detect_qgis_path(self) -> Optional[Path]:
        """Détecte le chemin d'installation de QGIS"""
        # Méthode 1: Via QGIS_PREFIX_PATH
        qgis_prefix = os.environ.get('QGIS_PREFIX_PATH')
        if qgis_prefix:
            return Path(qgis_prefix)
        
        # Méthode 2: Via le module qgis
        try:
            import qgis
            qgis_path = Path(qgis.__file__).resolve()
            # Remonter jusqu'au répertoire d'installation
            for _ in range(6):  # qgis/core/__init__.py → apps/qgis/python
                qgis_path = qgis_path.parent
                if qgis_path.name == "apps":
                    return qgis_path.parent
        except ImportError:
            pass
        
        return None
    
    def _detect_site_packages(self) -> Optional[Path]:
        """Détecte le site-packages de la version actuelle de QGIS (PyQt5 ou PyQt6)"""
        qgis_path = self.current_qgis_path
        if not qgis_path:
            return None

        # QGIS 4 utilise PyQt6, QGIS 3 PyQt5
        try:
            qgis_major = int(str(self.current_qgis_version)[:1])
        except (ValueError, TypeError):
            qgis_major = 3
        pyqt_pkg = "PyQt6" if qgis_major >= 4 else "PyQt5"

        # Chercher Python*/Lib/site-packages avec le bon PyQt
        for python_dir in sorted(qgis_path.glob("Python*"), reverse=True):
            site_packages = python_dir / "Lib" / "site-packages"
            if site_packages.exists() and (site_packages / pyqt_pkg).exists():
                return site_packages

        # Fallback : prendre le premier site-packages existant
        for python_dir in sorted(qgis_path.glob("Python*"), reverse=True):
            site_packages = python_dir / "Lib" / "site-packages"
            if site_packages.exists():
                return site_packages

        return None
    
    def get_qgis_info(self) -> dict:
        """Retourne les informations sur la version actuelle de QGIS"""
        return {
            "version": self.current_qgis_version,
            "path": str(self.current_qgis_path) if self.current_qgis_path else None,
            "site_packages": str(self.current_site_packages) if self.current_site_packages else None,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        }
    
    def find_all_qgis_installations(self) -> List[dict]:
        """
        Trouve toutes les installations de QGIS sur le système
        
        Returns:
            Liste des installations détectées
        """
        installations = []
        
        # Chemins communs d'installation QGIS
        common_paths = []
        
        if sys.platform == "win32":
            # Windows
            program_files = [
                Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")),
                Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")),
                Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))),
            ]
            
            for base in program_files:
                if base.exists():
                    common_paths.extend(base.glob("QGIS*"))
        
        elif sys.platform == "darwin":
            # macOS
            common_paths.extend(Path("/Applications").glob("QGIS*.app"))
        
        else:
            # Linux
            common_paths.extend(Path("/usr").glob("bin/qgis*"))
            common_paths.extend(Path("/opt").glob("qgis*"))
        
        # Analyser chaque installation trouvée
        for qgis_dir in common_paths:
            info = self._analyze_qgis_installation(qgis_dir)
            if info:
                installations.append(info)
        
        return installations
    
    def _analyze_qgis_installation(self, qgis_dir: Path) -> Optional[dict]:
        """Analyse une installation QGIS spécifique"""
        try:
            # Chercher le dossier Python
            python_dirs = list(qgis_dir.glob("Python*"))
            if not python_dirs:
                return None
            
            # Prendre la version la plus récente
            python_dir = max(python_dirs, key=lambda p: p.name)
            
            # Vérifier si site-packages existe
            site_packages = python_dir / "Lib" / "site-packages"
            if not site_packages.exists():
                return None
            
            # Chercher qgis.core pour vérifier que c'est une installation valide
            qgis_core = site_packages / "qgis" / "core"
            if not qgis_core.exists():
                return None
            
            return {
                "path": str(qgis_dir),
                "python_dir": str(python_dir),
                "site_packages": str(site_packages),
                "name": qgis_dir.name,
            }
            
        except Exception:
            return None
    
    def get_plugin_path(self) -> Path:
        """
        Retourne le chemin du dossier plugins pour la version actuelle
        
        Returns:
            Chemin du dossier plugins
        """
        # Méthode 1: Via QGIS_PLUGIN_PATH
        plugin_path = os.environ.get('QGIS_PLUGIN_PATH')
        if plugin_path:
            return Path(plugin_path)
        
        # Méthode 2: Via le profil utilisateur
        # Détecter si QGIS 3 ou 4 pour le nom du dossier profil
        try:
            qgis_major = int(str(self.current_qgis_version)[:1])
        except (ValueError, TypeError):
            qgis_major = 3
        qgis_folder = f"QGIS{qgis_major}"

        if sys.platform == "win32":
            profile_dir = Path(os.environ.get("APPDATA", "")) / "QGIS" / qgis_folder / "profiles"
        elif sys.platform == "darwin":
            profile_dir = Path.home() / "Library" / "Application Support" / "QGIS" / qgis_folder / "profiles"
        else:
            profile_dir = Path.home() / ".local" / "share" / "QGIS" / qgis_folder / "profiles"
        
        # Chercher le profil par défaut
        default_profile = profile_dir / "default" / "python" / "plugins"
        if default_profile.exists():
            return default_profile
        
        # Fallback: profil courant
        current_profile = profile_dir / "default"
        if current_profile.exists():
            return current_profile / "python" / "plugins"
        
        # Dernier fallback: créer le dossier
        default_profile.mkdir(parents=True, exist_ok=True)
        return default_profile / "python" / "plugins"
    
    def ensure_correct_site_packages(self):
        """
        S'assure que le bon site-packages est utilisé pour la version actuelle
        """
        if not self.current_site_packages:
            print("WARNING: Impossible de détecter le site-packages de QGIS")
            return
        
        site_packages_str = str(self.current_site_packages)
        
        # Ajouter au début du path s'il n'y est pas déjà
        if site_packages_str not in sys.path:
            sys.path.insert(0, site_packages_str)
        
        # Supprimer les autres site-packages QGIS du path
        for path_item in sys.path[:]:
            path_obj = Path(path_item).resolve()
            # Vérifier si c'est un autre site-packages QGIS
            if "Python" in str(path_obj) and "site-packages" in str(path_obj):
                if str(path_obj) != site_packages_str:
                    sys.path.remove(path_item)
                    print(f"Supprimé du path: {path_obj}")
    
    def check_plugin_conflicts(self) -> List[str]:
        """
        Vérifie les conflits potentiels avec d'autres installations QGIS
        
        Returns:
            Liste des avertissements
        """
        warnings = []
        
        # Vérifier si le plugin existe dans plusieurs emplacements
        plugin_path = self.get_plugin_path()
        installations = self.find_all_qgis_installations()
        
        for installation in installations:
            other_plugin_path = Path(installation["path"]) / "apps" / "qgis" / "python" / "plugins"
            if other_plugin_path.exists() and other_plugin_path != plugin_path:
                warnings.append(
                    f"Plugin path détecté dans une autre installation: {other_plugin_path}"
                )
        
        # Vérifier les variables d'environnement
        if "QGIS_PREFIX_PATH" in os.environ:
            qgis_prefix = os.environ["QGIS_PREFIX_PATH"]
            if self.current_qgis_path and Path(qgis_prefix) != self.current_qgis_path:
                warnings.append(
                    f"QGIS_PREFIX_PATH pointe vers une autre installation: {qgis_prefix}"
                )
        
        return warnings
    
    def fix_path_issues(self):
        """
        Corrige les problèmes de chemin courants avec plusieurs installations QGIS
        """
        # 1. S'assurer du bon site-packages
        self.ensure_correct_site_packages()
        
        # 2. Nettoyer les doublons dans sys.path
        seen = set()
        clean_path = []
        for path_item in sys.path:
            resolved = str(Path(path_item).resolve())
            if resolved not in seen:
                seen.add(resolved)
                clean_path.append(path_item)
        sys.path[:] = clean_path
        
        # 3. Log les informations
        info = self.get_qgis_info()
        print(f"QGIS Version Manager:")
        print(f"  Version: {info['version']}")
        print(f"  Path: {info['path']}")
        print(f"  Site-packages: {info['site_packages']}")
        print(f"  Python: {info['python_version']}")


# Instance globale
qgis_version_manager = QgisVersionManager()


def fix_qgis_multi_version_issues():
    """
    Fonction utilitaire pour corriger les problèmes de versions multiples
    À appeler au début du plugin
    """
    manager = QgisVersionManager()
    
    # Corriger les problèmes de chemin
    manager.fix_path_issues()
    
    # Vérifier les conflits
    warnings = manager.check_plugin_conflicts()
    if warnings:
        print("WARNINGS - Conflits détectés:")
        for warning in warnings:
            print(f"  - {warning}")
    
    return manager
