# -*- coding: utf-8 -*-
"""
Pont Tool Calling QGIS <-> LLM.

Expose le catalogue d'outils QGIS (mcp_server.TOOL_CATALOG) au format OpenAI
'tools' pour que le LLM (via le gateway LiteLLM) puisse appeler des actions QGIS,
parse les tool_calls renvoyes par le modele, et execute l'appel en routant vers
le bridge HTTP QGIS (reutilise le dispatch MCP existant : une seule source de verite).
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, List, Optional

import uuid

# Sessions d'agent en pause (ask_user) : {session_id -> {state + timestamp}}
_AGENT_SESSIONS: dict[str, dict] = {}
_SESSION_TTL_SECONDS = 300  # 5 minutes


def _cleanup_stale_sessions() -> None:
    """Supprime les sessions expirées (> 5 min)."""
    now = time.time()
    expired = [sid for sid, state in _AGENT_SESSIONS.items()
               if now - state.get("_created_at", 0) > _SESSION_TTL_SECONDS]
    for sid in expired:
        _AGENT_SESSIONS.pop(sid, None)

try:
    from mcp_server import (
        TOOL_CATALOG,
        McpToolSpec,
        dispatch_tool_call,
        DEFAULT_BRIDGE_URL,
    )
except ImportError:  # pragma: no cover - fallback import package
    from .mcp_server import (  # type: ignore
        TOOL_CATALOG,
        McpToolSpec,
        dispatch_tool_call,
        DEFAULT_BRIDGE_URL,
    )

try:
    from native_tools import (
        native_tool_names,
        execute_native_tool,
        to_openai_tools as _native_openai_tools,
    )
except ImportError:  # pragma: no cover
    from .native_tools import (  # type: ignore
        native_tool_names,
        execute_native_tool,
        to_openai_tools as _native_openai_tools,
    )


def to_openai_tools(catalog: Optional[List[McpToolSpec]] = None) -> List[dict]:
    """
    Convertit le catalogue d'outils au format OpenAI 'tools' (function calling).
    Par defaut : outils QGIS (bridge) + outils natifs (web/geo). Si `catalog` est
    fourni explicitement, on ne renvoie que celui-ci (sans les natifs).
    """
    specs = catalog if catalog is not None else TOOL_CATALOG
    tools = [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.input_schema,
            },
        }
        for spec in specs
    ]
    if catalog is None:
        tools = tools + _native_openai_tools()
    return tools


def tool_names(catalog: Optional[List[McpToolSpec]] = None) -> List[str]:
    """Liste des noms d'outils disponibles."""
    specs = catalog if catalog is not None else TOOL_CATALOG
    return [s.name for s in specs]


def parse_tool_calls(response: dict) -> List[dict]:
    """
    Extrait les tool_calls d'une reponse OpenAI ChatCompletion.
    Retourne une liste [{id, name, arguments(dict)}], vide si aucun appel.
    """
    try:
        message = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return []

    calls = message.get("tool_calls") or []
    parsed: List[dict] = []
    for call in calls:
        fn = call.get("function", {}) if isinstance(call, dict) else {}
        raw_args = fn.get("arguments", "{}")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
        except (json.JSONDecodeError, TypeError):
            args = {}
        parsed.append({
            "id": call.get("id", "") if isinstance(call, dict) else "",
            "name": fn.get("name", ""),
            "arguments": args,
        })
    return parsed


def execute_tool_call(
    name: str,
    arguments: dict,
    *,
    bridge_url: str = DEFAULT_BRIDGE_URL,
    http_client: Any = None,
) -> str:
    """
    Execute (synchrone) un appel d'outil en routant vers le bridge QGIS via le
    dispatch MCP. `http_client` permet l'injection pour les tests.
    """
    return asyncio.run(
        dispatch_tool_call(
            name,
            arguments or {},
            bridge_url=bridge_url,
            http_client=http_client,
        )
    )


# Outils executant du code/SQL arbitraire : a passer au crible des guardrails.
_CODE_EXEC_TOOLS = {"runScript", "runScriptDirect", "runScriptDetailed"}


def safety_check(name: str, arguments: dict, auto_mode: bool = False) -> tuple:
    """
    Garde-fou avant execution d'un outil. Retourne (allowed: bool, reason: str).
    Seuls les outils executant du code PyQGIS arbitraire sont audites via
    agent_guardrails (BLOCK toujours refuse ; CONFIRM refuse hors mode auto).
    """
    if name not in _CODE_EXEC_TOOLS:
        return True, ""
    code = (arguments or {}).get("script") or (arguments or {}).get("code") or ""
    try:
        try:
            from agent_guardrails import AgentGuardrails  # type: ignore
        except ImportError:
            from .agent_guardrails import AgentGuardrails  # type: ignore
    except Exception:  # noqa: BLE001 - garde-fou indispo : best effort, on n'execute pas a l'aveugle
        return False, "Module de securite indisponible : execution de code bloquee."
    result = AgentGuardrails(auto_mode=auto_mode).check_pyqgis_code(code)
    if getattr(result, "passed", False):
        return True, ""
    return False, getattr(result, "message", "") or "Action bloquee par la securite."


DEFAULT_AGENT_SYSTEM = (
    "Tu es QGISIA+, un agent cartographe SIG autonome integre dans QGIS, aussi "
    "competent et proactif qu'un expert humain. Ta mission : accomplir REELLEMENT "
    "la demande de l'utilisateur en agissant sur le projet QGIS, pas seulement en "
    "decrivant quoi faire.\n\n"
    "METHODE (boucle autonome) :\n"
    "1. PLANIFIE brievement (1-4 etapes) l'objectif et les outils a enchainer.\n"
    "2. ANCRE-TOI sur le reel : commence par getLayersList pour connaitre les "
    "couches existantes ; n'invente jamais un identifiant de couche.\n"
    "3. GEOCODE les lieux cites (ville, commune, adresse) avec l'outil geocode "
    "pour obtenir le 'bbox' du lieu AVANT toute action spatiale.\n"
    "4. AGIS en enchainant les outils : ajoute des fonds de carte / sources de "
    "donnees (OSM, IGN, satellite), charge des donnees, calcule (indices spectraux, "
    "terrain, statistiques zonales, buffers, classifications), STYLE les couches "
    "avec une symbologie lisible. Pour CADRER la vue sur un lieu, appelle "
    "setMapExtent(bbox) avec le bbox renvoye par geocode — n'utilise JAMAIS "
    "zoomToLayer sur un fond mondial (OSM) car cela affiche le monde entier.\n"
    "5. POUR TOUTE DEMANDE VISUELLE (\"cree\", \"affiche\", \"cartographie\", "
    "\"surprends-moi\") : produis un resultat visible — couche(s) ajoutee(s) et "
    "stylee(s), vue cadree (zoomToLayer/renderMapView), et si pertinent une planche "
    "(exportPrintLayout). Ne te contente jamais d'expliquer.\n"
    "6. ORGANISE comme un pro : donne aux couches un nom CLAIR et descriptif via "
    "renameLayer (ex. 'Fond OpenStreetMap', 'NDVI 2024' — jamais le seul nom du "
    "lieu), puis range-les dans des groupes nommes via setLayerGroup "
    "('Fonds de carte', 'Donnees', 'Analyses', 'Resultats'...). L'arbre des couches "
    "doit etre propre et lisible a la fin.\n"
    "7. AUTO-CORRIGE : si un outil echoue, lis l'erreur, adapte les parametres et "
    "reessaie une autre approche au lieu d'abandonner.\n"
    "8. DEMANDE (ask_user) uniquement en cas d'ambiguite reelle bloquante "
    "(ex. plusieurs interpretations incompatibles). Sinon, prends l'initiative avec "
    "des choix par defaut raisonnables et explique-les.\n\n"
    "EFFICACITE : va a l'essentiel. Des que l'objectif demande est atteint "
    "(ex. la carte est ajoutee, stylee et cadree), ARRETE d'appeler des outils et "
    "donne ta reponse finale. N'enchaine pas d'actions superflues, ne repete pas un "
    "outil deja reussi : vise 3 a 8 appels d'outils pour une demande simple.\n\n"
    "STYLE DE REPONSE : agis d'abord, puis termine en francais par un resume clair "
    "de CE QUI A ETE FAIT (couches ajoutees, traitements, rendu) et 1-2 suggestions "
    "de suite pertinentes. Sois concis, concret, oriente resultat."
)


def run_tool_loop(
    messages: List[dict],
    api_keys: dict,
    *,
    model: str = "smart-default",
    max_iters: int = 30,
    auto_mode: bool = False,
    system: Optional[str] = None,
    bridge_url: str = DEFAULT_BRIDGE_URL,
    chat_fn: Any = None,
    http_client: Any = None,
    native_get_json: Any = None,
    on_event: Optional[Any] = None,  # Callable[[dict], None] — optionnel, retro-compatible
    _start_iteration: int = 1,  # Privé: pour resume_tool_loop après ask_user
) -> dict:
    """
    Boucle agentique de tool calling :
      LLM -> tool_calls -> execution bridge QGIS -> resultats -> LLM -> ... -> reponse.

    Retourne {content, trace[], iterations}. `chat_fn` et `http_client` sont
    injectables pour les tests (par defaut : gateway LiteLLM + httpx).
    """
    if chat_fn is None:  # pragma: no cover - chemin reel (gateway)
        try:
            from llm_gateway import chat as chat_fn  # type: ignore
        except ImportError:
            from .llm_gateway import chat as chat_fn  # type: ignore

    tools = to_openai_tools()
    msgs: List[dict] = list(messages)
    # Amorce de planification/grounding si aucun message systeme n'est fourni.
    if not any(m.get("role") == "system" for m in msgs):
        msgs.insert(0, {"role": "system", "content": system or DEFAULT_AGENT_SYSTEM})
    trace: List[dict] = []

    def _emit(event: dict) -> None:
        """Emet un evenement SSE si le callback est fourni (sans exception)."""
        if on_event is not None:
            try:
                on_event(event)
            except Exception:  # noqa: BLE001
                pass

    for iteration in range(_start_iteration, _start_iteration + max_iters):
        _emit({"type": "iteration", "i": iteration})
        response = chat_fn(
            model=model,
            messages=msgs,
            api_keys=api_keys,
            tools=tools,
            stream=False,
        )
        message = response["choices"][0]["message"]
        calls = parse_tool_calls(response)

        if not calls:
            return {
                "content": message.get("content") or "",
                "trace": trace,
                "iterations": iteration,
            }

        # Rejoue le message assistant (avec ses tool_calls) puis les resultats d'outils.
        msgs.append({
            "role": "assistant",
            "content": message.get("content"),
            "tool_calls": message.get("tool_calls"),
        })
        for call in calls:
            _emit({"type": "tool_start", "tool": call["name"], "arguments": call["arguments"]})
            allowed, reason = safety_check(call["name"], call["arguments"], auto_mode)
            if not allowed:
                result = f"BLOQUE PAR SECURITE: {reason}"
                trace.append({
                    "tool": call["name"],
                    "arguments": call["arguments"],
                    "result": result,
                    "blocked": True,
                })
                _emit({"type": "tool_result", "tool": call["name"], "result": result[:300], "blocked": True})
            else:
                try:
                    if call["name"] in native_tool_names():
                        # Outil natif (web/geo) : execution en-process, hors bridge QGIS.
                        result = execute_native_tool(
                            call["name"], call["arguments"], get_json=native_get_json,
                        )
                    else:
                        result = execute_tool_call(
                            call["name"], call["arguments"],
                            bridge_url=bridge_url, http_client=http_client,
                        )
                except Exception as exc:  # noqa: BLE001
                    result = f"Erreur outil {call['name']}: {exc}"
                trace.append({
                    "tool": call["name"],
                    "arguments": call["arguments"],
                    "result": result[:500],
                })
                _emit({"type": "tool_result", "tool": call["name"], "result": result[:300], "blocked": False})

                # Detection pause ask_user
                if call["name"] == "ask_user":
                    try:
                        parsed = json.loads(result) if isinstance(result, str) else result
                        if isinstance(parsed, dict) and parsed.get("_ask_user_pause"):
                            session_id = str(uuid.uuid4())
                            _AGENT_SESSIONS[session_id] = {
                                "messages": list(msgs),
                                "iteration": iteration,
                                "max_iters": max_iters,
                                "model": model,
                                "api_keys": api_keys,
                                "system": system,
                                "bridge_url": bridge_url,
                                "trace": list(trace),
                                "chat_fn": chat_fn,
                                "native_get_json": native_get_json,
                                "http_client": http_client,
                                "auto_mode": auto_mode,
                                "on_event": on_event,
                                "pending_tool_call_id": call["id"],
                                "pending_tool_name": call["name"],
                                "_created_at": time.time(),  # TTL tracking
                            }
                            _emit({"type": "ask_user", "session_id": session_id,
                                   "question": parsed["question"], "options": parsed["options"]})
                            return {
                                "content": "",
                                "trace": trace,
                                "paused": True,
                                "session_id": session_id,
                                "question": parsed["question"],
                                "options": parsed["options"],
                                "iterations": iteration,
                            }
                    except (json.JSONDecodeError, TypeError):
                        pass

            msgs.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "name": call["name"],
                "content": result,
            })

    return {
        "content": "Limite d'iterations d'outils atteinte sans reponse finale.",
        "trace": trace,
        "iterations": max_iters,
    }



def resume_tool_loop(session_id: str, selected_option: str) -> dict:
    """Reprend une boucle agentique interrompue par ask_user.

    Args:
        session_id: ID de session stockee lors de la pause.
        selected_option: Option choisie par l'utilisateur.

    Returns:
        {content, trace, iterations} ou {error} si session inconnue.
    """
    _cleanup_stale_sessions()  # Nettoyer les sessions expirées (TTL 5 min)
    state = _AGENT_SESSIONS.pop(session_id, None)
    if state is None:
        return {"error": f"Session inconnue ou expiree: {session_id}"}

    msgs = state["messages"]
    trace = state["trace"]

    # Injecte la reponse de l'utilisateur comme resultat d'outil
    msgs.append({
        "role": "tool",
        "tool_call_id": state["pending_tool_call_id"],
        "name": state["pending_tool_name"],
        "content": json.dumps({"selected_option": selected_option}),
    })
    trace.append({
        "tool": state["pending_tool_name"],
        "result": f"Utilisateur a choisi: {selected_option}",
    })

    def _emit(event: dict) -> None:
        on_event = state.get("on_event")
        if on_event is not None:
            try:
                on_event(event)
            except Exception:  # noqa: BLE001
                pass

    _emit({"type": "tool_result", "tool": state["pending_tool_name"],
           "result": f"Utilisateur a choisi: {selected_option}", "blocked": False})

    # Calculer les itérations restantes (pas recommencer de zéro)
    current_iteration = state.get("iteration", 0)
    original_max = state["max_iters"]
    remaining_iters = max(1, original_max - current_iteration)
    next_start_iter = current_iteration + 1

    return run_tool_loop(
        msgs,
        state["api_keys"],
        model=state["model"],
        max_iters=remaining_iters,  # Itérations restantes, pas le total
        auto_mode=state["auto_mode"],
        system=state["system"],
        bridge_url=state["bridge_url"],
        chat_fn=state["chat_fn"],
        http_client=state["http_client"],
        native_get_json=state.get("native_get_json"),
        on_event=state.get("on_event"),
        _start_iteration=next_start_iter,  # Reprendre à l'itération suivante
    )
