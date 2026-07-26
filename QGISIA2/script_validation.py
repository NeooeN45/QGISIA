# -*- coding: utf-8 -*-
"""
script_validation — validation de sécurité des scripts PyQGIS générés par LLM.

Module PUR (aucune dépendance Qt/QGIS) afin d'être testable en CI sans
environnement QGIS. Il centralise la défense AVANT tout `exec()` :

- blocklist regex (patterns qui crashent QGIS / exécution évidente) ;
- analyse AST anti-évasion (imports dangereux, accès dunder, builtins) ;
- détection de fonctions hallucinées fréquentes.

Extrait de geoai_assistant.ScriptWorker (décomposition du monolithe).
"""
from __future__ import annotations

import ast
import re
from typing import List, Optional, Tuple

# Patterns dangereux qui font crasher QGIS ou exécutent du code évident.
DANGEROUS_PATTERNS: List[str] = [
    r'\bexit\s*\(\s*\)',
    r'\bquit\s*\(\s*\)',
    r'\bsys\.exit\s*\(',
    r'\bos\._exit\s*\(',
    r'\b__import__\s*\(',
    r'\beval\s*\(',
    r'\bexec\s*\(',
    r'\bsubprocess\.',
    r'\bos\.system\s*\(',
    r'\bos\.popen\s*\(',
]

# Racines de modules dont l'import est interdit dans un script généré par LLM.
BLOCKED_IMPORT_ROOTS = frozenset({
    "os", "sys", "subprocess", "shutil", "socket", "ctypes",
    "importlib", "builtins", "multiprocessing", "pickle", "marshal",
    "code", "pty", "signal", "requests", "urllib", "http", "ftplib",
    "smtplib", "telnetlib", "webbrowser", "platform",
})

# Builtins dont l'appel/référence est interdit (exécution, I/O, introspection).
BLOCKED_NAMES = frozenset({
    "eval", "exec", "compile", "open", "__import__", "getattr",
    "setattr", "delattr", "globals", "locals", "vars", "input",
    "breakpoint", "memoryview",
})

# Attributs « dunder » exploités pour les évasions de sandbox classiques.
BLOCKED_DUNDERS = frozenset({
    "__class__", "__bases__", "__base__", "__subclasses__", "__mro__",
    "__globals__", "__builtins__", "__import__", "__dict__",
    "__getattribute__", "__reduce__", "__reduce_ex__", "__code__",
    "__closure__", "__func__", "__self__",
})

# Fonctions inexistantes fréquemment hallucinées par les LLM.
HALLUCINATED_FUNCTIONS = frozenset({
    "searchGeoApiCommunes",
    "searchCadastreParcels",
    "applyParcelStylePreset",
    "setLayerLabels",
    "addServiceLayer",
})


def ast_security_scan(script: str) -> Optional[str]:
    """Analyse AST anti-évasion. Retourne un message d'erreur, ou None si sûr.

    Si le script n'est pas analysable (SyntaxError), on retourne None : aucun
    code n'aura été exécuté, l'erreur sera levée par Python à l'exécution.
    """
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BLOCKED_IMPORT_ROOTS:
                    return f"import interdit '{alias.name}'"
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in BLOCKED_IMPORT_ROOTS:
                return f"import interdit 'from {node.module}'"
        elif isinstance(node, ast.Attribute):
            if node.attr in BLOCKED_DUNDERS:
                return f"accès interne interdit '{node.attr}'"
        elif isinstance(node, ast.Name):
            if node.id in BLOCKED_NAMES:
                return f"fonction interdite '{node.id}'"
    return None


def _get_attribute_chain(node: ast.AST) -> str:
    """Extrait la chaîne complète d'un attribut (ex: obj.method.submethod)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _get_attribute_chain(node.value) + "." + node.attr
    return ""


def detect_undefined_functions(script: str) -> List[str]:
    """Détecte les appels à des fonctions hallucinées inexistantes en PyQGIS."""
    undefined: List[str] = []
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return undefined

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in HALLUCINATED_FUNCTIONS:
                    undefined.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                full_name = _get_attribute_chain(node.func)
                if full_name in HALLUCINATED_FUNCTIONS:
                    undefined.append(full_name)
    return list(set(undefined))


def validate_script(script: str) -> Tuple[bool, Optional[str]]:
    """Valide un script avant exécution. Retourne (is_valid, error_message)."""
    for pattern in DANGEROUS_PATTERNS:
        match = re.search(pattern, script, re.IGNORECASE)
        if match:
            return False, (
                f"Code dangereux détecté et bloqué: '{match.group(0)}'\n"
                "Ce pattern peut crasher QGIS."
            )

    ast_error = ast_security_scan(script)
    if ast_error:
        return False, f"Code dangereux détecté et bloqué: {ast_error}"

    undefined = detect_undefined_functions(script)
    if undefined:
        return False, (
            f"Fonctions inexistantes détectées: {', '.join(undefined)}\n"
            "Ces fonctions ne sont pas disponibles dans PyQGIS."
        )

    return True, None
