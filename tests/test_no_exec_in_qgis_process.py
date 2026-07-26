# -*- coding: utf-8 -*-
"""Garde-fou de non-régression : aucun exec/eval dans le processus QGIS.

Vérification par AST, pas par grep : un commentaire ou une docstring qui
*mentionne* `exec(` ne doit pas faire échouer la CI, et inversement un vrai
appel ne doit pas pouvoir se cacher derrière une mise en forme inhabituelle.

Ce test tourne aussi sur le code EXTRAIT de l'artefact livré : il garantit que
le ZIP publié ne réintroduit pas un chemin d'exécution dans le processus QGIS.
"""
import ast
import os

import pytest

QGISIA2 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "QGISIA2")

# Seul fichier autorisé à appeler exec : il EST le bac à sable, et ne tourne
# jamais dans le processus QGIS (lancé comme programme séparé).
SANDBOX_RUNNER = "sandbox_runner.py"

DYNAMIC_EXECUTION_BUILTINS = {"exec", "eval", "compile"}


def _python_files():
    for root, dirs, files in os.walk(QGISIA2):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", "vendor", "data"}]
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(root, name)


def _dynamic_execution_calls(path):
    """Appels réels à exec/eval/compile dans un fichier (AST, pas texte)."""
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)

    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in DYNAMIC_EXECUTION_BUILTINS:
                hits.append((node.func.id, node.lineno))
    return hits


def test_repository_has_python_files_to_check():
    # Garde contre un test qui passerait en ne regardant rien.
    assert list(_python_files())


@pytest.mark.parametrize(
    "path",
    [p for p in _python_files() if os.path.basename(p) != SANDBOX_RUNNER],
    ids=lambda p: os.path.relpath(p, QGISIA2).replace(os.sep, "/"),
)
def test_no_dynamic_execution_outside_the_sandbox_runner(path):
    hits = _dynamic_execution_calls(path)
    assert hits == [], (
        f"{os.path.relpath(path, QGISIA2)} appelle "
        + ", ".join(f"{name}() ligne {line}" for name, line in hits)
        + " — l'exécution dynamique doit rester dans sandbox_runner.py"
    )


def test_sandbox_runner_contains_exactly_one_execution_site():
    # Le bac à sable exécute, c'est sa raison d'être — mais une seule fois, à
    # un endroit identifiable et revu.
    path = os.path.join(QGISIA2, SANDBOX_RUNNER)
    hits = _dynamic_execution_calls(path)
    names = sorted(name for name, _ in hits)
    assert names == ["compile", "exec"], names


def test_no_module_passes_full_builtins_to_an_execution_context():
    # Motif exact de la faille corrigée : {"__builtins__": __builtins__}.
    offenders = []
    for path in _python_files():
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                is_builtins_key = (
                    isinstance(key, ast.Constant) and key.value == "__builtins__"
                )
                is_full_builtins = (
                    isinstance(value, ast.Name) and value.id == "__builtins__"
                )
                if is_builtins_key and is_full_builtins:
                    offenders.append(f"{os.path.relpath(path, QGISIA2)}:{node.lineno}")
    assert offenders == [], offenders


def test_no_runscriptdirect_slot_remains():
    offenders = []
    for path in _python_files():
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "runScriptDirect":
                    offenders.append(f"{os.path.relpath(path, QGISIA2)}:{node.lineno}")
    assert offenders == [], offenders
