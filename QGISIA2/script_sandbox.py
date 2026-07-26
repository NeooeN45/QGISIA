# -*- coding: utf-8 -*-
"""
script_sandbox — exécution des scripts PyQGIS HORS du processus QGIS.

Remplace l'ancien `exec(script, local_context, local_context)` qui tournait
dans le processus QGIS avec `__builtins__` complet, dans un thread `daemon`
que le timeout ne tuait pas (il se contentait de signaler l'expiration
pendant que le thread continuait à consommer du CPU).

Ici, l'exécution a lieu dans un sous-processus :
- démarré en mode isolé (`-I -S -B`) : ni PYTHONPATH, ni site-packages
  utilisateur, ni dossier du script dans `sys.path`, ni écriture de .pyc ;
- doté de builtins réduits et d'un `__import__` filtré (`sandbox_runner`) ;
- **réellement tué** au timeout par l'OS (SIGKILL / TerminateProcess), puis
  moissonné : `returncode` est toujours renseigné après un timeout.

Deux entrées :
- `run_sandboxed`   : validation statique PUIS bac à sable (usage produit) ;
- `spawn_sandboxed` : bac à sable seul, sans validation — utilisé par les
  tests pour prouver que la seconde barrière tient toute seule.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, Optional

try:
    from . import script_validation
except ImportError:  # pragma: no cover - import absolu (standalone / tests)
    import script_validation  # type: ignore[no-redef]

# Délai par défaut d'exécution d'un script (secondes).
DEFAULT_TIMEOUT_SECONDS = 30

# Marge laissée au processus pour mourir après le signal de terminaison.
_KILL_GRACE_SECONDS = 5

_RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sandbox_runner.py")


def _refused(message: str, traceback_text: str = "") -> Dict[str, Any]:
    """Résultat d'un script refusé avant tout lancement de processus."""
    return {
        "ok": False,
        "message": message,
        "traceback": traceback_text or message,
        "stdout": "",
        "timed_out": False,
        "pid": None,
        "returncode": None,
    }


def resolve_python_executable() -> Optional[str]:
    """Trouve un interpréteur Python utilisable pour le sous-processus.

    Dans QGIS, `sys.executable` désigne souvent `qgis-bin.exe` : le lancer
    rouvrirait QGIS au lieu d'exécuter le runner. On ne l'utilise donc que
    s'il ressemble vraiment à un interpréteur, sinon on cherche à côté de
    `sys.prefix`, puis dans le PATH.
    """
    override = os.environ.get("QGISIA_SANDBOX_PYTHON")
    if override and os.path.exists(override):
        return override

    candidate = sys.executable or ""
    name = os.path.basename(candidate).lower()
    if candidate and (name.startswith("python") or name.startswith("pythonw")):
        return candidate

    for relative in ("python.exe", "pythonw.exe", os.path.join("bin", "python3"),
                     os.path.join("bin", "python")):
        path = os.path.join(sys.prefix, relative)
        if os.path.exists(path):
            return path

    return shutil.which("python3") or shutil.which("python")


def process_is_finished(pid: Optional[int]) -> bool:
    """True si le processus `pid` n'est plus vivant (vérification OS réelle)."""
    if pid is None:
        return True
    if os.name == "nt":
        import ctypes  # noqa: PLC0415 - Windows seulement

        SYNCHRONIZE = 0x00100000
        WAIT_OBJECT_0 = 0x00000000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not handle:
            return True  # introuvable => terminé
        try:
            return kernel32.WaitForSingleObject(handle, 0) == WAIT_OBJECT_0
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _kill(process) -> None:
    """Tue le processus et, sous POSIX, tout son groupe."""
    if os.name != "nt":
        try:
            os.killpg(os.getpgid(process.pid), 9)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        process.kill()
    except OSError:
        pass


def spawn_sandboxed(
    script: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    python_executable: Optional[str] = None,
) -> Dict[str, Any]:
    """Exécute `script` dans le sous-processus bac à sable, SANS validation.

    Réservé aux tests de la seconde barrière et à `run_sandboxed`. Le code
    produit doit appeler `run_sandboxed`, qui valide d'abord.
    """
    interpreter = python_executable or resolve_python_executable()
    if not interpreter:
        return _refused(
            "Aucun interpréteur Python utilisable pour le bac à sable.\n"
            "Définir QGISIA_SANDBOX_PYTHON sur le chemin de python."
        )
    if not os.path.exists(_RUNNER):
        return _refused(f"Runner du bac à sable introuvable : {_RUNNER}")

    popen_kwargs: Dict[str, Any] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": os.path.dirname(_RUNNER),
        # Environnement minimal : rien des variables du processus QGIS (clés
        # API, jetons, chemins de profil) n'est transmis au script.
        "env": {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"},
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        # Groupe de processus dédié : le kill emporte d'éventuels descendants.
        popen_kwargs["start_new_session"] = True

    command = [interpreter, "-I", "-S", "-B", _RUNNER]
    payload = json.dumps({"script": script}, ensure_ascii=False)

    try:
        process = subprocess.Popen(command, **popen_kwargs)  # noqa: S603
    except OSError as exc:
        return _refused(f"Lancement du bac à sable impossible : {exc}")

    timed_out = False
    try:
        stdout, stderr = process.communicate(payload, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill(process)
        try:
            stdout, stderr = process.communicate(timeout=_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:  # pragma: no cover - défense ultime
            process.kill()
            stdout, stderr = "", ""

    returncode = process.poll()
    pid = process.pid

    if timed_out:
        return {
            "ok": False,
            "message": f"Script interrompu après {timeout_seconds}s (timeout).",
            "traceback": (
                "Le script a dépassé le temps d'exécution maximum et son "
                "processus a été terminé par le système.\n"
                "Causes possibles : boucle infinie, opération trop lourde."
            ),
            "stdout": (stdout or "")[:4096],
            "timed_out": True,
            "pid": pid,
            "returncode": returncode,
        }

    try:
        result = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return {
            "ok": False,
            "message": "Le bac à sable n'a pas renvoyé de résultat exploitable.",
            "traceback": (stderr or stdout or "")[:4096],
            "stdout": "",
            "timed_out": False,
            "pid": pid,
            "returncode": returncode,
        }

    result.setdefault("ok", False)
    result.setdefault("message", "")
    result.setdefault("traceback", "")
    result.setdefault("stdout", "")
    result["timed_out"] = False
    result["pid"] = pid
    result["returncode"] = returncode
    return result


def run_sandboxed(
    script: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    python_executable: Optional[str] = None,
) -> Dict[str, Any]:
    """Valide puis exécute `script`. Entrée à utiliser côté produit.

    Un script refusé par la validation ne fait lancer AUCUN processus
    (`pid` reste None).
    """
    is_valid, error_message = script_validation.validate_script(script)
    if not is_valid:
        return _refused(f"Script bloqué pour sécurité: {error_message}", error_message)

    return spawn_sandboxed(
        script,
        timeout_seconds=timeout_seconds,
        python_executable=python_executable,
    )
