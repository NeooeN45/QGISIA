# -*- coding: utf-8 -*-
"""
sandbox_runner — enfant du bac à sable. NE JAMAIS importer depuis QGIS.

Ce module est lancé comme programme par `script_sandbox`, dans un processus
jetable démarré en mode isolé (`python -I -S -B sandbox_runner.py`). Il est
volontairement **autonome** : le mode isolé retire le dossier du script de
`sys.path`, donc aucun import frère n'est possible (et c'est voulu).

Contrat d'exécution :
- entrée  : un objet JSON sur stdin -> {"script": "<code>"}
- sortie  : un objet JSON sur stdout -> {"ok", "message", "traceback", "stdout"}
- capacités : builtins réduits, `__import__` filtré par allowlist, aucun accès
  fichier (`open` absent), aucun `eval`/`exec`/`compile`/`getattr`.

C'est ICI — et nulle part ailleurs — que le `exec` du script a lieu. Le
processus QGIS n'exécute plus jamais de code généré par un LLM : il ne fait
que lire le JSON de résultat. Ce processus est sans capacité et tuable par
l'OS, ce qui rend l'`exec` acceptable ; il est le produit du durcissement,
pas un oubli.
"""
from __future__ import annotations

import builtins as _builtins
import io
import json
import sys
import traceback

# Racines importables dans le bac à sable.
#
# C'est l'allowlist de `script_validation` PRIVÉE de `qgis` et `processing` :
# le sous-processus n'a aucun accès au projet QGIS. Toute mutation du projet
# passe par l'API de commandes autorisées (`script_commands`), jamais par ici.
# `tests/test_script_sandbox.py` vérifie que les deux listes ne dérivent pas.
ALLOWED_IMPORT_ROOTS = frozenset({
    "math", "statistics", "decimal", "fractions", "random",
    "json", "re", "string", "textwrap", "unicodedata",
    "collections", "itertools", "bisect", "heapq", "copy", "array",
    "datetime", "enum", "dataclasses", "typing", "uuid",
})

# Builtins exposés au script. Tout ce qui permet d'exécuter du code, de
# toucher au système de fichiers ou d'introspecter l'interpréteur est absent :
# eval, exec, compile, open, getattr, setattr, delattr, globals, locals, vars,
# input, breakpoint, help, dir, type, object, super, memoryview, id.
_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "ascii", "bin", "bool", "bytes", "callable", "chr",
    "complex", "dict", "divmod", "enumerate", "filter", "float", "format",
    "frozenset", "hash", "hex", "int", "isinstance", "issubclass", "iter",
    "len", "list", "map", "max", "min", "next", "oct", "ord", "pow", "print",
    "range", "repr", "reversed", "round", "set", "slice", "sorted", "str",
    "sum", "tuple", "zip",
)

# Exceptions nécessaires pour écrire du code défensif lisible.
_SAFE_EXCEPTION_NAMES = (
    "BaseException", "Exception", "ArithmeticError", "AssertionError",
    "AttributeError", "IndexError", "KeyError", "KeyboardInterrupt",
    "LookupError", "NotImplementedError", "OverflowError", "RuntimeError",
    "StopIteration", "TypeError", "ValueError", "ZeroDivisionError",
)

# Borne de la sortie standard renvoyée (anti-saturation du pipe et de l'UI).
MAX_STDOUT_CHARS = 64 * 1024

_REAL_IMPORT = _builtins.__import__


def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    """`__import__` filtré : refuse tout ce qui n'est pas dans l'allowlist."""
    if level:
        raise ImportError("import relatif interdit dans le bac à sable")
    root = (name or "").split(".")[0]
    if root not in ALLOWED_IMPORT_ROOTS:
        raise ImportError(
            f"import '{name}' interdit dans le bac à sable. "
            "Pour agir sur le projet QGIS, utiliser l'API de commandes."
        )
    return _REAL_IMPORT(name, globals, locals, fromlist, level)


def build_safe_builtins():
    """Construit le dictionnaire de builtins exposé au script.

    `__import__` y figure, mais c'est la version filtrée `guarded_import` :
    sans elle l'instruction `import` ne fonctionnerait pas du tout. Les tests
    vérifient son comportement, pas seulement sa présence.
    """
    safe = {}
    for name in _SAFE_BUILTIN_NAMES + _SAFE_EXCEPTION_NAMES:
        if hasattr(_builtins, name):
            safe[name] = getattr(_builtins, name)
    safe["__import__"] = guarded_import
    return safe


def _apply_os_limits():
    """Durcit le processus au niveau OS quand la plateforme le permet.

    POSIX uniquement : RLIMIT_FSIZE=0 interdit matériellement l'écriture de
    tout fichier, RLIMIT_AS borne la mémoire. Sous Windows ces limites
    n'existent pas ; la containment y repose sur l'absence de capacités et sur
    la terminaison par TerminateProcess.
    """
    try:
        import resource  # noqa: PLC0415 - POSIX seulement, import tardif voulu
    except ImportError:
        return
    for limit_name, value in (
        ("RLIMIT_FSIZE", 0),                 # aucune écriture de fichier
        ("RLIMIT_AS", 1024 * 1024 * 1024),   # 1 Go d'espace d'adressage
        ("RLIMIT_CORE", 0),                  # pas de core dump
    ):
        limit = getattr(resource, limit_name, None)
        if limit is None:
            continue
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            continue


def execute(script):
    """Exécute le script dans l'environnement restreint et renvoie le résultat."""
    captured = io.StringIO()
    real_stdout = sys.stdout
    sandbox_globals = {
        "__builtins__": build_safe_builtins(),
        "__name__": "__sandbox__",
    }

    try:
        sys.stdout = captured
        # Unique `exec` du produit, dans un processus jetable et sans capacité.
        exec(compile(script, "<script-qgisia>", "exec"), sandbox_globals)  # noqa: S102
    except BaseException:  # noqa: BLE001 - tout est rapporté, rien ne s'échappe
        return {
            "ok": False,
            "message": "Erreur lors de l'exécution du script.",
            "traceback": traceback.format_exc(limit=20),
            "stdout": captured.getvalue()[:MAX_STDOUT_CHARS],
        }
    finally:
        sys.stdout = real_stdout

    return {
        "ok": True,
        "message": "Script exécuté avec succès.",
        "traceback": "",
        "stdout": captured.getvalue()[:MAX_STDOUT_CHARS],
    }


def main():
    _apply_os_limits()
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        script = payload.get("script", "")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        result = {
            "ok": False,
            "message": f"Charge utile illisible: {exc}",
            "traceback": "",
            "stdout": "",
        }
    else:
        result = execute(script)

    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
