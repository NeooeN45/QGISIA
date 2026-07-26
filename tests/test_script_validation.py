# -*- coding: utf-8 -*-
"""Tests de la validation de sécurité des scripts PyQGIS (module pur).

La validation est passée d'une *blocklist* (tout est permis sauf ce qui est
listé) à une *allowlist* d'imports (rien n'est permis sauf ce qui est listé).
Les tests ci-dessous couvrent les contournements que la blocklist laissait
passer : pathlib, shutil, importlib, subscript de __builtins__, dunders
atteints par chaîne de caractères.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "QGISIA2"))

import script_validation as sv  # noqa: E402


def _assert_blocked(script, hint=None):
    ok, msg = sv.validate_script(script)
    assert ok is False, f"NON bloqué (faille): {script!r}"
    assert msg
    if hint:
        assert hint in msg, f"message inattendu pour {script!r}: {msg}"


# ── Scripts d'attaque historiques : doivent rester bloqués ────────────────────

ATTACKS = [
    "import os\nos.system('calc')",
    "exec = __import__('os').system\nexec('calc')",
    "().__class__.__bases__[0].__subclasses__()",
    "getattr(__builtins__, 'ev' + 'al')('1')",
    "from subprocess import Popen",
    "o = open('/etc/passwd')",
    "globals()['x'] = 1",
    "import socket",
    "eval('2+2')",
    "x = (1).__class__.__mro__",
]


def test_attacks_are_blocked():
    for script in ATTACKS:
        _assert_blocked(script)


# ── Contournements que la blocklist laissait passer ───────────────────────────

FILESYSTEM_ESCAPES = [
    "import pathlib\npathlib.Path('/etc/passwd').read_text()",
    "from pathlib import Path\nPath('C:/Windows/win.ini').read_bytes()",
    "import shutil\nshutil.rmtree('C:/')",
    "import tempfile\ntempfile.mkstemp()",
    "import glob\nglob.glob('/home/*')",
    "import io\nio.open('/etc/passwd')",
    "import fileinput\nfileinput.input('/etc/passwd')",
    "import sqlite3\nsqlite3.connect('/tmp/x.db')",
    "import zipfile\nzipfile.ZipFile('/tmp/x.zip')",
]


def test_filesystem_escapes_are_blocked():
    for script in FILESYSTEM_ESCAPES:
        _assert_blocked(script)


NETWORK_ESCAPES = [
    "import requests\nrequests.get('http://evil.com')",
    "import urllib.request\nurllib.request.urlopen('http://evil.com')",
    "from urllib import request",
    "import http.client",
    "import ftplib",
    "import asyncio",
    "import xmlrpc.client",
]


def test_network_escapes_are_blocked():
    for script in NETWORK_ESCAPES:
        _assert_blocked(script)


INDIRECT_IMPORTS = [
    "import importlib\nimportlib.import_module('os')",
    "from importlib import import_module\nimport_module('os')",
    "import runpy\nrunpy.run_module('os')",
    "import pkgutil",
    "from . import os",                     # import relatif
    "from .. import subprocess",            # import relatif remontant
    "import os.path",                       # racine interdite via sous-module
    "import xml.etree.ElementTree",         # racine non allowlistée
]


def test_indirect_imports_are_blocked():
    for script in INDIRECT_IMPORTS:
        _assert_blocked(script)


# NOTE sécurité : les chaînes ci-dessous sont des *données de test* — des
# charges utiles d'attaque que la validation doit refuser. Rien n'est exécuté
# ici : `validate_script` fait de l'analyse statique (regex + AST) et ne fait
# jamais d'eval/exec sur son entrée.
BUILTINS_ESCAPES = [
    "__builtins__['eval']('1')",
    "__builtins__[\"ex\" + \"ec\"]('x=1')",
    "b = __builtins__\nb.eval('1')",
    "print(__builtins__)",
    "__loader__.load_module('os')",
    "__spec__.loader",
]


def test_builtins_escapes_are_blocked():
    for script in BUILTINS_ESCAPES:
        _assert_blocked(script)


DUNDER_BY_STRING = [
    "getattr(layer, '__class__')",
    "import operator\noperator.attrgetter('__class__')(layer)",
    "name = '__subclasses__'",
    "x = ''.join(['__cla', 'ss__'])\n",  # concaténation : voir note ci-dessous
]


def test_dunder_reached_by_string_literal_is_blocked():
    # Les trois premiers portent un littéral dunder complet.
    for script in DUNDER_BY_STRING[:3]:
        _assert_blocked(script)


def test_split_dunder_literal_is_not_claimed_to_be_blocked():
    # Honnêteté du modèle de menace : une chaîne dunder reconstruite morceau
    # par morceau échappe à l'analyse statique. C'est le rôle du bac à sable
    # (builtins restreints, pas de getattr) de rattraper ce cas — la validation
    # statique ne prétend pas le couvrir.
    ok, _ = sv.validate_script("x = '__cla' + 'ss__'")
    assert ok is True


PROCESS_ESCAPES = [
    "import multiprocessing",
    "import threading\nthreading.Thread(target=print).start()",
    "import ctypes\nctypes.CDLL('libc.so.6')",
    "import signal",
    "import atexit",
    "import gc\ngc.get_objects()",
    "import inspect\ninspect.stack()",
    "import sys\nsys.modules",
]


def test_process_and_introspection_escapes_are_blocked():
    for script in PROCESS_ESCAPES:
        _assert_blocked(script)


# ── Scripts PyQGIS légitimes : doivent passer ─────────────────────────────────

LEGIT = [
    "layer = QgsProject.instance().mapLayersByName('test')[0]\nprint(layer.featureCount())",
    "from qgis.core import QgsVectorLayer\nimport processing\nprocessing.run('native:buffer', {})",
    "iface.messageBar().pushMessage('ok')",
    "feats = [f for f in layer.getFeatures()]\nprint(len(feats))",
    "import math\nprint(math.sqrt(2))",
    "import json\nprint(json.dumps({'a': 1}))",
    "from collections import Counter\nprint(Counter('abc'))",
    "import datetime\nprint(datetime.date.today())",
    "import statistics\nprint(statistics.mean([1, 2, 3]))",
    "from qgis.PyQt.QtCore import QVariant",
]


def test_legit_scripts_pass():
    for script in LEGIT:
        ok, msg = sv.validate_script(script)
        assert ok is True, f"Faux positif: {script!r} -> {msg}"


def test_allowlist_is_explicit_and_minimal():
    # Le durcissement doit rester une allowlist : toute racine non listée est
    # refusée par défaut. On vérifie que les racines dangereuses n'y sont pas.
    for forbidden in ("os", "sys", "subprocess", "pathlib", "shutil", "socket",
                      "importlib", "ctypes", "requests", "urllib", "io"):
        assert forbidden not in sv.ALLOWED_IMPORT_ROOTS


# ── Fonctions hallucinées ─────────────────────────────────────────────────────

def test_hallucinated_function_detected():
    ok, msg = sv.validate_script("searchCadastreParcels('75001')")
    assert ok is False
    assert "searchCadastreParcels" in msg


# ── Comportement de l'AST ─────────────────────────────────────────────────────

def test_syntax_error_is_rejected_not_silently_allowed():
    # Un script non parsable ne peut pas être analysé : il est refusé, pas
    # laissé passer « puisque Python lèvera l'erreur ». Un script inanalysable
    # ne doit jamais atteindre l'exécution.
    ok, msg = sv.validate_script("def (")
    assert ok is False
    assert msg


def test_ast_security_scan_reports_unparsable_scripts():
    assert sv.ast_security_scan("def (") is not None


def test_regex_blocklist_catches_exit():
    ok, _ = sv.validate_script("exit()")
    assert ok is False


@pytest.mark.parametrize("script", ["", "   ", "\n\n"])
def test_empty_scripts_are_rejected(script):
    ok, _ = sv.validate_script(script)
    assert ok is False
