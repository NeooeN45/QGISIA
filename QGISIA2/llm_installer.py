# -*- coding: utf-8 -*-
"""
Auto-installation de litellm dans un dossier vendor/ isole du plugin.

Strategie turnkey :
- Aucune dependance Docker
- Aucun venv systeme
- pip install --target qgis_plugin/vendor/ litellm + deps minimales
- sys.path prepend de vendor/ pour que les imports soient prioritaires

Compatible QGIS Python 3.9+, Windows / Linux / macOS.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Dict, Optional

# Import plugin_logger si disponible (mode plugin QGIS), sinon fallback
plugin_logger = None
try:
    from .error_handler import plugin_logger
except ImportError:
    # Mode standalone (console Python direct)
    class _FakeLogger:
        def info(self, msg): print(f"[INFO] {msg}", file=sys.stderr, flush=True)
        def warning(self, msg): print(f"[WARN] {msg}", file=sys.stderr, flush=True)
        def error(self, msg): print(f"[ERROR] {msg}", file=sys.stderr, flush=True)
    plugin_logger = _FakeLogger()

PLUGIN_DIR = Path(__file__).parent
VENDOR_DIR = PLUGIN_DIR / "vendor"
MARKER_FILE = VENDOR_DIR / ".installed"

# Dependances minimales. Versions epinglees pour reproductibilite commerciale.
REQUIRED_PACKAGES = [
    # Versions épinglées (reproductibilité + supply chain). Aligné sur
    # requirements.txt à la racine du dépôt.
    "litellm==1.52.0",
    "pyyaml==6.0.2",
    "httpx==0.27.2",
    "tiktoken==0.8.0",
    "certifi==2024.8.30",  # Certificats SSL pour HTTPS
]

# Version minimale de pip requise
MIN_PIP_VERSION = "21.0"

_install_lock = threading.Lock()
_install_in_progress = False

# Système de debug/logs d'installation pour feedback UI
_install_logs: list[dict] = []
_install_status = {"stage": "idle", "progress": 0, "error": None, "done": False}

# Fichier de log persistant pour debug
DEBUG_LOG_FILE = PLUGIN_DIR / "install_debug.log"

def _write_file_log(message: str):
    """Écrit dans le fichier de log persistant."""
    import datetime
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass  # Ignorer les erreurs de fichier

def get_install_status() -> dict:
    """Retourne le statut courant de l'installation avec logs."""
    global _install_status, _install_logs
    with _install_lock:
        return {
            "status": _install_status["stage"],
            "progress": _install_status["progress"],
            "error": _install_status["error"],
            "done": _install_status["done"],
            "logs": list(_install_logs),
            "in_progress": _install_in_progress,
            "vendor_ready": is_vendor_ready(),
            "debug_file": str(DEBUG_LOG_FILE) if DEBUG_LOG_FILE.exists() else None,
        }

def _log(stage: str, message: str, level: str = "info"):
    """Ajoute un log d'installation avec timestamp."""
    global _install_logs, _install_status
    import time
    entry = {"time": time.time(), "stage": stage, "message": message, "level": level}
    log_line = f"[INSTALL:{stage}] {message}"
    with _install_lock:
        _install_logs.append(entry)
        _install_status["stage"] = stage
        if level == "error":
            _install_status["error"] = message
        plugin_logger.info(log_line)
        _write_file_log(log_line)
        # Also print to stderr for console visibility
        print(log_line, file=sys.stderr, flush=True)


def is_vendor_ready() -> bool:
    """True si vendor/ contient une install litellm fonctionnelle."""
    if not MARKER_FILE.exists():
        return False
    try:
        ensure_vendor_on_path()
        import litellm  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_vendor_on_path() -> None:
    """Prepend vendor/ au sys.path si pas deja present."""
    vendor_str = str(VENDOR_DIR)
    if VENDOR_DIR.exists() and vendor_str not in sys.path:
        sys.path.insert(0, vendor_str)


def _check_pip_version() -> tuple[bool, str]:
    """Verifie que pip est disponible via subprocess (robuste même sous QGIS)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return False, f"pip indisponible (code {result.returncode}): {result.stderr.strip()}"
        # stdout: "pip 24.0 from ..."
        stdout = result.stdout.strip()
        version = stdout.split()[1] if len(stdout.split()) >= 2 else stdout
        parts = version.split('.')
        major = int(parts[0]) if parts[0].isdigit() else 0
        minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        min_major, min_minor = 21, 0
        if (major, minor) >= (min_major, min_minor):
            return True, version
        return False, version
    except Exception as e:
        return False, f"erreur: {e}"


def _pip_install(progress_cb: Optional[Callable[[str], None]] = None) -> Dict:
    """Execute pip install --target vendor/ REQUIRED_PACKAGES avec debug complet."""
    global _install_status
    _log("init", f"Démarrage installation dans {VENDOR_DIR}")
    _log("init", f"Python: {sys.executable}")
    _log("init", f"Platform: {sys.platform}")
    
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    _log("init", f"Dossier vendor créé: {VENDOR_DIR.exists()}")
    
    # Verif pip version
    _log("pip", "Vérification version pip...")
    if progress_cb:
        progress_cb("Verification de pip...")
    pip_ok, pip_ver = _check_pip_version()
    _log("pip", f"Version pip: {pip_ver}, OK: {pip_ok}")
    if not pip_ok:
        err_msg = f"pip trop ancien ({pip_ver}). Requis: {MIN_PIP_VERSION}+"
        _log("pip", err_msg, "error")
        return {"success": False, "error": err_msg}
    
    if progress_cb:
        progress_cb(f"pip OK ({pip_ver})")

    cmd = [
        sys.executable,
        "-m", "pip", "install",
        "--target", str(VENDOR_DIR),
        "--upgrade",
        "--no-warn-script-location",
        "--disable-pip-version-check",
        *REQUIRED_PACKAGES,
    ]
    _log("pip", f"Commande: {' '.join(cmd)}")

    if progress_cb:
        progress_cb(f"Téléchargement {len(REQUIRED_PACKAGES)} packages...")
    
    _log("download", f"Packages à installer: {REQUIRED_PACKAGES}")
    
    try:
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            _log("exec", "Mode Windows (CREATE_NO_WINDOW)")

        _log("exec", "Lancement subprocess...")
        with _install_lock:
            _install_status["progress"] = 30
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max
            creationflags=creationflags,
        )
        _log("exec", f"Subprocess terminé, returncode: {result.returncode}")
        
        with _install_lock:
            _install_status["progress"] = 70
    except subprocess.TimeoutExpired:
        _log("exec", "TIMEOUT après 10min", "error")
        return {"success": False, "error": "Timeout pip install (>10min)"}
    except Exception as exc:
        _log("exec", f"Exception: {exc}", "error")
        return {"success": False, "error": f"Echec pip: {exc}"}

    if result.returncode != 0:
        err_detail = result.stderr[-2000:] if result.stderr else "(pas de stderr)"
        _log("pip", f"ECHEC pip (code {result.returncode}): {err_detail}", "error")
        return {
            "success": False,
            "error": f"pip exit code {result.returncode}",
            "stderr": err_detail,
        }

    _log("pip", "pip install OK")
    _log("verify", "Création marker file...")
    MARKER_FILE.write_text("ok", encoding="utf-8")
    
    _log("verify", "Test import litellm...")
    ensure_vendor_on_path()
    try:
        import litellm
        _log("verify", f"litellm importé avec succès (version: {getattr(litellm, '__version__', 'unknown')})")
    except ImportError as e:
        _log("verify", f"ERREUR import litellm: {e}", "error")
        return {"success": False, "error": f"Import litellm échoué: {e}"}
    
    with _install_lock:
        _install_status["progress"] = 100
        _install_status["done"] = True
    
    _log("complete", "Installation terminée avec succès")
    return {"success": True, "stdout": result.stdout[-1000:]}


def install_if_needed(
    progress_cb: Optional[Callable[[str], None]] = None,
    force: bool = False,
) -> Dict:
    """
    Point d'entree unique. Idempotent, thread-safe avec debug complet.

    Returns:
        {success: bool, already_installed: bool, error?: str, logs?: list}
    """
    global _install_in_progress, _install_logs, _install_status

    if not force and is_vendor_ready():
        _log("check", "Vendor déjà prêt, skip installation")
        return {"success": True, "already_installed": True, "logs": []}

    with _install_lock:
        if _install_in_progress:
            _log("check", "Installation déjà en cours", "warning")
            return {"success": False, "error": "Install deja en cours", "logs": list(_install_logs)}
        # Reset logs pour nouvelle installation
        _install_logs = []
        _install_status = {"stage": "starting", "progress": 0, "error": None, "done": False}
        _install_in_progress = True
        _log("start", "=== Démarrage installation Gateway IA ===")

    try:
        if progress_cb:
            progress_cb("Préparation du gateway IA...")

        result = _pip_install(progress_cb=progress_cb)
        result["already_installed"] = False
        result["logs"] = list(_install_logs)

        if result["success"]:
            _log("complete", "✓ Gateway IA prêt")
            if progress_cb:
                progress_cb("Gateway IA prêt.")
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
        target=install_if_needed,
        kwargs={"progress_cb": progress_cb},
        daemon=True,
        name="QGISIAPlusInstaller",
    )
    thread.start()
    return thread


# Auto-ajout du vendor au sys.path des l'import du module
ensure_vendor_on_path()
