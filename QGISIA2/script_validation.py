# -*- coding: utf-8 -*-
"""
script_validation — validation de sécurité des scripts PyQGIS générés par LLM.

Module PUR (aucune dépendance Qt/QGIS) afin d'être testable en CI sans
environnement QGIS. Première barrière AVANT le bac à sable :

- rejet des scripts vides ou non analysables ;
- blocklist regex (patterns d'exécution évidents) ;
- **allowlist** de racines d'import : tout ce qui n'est pas listé est refusé ;
- interdiction des dunders (attribut, nom, littéral) ;
- détection de fonctions hallucinées fréquentes.

Le passage blocklist -> allowlist est le correctif de fond : l'ancienne
blocklist énumérait `os`, `socket`, `subprocess`… et laissait donc passer
`pathlib`, `shutil`, `tempfile`, `glob`, `sqlite3`, `importlib`, tous
suffisants pour lire ou écrire des fichiers arbitraires.

Cette validation est une défense statique. Elle ne prétend PAS être complète :
une chaîne dunder reconstruite morceau par morceau lui échappe. La garantie
d'isolation vient du bac à sable hors-processus (`script_sandbox`), qui ne
fournit ni `getattr`, ni `open`, ni import hors allowlist.
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
    r'\bcompile\s*\(',
    r'\bsubprocess\.',
    r'\bos\.system\s*\(',
    r'\bos\.popen\s*\(',
]

# ── Allowlist d'imports ───────────────────────────────────────────────────────
# Seules ces racines sont importables. Défaut = refus.
#
# `qgis` et `processing` sont acceptés par la validation parce qu'ils ne sont
# pas dangereux en soi, mais le bac à sable ne les fournit PAS : un script qui
# veut agir sur le projet QGIS doit passer par l'API de commandes autorisées
# (`script_commands`). Les garder ici évite un faux positif sur du code
# légitime destiné à cette API.
ALLOWED_IMPORT_ROOTS = frozenset({
    # Domaine métier (résolus par l'API de commandes, pas par le bac à sable)
    "qgis", "processing",
    # Calcul pur
    "math", "statistics", "decimal", "fractions", "random",
    # Données et texte
    "json", "re", "string", "textwrap", "unicodedata",
    # Structures
    "collections", "itertools", "bisect", "heapq", "copy", "array",
    # Types et dates
    "datetime", "enum", "dataclasses", "typing", "uuid",
})

# Builtins dont l'appel/référence est interdit (exécution, I/O, introspection).
BLOCKED_NAMES = frozenset({
    "eval", "exec", "compile", "open", "__import__", "getattr",
    "setattr", "delattr", "globals", "locals", "vars", "input",
    "breakpoint", "memoryview", "help", "dir", "super", "object",
})

# Attributs « dunder » exploités pour les évasions de sandbox classiques.
# Conservé pour la lisibilité ; la détection réelle est générique (_DUNDER_RE)
# afin de ne dépendre d'aucune énumération exhaustive.
BLOCKED_DUNDERS = frozenset({
    "__class__", "__bases__", "__base__", "__subclasses__", "__mro__",
    "__globals__", "__builtins__", "__import__", "__dict__",
    "__getattribute__", "__reduce__", "__reduce_ex__", "__code__",
    "__closure__", "__func__", "__self__", "__loader__", "__spec__",
})

# Tout identifiant de la forme __xxx__ : attribut, nom, ou littéral chaîne.
_DUNDER_RE = re.compile(r"^__\w+__$")

# Fonctions inexistantes fréquemment hallucinées par les LLM.
HALLUCINATED_FUNCTIONS = frozenset({
    "searchGeoApiCommunes",
    "searchCadastreParcels",
    "applyParcelStylePreset",
    "setLayerLabels",
    "addServiceLayer",
})


def _is_dunder(name: Optional[str]) -> bool:
    return bool(name) and bool(_DUNDER_RE.match(name))


def _import_root(dotted: Optional[str]) -> str:
    return (dotted or "").split(".")[0]


def ast_security_scan(script: str) -> Optional[str]:
    """Analyse AST anti-évasion. Retourne un message d'erreur, ou None si sûr.

    Un script non analysable est REFUSÉ (message non nul) : on ne laisse pas
    passer du code qu'on n'a pas pu inspecter en pariant que Python lèvera
    l'erreur plus tard.
    """
    try:
        tree = ast.parse(script)
    except SyntaxError as exc:
        return f"script non analysable (SyntaxError: {exc.msg})"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _import_root(alias.name)
                if root not in ALLOWED_IMPORT_ROOTS:
                    return f"import non autorisé '{alias.name}'"

        elif isinstance(node, ast.ImportFrom):
            if node.level:
                return "import relatif interdit"
            root = _import_root(node.module)
            if root not in ALLOWED_IMPORT_ROOTS:
                return f"import non autorisé 'from {node.module}'"

        elif isinstance(node, ast.Attribute):
            if _is_dunder(node.attr):
                return f"accès interne interdit '{node.attr}'"

        elif isinstance(node, ast.Name):
            if node.id in BLOCKED_NAMES:
                return f"fonction interdite '{node.id}'"
            if _is_dunder(node.id):
                return f"accès interne interdit '{node.id}'"

        elif isinstance(node, ast.Constant):
            # Bloque getattr(x, "__class__") / attrgetter("__subclasses__") :
            # le dunder atteint par littéral échappe au contrôle d'attribut.
            if isinstance(node.value, str) and _is_dunder(node.value):
                return f"littéral interne interdit '{node.value}'"

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
    if not isinstance(script, str) or not script.strip():
        return False, "Script vide : rien à exécuter."

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
