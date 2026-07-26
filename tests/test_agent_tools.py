# -*- coding: utf-8 -*-
"""Tests du pont Tool Calling QGIS <-> LLM (agent_tools)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "QGISIA2" / "vendor"))
sys.path.insert(0, str(ROOT / "QGISIA2"))

import agent_tools as at  # noqa: E402
import bridge_http as bh  # noqa: E402


def test_to_openai_tools_shape():
    tools = at.to_openai_tools()
    assert len(tools) >= 8
    for t in tools:
        assert t["type"] == "function"
        fn = t["function"]
        assert isinstance(fn["name"], str) and fn["name"]
        assert isinstance(fn["description"], str)
        assert fn["parameters"]["type"] == "object"


def test_to_openai_tools_includes_native_and_qgis():
    names = [t["function"]["name"] for t in at.to_openai_tools()]
    assert "geocode" in names      # outil natif (web/geo)
    assert "getLayersList" in names  # outil QGIS (bridge)


def test_run_tool_loop_dispatches_native_tool_without_bridge():
    import json as _json
    state = {"i": 0}

    def fake_chat(model, messages, api_keys, tools=None, stream=False, **kw):
        state["i"] += 1
        if state["i"] == 1:
            return {"choices": [{"message": {
                "content": None,
                "tool_calls": [{
                    "id": "g1",
                    "function": {"name": "geocode", "arguments": _json.dumps({"query": "Toulouse"})},
                }],
            }}]}
        return {"choices": [{"message": {"content": "Toulouse se situe a 43.6, 1.44."}}]}

    def fake_get(url, params, timeout=20):
        return [{"display_name": "Toulouse, France", "lat": "43.6", "lon": "1.44"}]

    bridge = _FakeClient("NE DOIT PAS ETRE APPELE")
    res = at.run_tool_loop(
        [{"role": "user", "content": "ou se trouve Toulouse ?"}],
        api_keys={},
        chat_fn=fake_chat,
        http_client=bridge,
        native_get_json=fake_get,
        max_iters=2,
    )
    assert res["trace"][0]["tool"] == "geocode"
    assert "Toulouse" in res["trace"][0]["result"]
    assert bridge.calls == []  # outil natif -> aucun appel au bridge QGIS


def test_tool_names_include_core_map_ops():
    names = at.tool_names()
    for expected in ("getLayersList", "setLayerVisibility", "zoomToLayer",
                     "filterLayer", "reprojectLayer", "setLayerOpacity"):
        assert expected in names


def test_parse_tool_calls_extracts_name_and_args():
    response = {
        "choices": [{
            "message": {
                "tool_calls": [{
                    "id": "call_1",
                    "function": {
                        "name": "zoomToLayer",
                        "arguments": '{"layerId": "layer_42"}',
                    },
                }]
            }
        }]
    }
    calls = at.parse_tool_calls(response)
    assert len(calls) == 1
    assert calls[0]["name"] == "zoomToLayer"
    assert calls[0]["arguments"] == {"layerId": "layer_42"}
    assert calls[0]["id"] == "call_1"


def test_parse_tool_calls_empty_when_none():
    assert at.parse_tool_calls({"choices": [{"message": {"content": "hello"}}]}) == []
    assert at.parse_tool_calls({}) == []


def test_parse_tool_calls_tolerates_bad_json():
    response = {"choices": [{"message": {"tool_calls": [
        {"id": "x", "function": {"name": "filterLayer", "arguments": "{not json"}}
    ]}}]}
    calls = at.parse_tool_calls(response)
    assert calls[0]["name"] == "filterLayer"
    assert calls[0]["arguments"] == {}


class _FakeResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class _FakeClient:
    def __init__(self, text="OK"):
        self.text = text
        self.calls = []
        self.headers = []

    async def post(self, url, json, headers=None):  # noqa: A002 - signature httpx
        self.calls.append((url, json))
        self.headers.append(headers or {})
        return _FakeResp(self.text)


def test_execute_tool_call_routes_to_bridge():
    fake = _FakeClient("zoom effectue")
    out = at.execute_tool_call(
        "zoomToLayer",
        {"layerId": "layer_1"},
        bridge_url="http://localhost:8157",
        http_client=fake,
    )
    assert out == "zoom effectue"
    url, payload = fake.calls[0]
    assert url == "http://localhost:8157/api/qgis/zoomToLayer"
    assert payload == {"layerId": "layer_1"}


def test_execute_tool_call_authenticates_against_the_bridge():
    # Le bridge exige un jeton, une origine locale et application/json. Si
    # l'agent ne les envoie pas, chaque appel d'outil part en 403 puis 401 —
    # c'est exactement la regression que ce test verrouille.
    bh.set_active_token("JETON-DE-TEST")
    try:
        fake = _FakeClient("ok")
        at.execute_tool_call(
            "zoomToLayer",
            {"layerId": "layer_1"},
            bridge_url="http://localhost:8157",
            http_client=fake,
        )
        sent = fake.headers[0]
        assert sent[bh.TOKEN_HEADER] == "JETON-DE-TEST"
        assert sent["Origin"] == "http://localhost:8157"
        assert sent["Content-Type"] == "application/json"
    finally:
        bh.set_active_token(None)


def test_execute_tool_call_unknown_tool_raises():
    import pytest
    with pytest.raises(ValueError):
        at.execute_tool_call("doesNotExist", {}, http_client=_FakeClient())


def test_run_tool_loop_executes_tool_then_answers():
    state = {"i": 0}

    def fake_chat(model, messages, api_keys, tools=None, stream=False, **kw):
        state["i"] += 1
        if state["i"] == 1:
            # 1er tour : le LLM demande l'outil zoomToLayer
            return {"choices": [{"message": {
                "content": None,
                "tool_calls": [{
                    "id": "c1",
                    "function": {"name": "zoomToLayer", "arguments": '{"layerId": "L1"}'},
                }],
            }}]}
        # 2e tour : le LLM repond apres avoir vu le resultat de l'outil
        return {"choices": [{"message": {"content": "J'ai zoome sur la couche L1."}}]}

    fake_http = _FakeClient("zoom ok")
    res = at.run_tool_loop(
        [{"role": "user", "content": "zoom sur L1"}],
        api_keys={},
        chat_fn=fake_chat,
        http_client=fake_http,
        bridge_url="http://localhost:8157",
    )
    assert "zoome" in res["content"]
    assert res["iterations"] == 2
    assert res["trace"][0]["tool"] == "zoomToLayer"
    assert res["trace"][0]["arguments"] == {"layerId": "L1"}
    assert res["trace"][0]["result"] == "zoom ok"


def test_run_tool_loop_no_tools_returns_directly():
    def fake_chat(model, messages, api_keys, tools=None, stream=False, **kw):
        return {"choices": [{"message": {"content": "Reponse directe sans outil."}}]}

    res = at.run_tool_loop(
        [{"role": "user", "content": "bonjour"}],
        api_keys={},
        chat_fn=fake_chat,
    )
    assert res["content"] == "Reponse directe sans outil."
    assert res["iterations"] == 1
    assert res["trace"] == []


def test_safety_check_allows_non_code_tools():
    allowed, _ = at.safety_check("zoomToLayer", {"layerId": "L1"})
    assert allowed is True


def test_safety_check_blocks_drop_table_even_in_auto():
    args = {"script": "db.execute('DROP TABLE parcelles')"}
    assert at.safety_check("runScript", args, auto_mode=False)[0] is False
    assert at.safety_check("runScript", args, auto_mode=True)[0] is False


def test_safety_check_confirm_blocked_unless_auto():
    args = {"script": "layer.startEditing()\nlayer.deleteFeatures([1,2,3])\nlayer.commitChanges()"}
    assert at.safety_check("runScript", args, auto_mode=False)[0] is False
    # En mode auto, une action CONFIRM (non critique) passe.
    assert at.safety_check("runScript", args, auto_mode=True)[0] is True


def test_safety_check_allows_safe_script():
    assert at.safety_check("runScript", {"script": "print(iface.activeLayer().name())"})[0] is True


def test_run_tool_loop_blocks_dangerous_script_without_calling_bridge():
    import json as _json
    state = {"i": 0}

    def fake_chat(model, messages, api_keys, tools=None, stream=False, **kw):
        state["i"] += 1
        if state["i"] == 1:
            return {"choices": [{"message": {
                "content": None,
                "tool_calls": [{
                    "id": "c1",
                    "function": {
                        "name": "runScript",
                        "arguments": _json.dumps({"script": "db.execute('DROP TABLE parcelles')"}),
                    },
                }],
            }}]}
        return {"choices": [{"message": {"content": "Action refusee pour raison de securite."}}]}

    bridge = _FakeClient("NE DOIT PAS ETRE APPELE")
    res = at.run_tool_loop(
        [{"role": "user", "content": "supprime la table parcelles"}],
        api_keys={},
        chat_fn=fake_chat,
        http_client=bridge,
        auto_mode=False,
        max_iters=2,
    )
    assert res["trace"][0].get("blocked") is True
    assert "SECURITE" in res["trace"][0]["result"]
    assert bridge.calls == []  # le bridge QGIS n'a jamais ete appele


def test_run_tool_loop_prepends_default_system_prompt():
    captured = {}

    def fake_chat(model, messages, api_keys, tools=None, stream=False, **kw):
        captured["messages"] = list(messages)
        return {"choices": [{"message": {"content": "ok"}}]}

    at.run_tool_loop([{"role": "user", "content": "liste les couches"}], {}, chat_fn=fake_chat)
    assert captured["messages"][0]["role"] == "system"
    assert "agent SIG" in captured["messages"][0]["content"]


def test_run_tool_loop_respects_provided_system_message():
    captured = {}

    def fake_chat(model, messages, api_keys, tools=None, stream=False, **kw):
        captured["messages"] = list(messages)
        return {"choices": [{"message": {"content": "ok"}}]}

    at.run_tool_loop(
        [{"role": "system", "content": "SYSTEME PERSONNALISE"},
         {"role": "user", "content": "x"}],
        {}, chat_fn=fake_chat,
    )
    assert captured["messages"][0]["content"] == "SYSTEME PERSONNALISE"


def test_run_tool_loop_respects_max_iters():
    def always_calls(model, messages, api_keys, tools=None, stream=False, **kw):
        return {"choices": [{"message": {
            "content": None,
            "tool_calls": [{
                "id": "c", "function": {"name": "getLayersList", "arguments": "{}"},
            }],
        }}]}

    res = at.run_tool_loop(
        [{"role": "user", "content": "boucle"}],
        api_keys={},
        chat_fn=always_calls,
        http_client=_FakeClient("[]"),
        max_iters=3,
    )
    assert res["iterations"] == 3
    assert "Limite" in res["content"]
