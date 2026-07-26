# -*- coding: utf-8 -*-
"""Tests du bac à sable d'exécution hors-processus.

NOTE sécurité : toutes les chaînes de scripts ci-dessous sont des *données de
test* — des charges utiles que les barrières doivent refuser. Le processus
appelant n'exécute jamais rien : `run_sandboxed` valide statiquement puis
délègue à un sous-processus jetable.

Deux barrières sont testées SÉPARÉMENT pour prouver la défense en profondeur :

- `script_validation.validate_script` : analyse statique (testée ailleurs) ;
- `script_sandbox.spawn_sandboxed`    : sous-processus à capacités minimales,
  testé ici *sans* validation préalable, pour vérifier qu'il tient seul.

Le modèle de menace est explicite : le bac à sable n'est pas un « jail »
Python parfait (aucun ne l'est). Il garantit qu'aucun `exec` n'a lieu dans le
processus QGIS, que l'enfant n'a ni fichier ni import hors allowlist, et
qu'il est tué par l'OS au timeout. La traversée de dunders est arrêtée par la
validation statique, en amont — voir `test_dunder_traversal_*` ci-dessous.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "QGISIA2"))

import sandbox_runner  # noqa: E402
import script_sandbox as sb  # noqa: E402
import script_validation as sv  # noqa: E402


# ── Exécution nominale ────────────────────────────────────────────────────────

def test_simple_computation_succeeds():
    result = sb.run_sandboxed("print(6 * 7)", timeout_seconds=30)
    assert result["ok"] is True, result
    assert "42" in result["stdout"]
    assert result["timed_out"] is False


def test_allowed_stdlib_import_works():
    result = sb.run_sandboxed("import math\nprint(math.floor(3.7))", timeout_seconds=30)
    assert result["ok"] is True, result
    assert "3" in result["stdout"]


def test_script_exception_is_reported_not_raised():
    result = sb.run_sandboxed("raise ValueError('boom')", timeout_seconds=30)
    assert result["ok"] is False
    assert "boom" in result["traceback"]


def test_runs_in_a_separate_process():
    result = sb.run_sandboxed("print(1)", timeout_seconds=30)
    assert result["pid"] != os.getpid()
    assert result["returncode"] == 0


# ── Barrière 2 seule : capacités du sous-processus ───────────────────────────
# Ces tests appellent spawn_sandboxed directement, SANS validation statique :
# ils prouvent que le bac à sable tient même si la barrière 1 était contournée.

FILE_ACCESS_ATTEMPTS = [
    "open('/etc/passwd')",
    "open('sandbox_probe.txt', 'w').write('x')",
    "f = open('data.txt')",
]


@pytest.mark.parametrize("script", FILE_ACCESS_ATTEMPTS)
def test_sandbox_alone_refuses_file_access(script):
    result = sb.spawn_sandboxed(script, timeout_seconds=30)
    assert result["ok"] is False, f"accès fichier NON bloqué: {script!r}"


def test_sandbox_alone_writes_nothing_to_disk(tmp_path):
    probe = tmp_path / "ne-doit-pas-exister.txt"
    result = sb.spawn_sandboxed(
        f"open({str(probe)!r}, 'w').write('compromis')", timeout_seconds=30
    )
    assert result["ok"] is False
    assert not probe.exists(), "le bac à sable a écrit sur le disque"


BLOCKED_IMPORTS = [
    "import os",
    "import sys",
    "import socket",
    "import subprocess",
    "import pathlib",
    "import shutil",
    "import importlib",
    "import ctypes",
    "import urllib.request",
    "import sqlite3",
    "import threading",
    "import qgis",          # le bac à sable ne donne aucun accès au projet QGIS
    "import processing",
]


@pytest.mark.parametrize("script", BLOCKED_IMPORTS)
def test_sandbox_alone_refuses_blocked_imports(script):
    result = sb.spawn_sandboxed(script, timeout_seconds=30)
    assert result["ok"] is False, f"import NON bloqué: {script!r}"


BUILTIN_ESCAPES = [
    "eval('1+1')",
    "exec('x = 1')",
    "compile('1', '<s>', 'eval')",
    "__import__('os')",
    "getattr(int, 'mro')",
    "setattr(int, 'x', 1)",
    "globals()",
    "locals()",
    "vars()",
    "open('x')",
    "input()",
    "breakpoint()",
    "help()",
    "dir()",
]


@pytest.mark.parametrize("script", BUILTIN_ESCAPES)
def test_sandbox_alone_exposes_no_dangerous_builtin(script):
    result = sb.spawn_sandboxed(script, timeout_seconds=30)
    assert result["ok"] is False, f"builtin NON bloqué: {script!r}"


def test_sandbox_builtins_expose_no_dangerous_name():
    # `__import__` n'est pas dans cette liste : sans lui, aucune instruction
    # `import` ne fonctionne. Sa sûreté est vérifiée par les deux tests
    # suivants — présence de la version filtrée, et comportement de refus.
    forbidden = {
        "eval", "exec", "compile", "open", "getattr", "setattr",
        "delattr", "globals", "locals", "vars", "input", "breakpoint",
        "memoryview", "help", "dir", "type", "object", "super", "id",
    }
    exposed = set(sandbox_runner.build_safe_builtins())
    assert not (exposed & forbidden), sorted(exposed & forbidden)


def test_sandbox_import_is_the_guarded_one():
    assert sandbox_runner.build_safe_builtins()["__import__"] is sandbox_runner.guarded_import


def test_guarded_import_refuses_blocked_roots_and_relative_imports():
    for blocked in ("os", "sys", "socket", "subprocess", "pathlib", "qgis"):
        with pytest.raises(ImportError):
            sandbox_runner.guarded_import(blocked)
    with pytest.raises(ImportError):
        sandbox_runner.guarded_import("math", level=1)
    # Une racine autorisée passe.
    assert sandbox_runner.guarded_import("math") is not None


# ── Limite assumée du bac à sable, couverte par la barrière 1 ────────────────

def test_dunder_traversal_is_blocked_by_static_validation():
    # C'est la validation statique — pas le bac à sable — qui ferme la
    # traversée de dunders. On l'affirme explicitement pour que la limite du
    # bac à sable reste documentée et testée.
    ok, msg = sv.validate_script("().__class__.__bases__[0].__subclasses__()")
    assert ok is False
    assert msg


def test_dunder_traversal_is_not_claimed_to_be_blocked_by_the_sandbox():
    # Honnêteté du modèle de menace : le sous-processus n'interdit pas l'accès
    # aux attributs internes de Python. Sa garantie est d'être hors du
    # processus QGIS, sans capacité, et tuable. Si ce test se met à échouer,
    # c'est que le bac à sable s'est durci — mettre à jour le modèle de menace.
    result = sb.spawn_sandboxed("x = ().__class__\nprint(x)", timeout_seconds=30)
    assert result["ok"] is True


def test_full_pipeline_blocks_what_each_barrier_alone_might_miss():
    # run_sandboxed = validation + bac à sable : la traversée de dunders est
    # refusée avant même le lancement du processus.
    result = sb.run_sandboxed("().__class__.__bases__", timeout_seconds=30)
    assert result["ok"] is False
    assert result["pid"] is None, "un processus a été lancé pour un script refusé"


# ── Timeout : terminaison réelle du processus ────────────────────────────────

INFINITE_LOOPS = [
    "while True:\n    pass",
    "x = 0\nwhile True:\n    x += 1",
]


@pytest.mark.parametrize("script", INFINITE_LOOPS)
def test_infinite_loop_process_is_really_killed(script):
    started = time.monotonic()
    result = sb.spawn_sandboxed(script, timeout_seconds=2)
    elapsed = time.monotonic() - started

    assert result["timed_out"] is True
    assert result["ok"] is False
    # Le processus a été moissonné : un code de retour existe. L'ancien
    # comportement (thread daemon abandonné) n'en produisait jamais.
    assert result["returncode"] is not None
    assert result["returncode"] != 0
    assert elapsed < 30, f"terminaison trop lente ({elapsed:.1f}s)"


def test_timeout_kills_a_script_that_swallows_exceptions():
    # Terminaison faite par l'OS (SIGKILL / TerminateProcess) : un script qui
    # avale toutes les exceptions n'y survit pas.
    script = (
        "while True:\n"
        "    try:\n"
        "        pass\n"
        "    except BaseException:\n"
        "        pass\n"
    )
    result = sb.spawn_sandboxed(script, timeout_seconds=2)
    assert result["timed_out"] is True
    assert result["returncode"] is not None


def test_killed_process_is_not_left_running():
    result = sb.spawn_sandboxed("while True:\n    pass", timeout_seconds=2)
    pid = result["pid"]
    assert pid is not None
    # Le processus a été attendu (wait) : il n'est plus dans la table des
    # processus enfants. Une seconde terminaison doit être un no-op sûr.
    assert sb.process_is_finished(pid) is True


# ── Cohérence des allowlists ─────────────────────────────────────────────────

def test_sandbox_allowlist_is_the_validator_allowlist_minus_qgis():
    # Empêche la dérive entre la barrière statique et la barrière d'exécution.
    assert sandbox_runner.ALLOWED_IMPORT_ROOTS == (
        sv.ALLOWED_IMPORT_ROOTS - {"qgis", "processing"}
    )


# ── Validation en amont ──────────────────────────────────────────────────────

def test_invalid_script_never_reaches_the_subprocess():
    result = sb.run_sandboxed("import os\nos.system('calc')", timeout_seconds=30)
    assert result["ok"] is False
    assert result["pid"] is None, "un processus a été lancé pour un script refusé"


def test_empty_script_is_refused_without_spawning():
    result = sb.run_sandboxed("   ", timeout_seconds=30)
    assert result["ok"] is False
    assert result["pid"] is None
