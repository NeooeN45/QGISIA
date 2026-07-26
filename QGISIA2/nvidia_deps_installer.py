# -*- coding: utf-8 -*-
"""
Auto-installation des dépendances NVIDIA (torch CUDA + earth2studio).

Ce module gère l'installation de:
- torch avec support CUDA (et non la version CPU)
- earth2studio pour les prévisions météo/climat
- xarray, netCDF4 pour le traitement des données

Usage:
    from nvidia_deps_installer import install_nvidia_deps, is_nvidia_deps_available
    
    # Vérifier si les deps sont disponibles
    ok, reason = is_nvidia_deps_available()
    
    # Installer si nécessaire
    result = install_nvidia_deps()
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Dict, Optional

# Import plugin_logger si disponible
plugin_logger = None
try:
    from .error_handler import plugin_logger
except ImportError:
    import logging
    plugin_logger = logging.getLogger(__name__)

PLUGIN_DIR = Path(__file__).parent
VENDOR_DIR = PLUGIN_DIR / "vendor"
MARKER_FILE = VENDOR_DIR / ".nvidia_deps_installed"

_install_lock = threading.Lock()
_install_in_progress = False
_install_logs: list[dict] = []
_install_status = {"stage": "idle", "progress": 0, "error": None, "done": False}

def _log(stage: str, message: str, level: str = "info"):
    """Ajoute un log d'installation."""
    global _install_logs, _install_status
    import time
    entry = {"time": time.time(), "stage": stage, "message": message, "level": level}
    log_line = f"[NVIDIA:{stage}] {message}"
    with _install_lock:
        _install_logs.append(entry)
        _install_status["stage"] = stage
        if level == "error":
            _install_status["error"] = message
        if plugin_logger:
            getattr(plugin_logger, level, plugin_logger.info)(log_line)
        print(log_line, file=sys.stderr, flush=True)

def get_install_status() -> dict:
    """Retourne le statut courant de l'installation."""
    global _install_status, _install_logs
    with _install_lock:
        return {
            "status": _install_status["stage"],
            "progress": _install_status["progress"],
            "error": _install_status["error"],
            "done": _install_status["done"],
            "logs": list(_install_logs),
            "in_progress": _install_in_progress,
            "vendor_ready": is_nvidia_deps_available()[0],
        }

def is_nvidia_deps_available() -> tuple[bool, str]:
    """
    Vérifie que torch CUDA + earth2studio sont disponibles.
    Retourne (True, "") si OK, sinon (False, raison).
    """
    try:
        import torch
        if not torch.cuda.is_available():
            # Vérifier si c'est la version CPU
            if hasattr(torch, '_C') and 'cpu' in str(torch.__file__).lower():
                return False, "torch est installé en version CPU (pas CUDA). Réinstallation nécessaire."
    except ImportError as e:
        return False, f"torch non installé : {e}"
    
    try:
        import xarray  # noqa: F401
    except ImportError as e:
        return False, f"xarray non installé : {e}"
    
    try:
        import netCDF4  # noqa: F401
    except ImportError as e:
        return False, f"netCDF4 non installé : {e}"
    
    try:
        import earth2studio  # noqa: F401
    except ImportError as e:
        return False, f"earth2studio non installé : {e}"
    
    return True, ""

def ensure_vendor_on_path() -> None:
    """Prepend vendor/ au sys.path si pas déjà présent."""
    vendor_str = str(VENDOR_DIR)
    if VENDOR_DIR.exists() and vendor_str not in sys.path:
        sys.path.insert(0, vendor_str)

def _get_torch_index_url() -> str:
    """Retourne l'URL de l'index PyTorch pour CUDA 12.4."""
    return "https://download.pytorch.org/whl/cu124"

def _pip_install_nvidia_deps(progress_cb: Optional[Callable[[str], None]] = None) -> Dict:
    """Installe torch CUDA + earth2studio + dépendances."""
    global _install_status
    
    _log("init", f"Démarrage installation NVIDIA deps dans {VENDOR_DIR}")
    _log("init", f"Python: {sys.executable}")
    _log("init", f"Platform: {sys.platform}")
    
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    _log("init", f"Dossier vendor créé: {VENDOR_DIR.exists()}")
    
    # URL pour torch CUDA
    torch_index = _get_torch_index_url()
    _log("init", f"PyTorch index: {torch_index}")
    
    # Packages à installer
    # Note: torch torchvision torchaudio avec index CUDA.
    # Sécurité supply-chain : épingler ces versions (ex: torch==2.4.1) une fois
    # la matrice CUDA/driver figée, puis envisager --require-hashes.
    nvidia_packages = [
        "torch",
        "torchvision", 
        "torchaudio",
        "--index-url", torch_index,
    ]
    
    earth2_packages = [
        "earth2studio",
        "xarray",
        "netCDF4",
        "h5netcdf",  # Pour la compatibilité netCDF
        "cfgrib",    # Pour les données GRIB (météo)
        "eccodes",   # Dépendance cfgrib
    ]
    
    if progress_cb:
        progress_cb("Installation PyTorch CUDA...")
    
    # Installation PyTorch CUDA
    cmd_torch = [
        sys.executable,
        "-m", "pip", "install",
        "--target", str(VENDOR_DIR),
        "--upgrade",
        "--no-warn-script-location",
        "--disable-pip-version-check",
        *nvidia_packages,
    ]
    
    _log("torch", f"Commande: {' '.join(cmd_torch)}")
    
    try:
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW
            _log("torch", "Mode Windows (CREATE_NO_WINDOW)")
        
        with _install_lock:
            _install_status["progress"] = 20
        
        result = subprocess.run(
            cmd_torch,
            capture_output=True,
            text=True,
            timeout=600,
            creationflags=creationflags,
        )
        
        if result.returncode != 0:
            err_detail = result.stderr[-2000:] if result.stderr else "(pas de stderr)"
            _log("torch", f"ECHEC torch (code {result.returncode}): {err_detail}", "error")
            return {
                "success": False,
                "error": f"torch install failed: {err_detail}",
            }
        
        _log("torch", "PyTorch CUDA installé avec succès")
        
        with _install_lock:
            _install_status["progress"] = 50
        
    except subprocess.TimeoutExpired:
        _log("torch", "TIMEOUT après 10min", "error")
        return {"success": False, "error": "Timeout torch install (>10min)"}
    except Exception as exc:
        _log("torch", f"Exception: {exc}", "error")
        return {"success": False, "error": f"Echec torch: {exc}"}
    
    if progress_cb:
        progress_cb("Installation earth2studio...")
    
    # Installation earth2studio + deps
    cmd_earth2 = [
        sys.executable,
        "-m", "pip", "install",
        "--target", str(VENDOR_DIR),
        "--upgrade",
        "--no-warn-script-location", 
        "--disable-pip-version-check",
        *earth2_packages,
    ]
    
    _log("earth2", f"Commande: {' '.join(cmd_earth2)}")
    
    try:
        result = subprocess.run(
            cmd_earth2,
            capture_output=True,
            text=True,
            timeout=600,
            creationflags=creationflags,
        )
        
        if result.returncode != 0:
            err_detail = result.stderr[-2000:] if result.stderr else "(pas de stderr)"
            _log("earth2", f"ECHEC earth2studio (code {result.returncode}): {err_detail}", "error")
            return {
                "success": False,
                "error": f"earth2studio install failed: {err_detail}",
            }
        
        _log("earth2", "earth2studio installé avec succès")
        
        with _install_lock:
            _install_status["progress"] = 80
            
    except subprocess.TimeoutExpired:
        _log("earth2", "TIMEOUT après 10min", "error")
        return {"success": False, "error": "Timeout earth2studio install (>10min)"}
    except Exception as exc:
        _log("earth2", f"Exception: {exc}", "error")
        return {"success": False, "error": f"Echec earth2studio: {exc}"}
    
    # Vérification finale
    _log("verify", "Vérification des installations...")
    ensure_vendor_on_path()
    
    ok, reason = is_nvidia_deps_available()
    if not ok:
        _log("verify", f"Vérification échouée: {reason}", "error")
        return {"success": False, "error": f"Vérification échouée: {reason}"}
    
    # Créer marker file
    MARKER_FILE.write_text("ok", encoding="utf-8")
    
    with _install_lock:
        _install_status["progress"] = 100
        _install_status["done"] = True
    
    _log("complete", "✓ Dépendances NVIDIA prêtes")
    
    # Info sur CUDA
    try:
        import torch
        cuda_version = torch.version.cuda
        _log("info", f"CUDA version: {cuda_version}")
    except:
        pass
    
    return {"success": True}

def install_nvidia_deps(
    progress_cb: Optional[Callable[[str], None]] = None,
    force: bool = False,
) -> Dict:
    """
    Point d'entrée unique pour l'installation des dépendances NVIDIA.
    
    Args:
        progress_cb: Callback pour les mises à jour de progression
        force: Force la réinstallation même si déjà présent
        
    Returns:
        Dict avec success, error, logs
    """
    global _install_in_progress, _install_logs, _install_status
    
    if not force:
        ok, _ = is_nvidia_deps_available()
        if ok:
            _log("check", "Dépendances NVIDIA déjà prêtes, skip installation")
            return {"success": True, "already_installed": True, "logs": []}
    
    with _install_lock:
        if _install_in_progress:
            _log("check", "Installation déjà en cours", "warning")
            return {"success": False, "error": "Install déjà en cours", "logs": list(_install_logs)}
        _install_logs = []
        _install_status = {"stage": "starting", "progress": 0, "error": None, "done": False}
        _install_in_progress = True
        _log("start", "=== Démarrage installation dépendances NVIDIA ===")
    
    try:
        if progress_cb:
            progress_cb("Préparation de l'installation NVIDIA...")
        
        result = _pip_install_nvidia_deps(progress_cb=progress_cb)
        result["already_installed"] = False
        result["logs"] = list(_install_logs)
        
        if result["success"]:
            _log("complete", "✓ Installation NVIDIA terminée")
            if progress_cb:
                progress_cb("Dépendances NVIDIA prêtes!")
        else:
            _log("complete", f"✗ Échec: {result.get('error', 'unknown')}", "error")
        
        return result
        
    except Exception as e:
        _log("exception", f"Exception inattendue: {e}", "error")
        return {"success": False, "error": str(e), "logs": list(_install_logs)}
    finally:
        with _install_lock:
            _install_in_progress = False

def install_async(progress_cb: Optional[Callable[[str], None]] = None) -> threading.Thread:
    """Lance l'install en thread (non-bloquant pour QGIS UI)."""
    thread = threading.Thread(
        target=install_nvidia_deps,
        kwargs={"progress_cb": progress_cb},
        daemon=True,
        name="QGISIANvidiaInstaller",
    )
    thread.start()
    return thread


# Auto-ajout du vendor au sys.path dès l'import
ensure_vendor_on_path()
