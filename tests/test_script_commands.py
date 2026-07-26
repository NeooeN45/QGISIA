# -*- coding: utf-8 -*-
"""Tests de l'API de commandes autorisées (remplace l'exec pour les mutations).

Le principe : un LLM ne fournit plus du code Python à exécuter pour agir sur
le projet QGIS, mais une liste de commandes déclaratives. Chaque commande est
résolue dans une table figée (nom -> méthode du bridge), et chaque paramètre
est validé en nom et en type. Tout ce qui n'est pas explicitement autorisé est
refusé — il n'y a aucun chemin d'échappement vers du code arbitraire.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "QGISIA2"))

import script_commands as sc  # noqa: E402


# ── Table des commandes ───────────────────────────────────────────────────────

def test_command_table_is_not_empty():
    assert sc.list_commands()


def test_no_script_execution_command_is_reachable():
    # L'API de commandes ne doit JAMAIS exposer une exécution de code.
    for name in sc.list_commands():
        lowered = name.lower()
        assert "script" not in lowered, f"commande d'exécution exposée: {name}"
        assert "exec" not in lowered
        assert "eval" not in lowered


def test_no_command_maps_to_a_script_bridge_method():
    forbidden = {"runScript", "runScriptDirect", "runScriptDetailed"}
    for name in sc.list_commands():
        method = sc.bridge_method_for(name)
        assert method not in forbidden, f"{name} -> {method}"


# ── Résolution et validation ──────────────────────────────────────────────────

def test_valid_command_resolves_to_ordered_bridge_arguments():
    ok, error, call = sc.validate_command(
        "setLayerVisibility", {"layerId": "abc", "visible": False}
    )
    assert ok is True, error
    assert call == ("setLayerVisibility", ("abc", False))


def test_argument_order_follows_the_spec_not_the_payload():
    # L'ordre des clés du payload ne doit pas influencer l'ordre des arguments.
    ok, _, call = sc.validate_command(
        "filterLayer", {"subsetString": "pop > 10", "layerId": "L1"}
    )
    assert ok is True
    assert call == ("filterLayer", ("L1", "pop > 10"))


def test_unknown_command_is_refused():
    ok, error, call = sc.validate_command("dropDatabase", {})
    assert ok is False
    assert call is None
    assert "dropDatabase" in error


def test_unknown_parameter_is_refused_not_ignored():
    ok, error, _ = sc.validate_command(
        "zoomToLayer", {"layerId": "L1", "callback": "evil"}
    )
    assert ok is False
    assert "callback" in error


def test_missing_required_parameter_is_refused():
    ok, error, _ = sc.validate_command("setLayerVisibility", {"visible": True})
    assert ok is False
    assert "layerId" in error


def test_optional_parameter_falls_back_to_its_default():
    ok, error, call = sc.validate_command("setLayerVisibility", {"layerId": "L1"})
    assert ok is True, error
    assert call == ("setLayerVisibility", ("L1", True))


# ── Typage strict ─────────────────────────────────────────────────────────────

WRONG_TYPES = [
    ("setLayerVisibility", {"layerId": "L1", "visible": "true"}),   # str != bool
    ("setLayerVisibility", {"layerId": 42, "visible": True}),       # int != str
    ("setLayerOpacity", {"layerId": "L1", "opacity": "0.5"}),       # str != float
    ("zoomToLayer", {"layerId": ["L1"]}),                           # list != str
    ("zoomToLayer", {"layerId": None}),                             # None != str
    ("renameLayer", {"layerId": "L1", "name": {"a": 1}}),           # dict != str
]


@pytest.mark.parametrize("name,params", WRONG_TYPES)
def test_wrong_parameter_type_is_refused(name, params):
    ok, error, _ = sc.validate_command(name, params)
    assert ok is False, f"type non contrôlé: {name} {params}"
    assert error


def test_bool_is_not_accepted_where_a_number_is_expected():
    # bool est un sous-type de int en Python : le contrôle doit l'exclure.
    ok, _, _ = sc.validate_command("setLayerOpacity", {"layerId": "L1", "opacity": True})
    assert ok is False


def test_int_is_accepted_where_a_float_is_expected():
    ok, error, call = sc.validate_command("setLayerOpacity", {"layerId": "L1", "opacity": 1})
    assert ok is True, error
    assert call == ("setLayerOpacity", ("L1", 1.0))


def test_oversized_string_is_refused():
    ok, error, _ = sc.validate_command(
        "renameLayer", {"layerId": "L1", "name": "x" * (sc.MAX_STRING_LENGTH + 1)}
    )
    assert ok is False
    assert error


# ── Lots de commandes ─────────────────────────────────────────────────────────

def test_valid_batch_resolves_every_command():
    ok, error, calls = sc.validate_command_batch([
        {"command": "zoomToLayer", "params": {"layerId": "L1"}},
        {"command": "setLayerOpacity", "params": {"layerId": "L1", "opacity": 0.5}},
    ])
    assert ok is True, error
    assert calls == [
        ("zoomToLayer", ("L1",)),
        ("setLayerOpacity", ("L1", 0.5)),
    ]


def test_batch_fails_entirely_if_one_command_is_invalid():
    # Pas d'exécution partielle : une commande refusée invalide tout le lot.
    ok, error, calls = sc.validate_command_batch([
        {"command": "zoomToLayer", "params": {"layerId": "L1"}},
        {"command": "runScript", "params": {"script": "import os"}},
    ])
    assert ok is False
    assert calls is None
    assert "runScript" in error


def test_batch_length_is_bounded():
    payload = [{"command": "zoomToLayer", "params": {"layerId": "L1"}}] * (
        sc.MAX_BATCH_COMMANDS + 1
    )
    ok, error, _ = sc.validate_command_batch(payload)
    assert ok is False
    assert error


@pytest.mark.parametrize("payload", [None, {}, "zoomToLayer", [None], [[]], [{"params": {}}]])
def test_malformed_batch_payloads_are_refused(payload):
    ok, error, calls = sc.validate_command_batch(payload)
    assert ok is False
    assert calls is None
    assert error


def test_empty_batch_is_refused():
    ok, error, _ = sc.validate_command_batch([])
    assert ok is False
    assert error


# ── Traçabilité ───────────────────────────────────────────────────────────────

def test_filesystem_writing_commands_are_declared():
    # Les commandes qui écrivent sur le disque sont explicitement marquées,
    # pour que la revue de sécurité et l'UI puissent les traiter à part.
    writers = set(sc.filesystem_writing_commands())
    assert "saveVectorLayer" in writers
    assert "zoomToLayer" not in writers
    assert writers <= set(sc.list_commands())
