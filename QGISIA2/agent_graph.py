# -*- coding: utf-8 -*-
"""
QGISIA+ Agent Graph (Sprint 7) — Orchestration LangGraph.

Graph d'agent qui implemente explicitement les 4 phases du raisonnement
structure : PLAN -> EXECUTE -> VERIFY -> REPORT, avec boucle de retour
PLAN si VERIFY echoue.

Architecture (DAG conditionnel) :

         ┌────────┐
         │  PLAN  │
         └───┬────┘
             v
         ┌────────┐
         │EXECUTE │
         └───┬────┘
             v
         ┌────────┐    KO   ┌──────┐
         │ VERIFY │ ──────> │ PLAN │  (max 3 tentatives)
         └───┬────┘         └──────┘
             v OK
         ┌────────┐
         │ REPORT │  (terminal)
         └────────┘

Le scaffold fonctionne en deux modes :
    1. Mode LangGraph natif (si langgraph installe) : graph compile + invoke
    2. Mode fallback sequentiel : exec linear pure Python (pour tests/CI)

Dependances optionnelles :
    pip install langgraph langchain-core
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional, TypedDict

logger = logging.getLogger(__name__)

MAX_REPLAN_ATTEMPTS = 3


# ─── State du graph (TypedDict compatible LangGraph) ──────────────────────────


class AgentState(TypedDict, total=False):
    """
    State partage entre les nodes du graph.

    Champs :
        user_request   : message utilisateur initial
        layer_context  : contexte des couches QGIS
        plan           : plan d'execution genere par le node PLAN
        execution_log  : trace des appels d'outils du node EXECUTE
        verify_passed  : bool resultant du node VERIFY
        verify_message : detail du verdict (raison si echec)
        report         : reponse finale assembled par REPORT
        replan_count   : nombre de re-planifications effectuees
        error          : eventuelle erreur fatale
    """
    user_request: str
    layer_context: str
    plan: list[str]
    execution_log: list[str]
    verify_passed: bool
    verify_message: str
    report: str
    replan_count: int
    error: Optional[str]


# ─── Node implementations (pure functions) ────────────────────────────────────


def init_state(user_request: str, layer_context: str = "") -> AgentState:
    """Cree un state initial valide."""
    return {
        "user_request": user_request,
        "layer_context": layer_context,
        "plan": [],
        "execution_log": [],
        "verify_passed": False,
        "verify_message": "",
        "report": "",
        "replan_count": 0,
        "error": None,
    }


@dataclass
class NodeRegistry:
    """
    Conteneur pour les implementations des nodes. Permet l'injection des
    callables LLM dans les tests et la production.
    """
    plan_fn: Callable[[AgentState], AgentState]
    execute_fn: Callable[[AgentState], AgentState]
    verify_fn: Callable[[AgentState], AgentState]
    report_fn: Callable[[AgentState], AgentState]


def _default_plan_node(state: AgentState) -> AgentState:
    """Node PLAN par defaut : echo du user request comme plan trivial."""
    request = state.get("user_request", "")
    return {
        **state,
        "plan": [f"Analyser la demande : {request}"],
    }


def _default_execute_node(state: AgentState) -> AgentState:
    """Node EXECUTE par defaut : simulation d'execution sans tool reel."""
    plan = state.get("plan", [])
    log = [f"OK: {step}" for step in plan]
    return {
        **state,
        "execution_log": log,
    }


def _default_verify_node(state: AgentState) -> AgentState:
    """
    Node VERIFY par defaut : verifie qu'au moins une etape a ete loggee
    et qu'aucune trace ne contient ECHEC ou ERREUR.
    """
    log = state.get("execution_log", [])
    if not log:
        return {**state, "verify_passed": False, "verify_message": "Execution vide"}
    failed = next((l for l in log if "ECHEC" in l.upper() or "ERREUR" in l.upper()), None)
    if failed:
        return {**state, "verify_passed": False, "verify_message": f"Etape KO : {failed}"}
    return {**state, "verify_passed": True, "verify_message": "Toutes etapes OK"}


def _default_report_node(state: AgentState) -> AgentState:
    """Node REPORT par defaut : resume textuel structure du run."""
    plan = state.get("plan", [])
    log = state.get("execution_log", [])
    verify_msg = state.get("verify_message", "")
    report = (
        f"[PLAN]\n{chr(10).join(f'- {p}' for p in plan)}\n\n"
        f"[EXECUTE]\n{chr(10).join(f'- {l}' for l in log)}\n\n"
        f"[VERIFY] {verify_msg}\n\n"
        f"[REPORT] Run termine en {state.get('replan_count', 0) + 1} tentative(s)."
    )
    return {**state, "report": report}


DEFAULT_REGISTRY = NodeRegistry(
    plan_fn=_default_plan_node,
    execute_fn=_default_execute_node,
    verify_fn=_default_verify_node,
    report_fn=_default_report_node,
)


# ─── Routing logic (edge conditionnel verify -> plan|report) ──────────────────


def route_after_verify(state: AgentState) -> Literal["plan", "report"]:
    """
    Edge conditionnel apres VERIFY :
        - verify_passed = True              -> 'report' (terminal)
        - verify_passed = False et replan < MAX -> 'plan' (re-iteration)
        - sinon                             -> 'report' (limite atteinte, on
                                                rapporte l'echec)
    """
    if state.get("verify_passed"):
        return "report"
    if state.get("replan_count", 0) < MAX_REPLAN_ATTEMPTS - 1:
        return "plan"
    return "report"


def increment_replan(state: AgentState) -> AgentState:
    """Helper : utilise par le routing pour bumper le compteur."""
    return {**state, "replan_count": state.get("replan_count", 0) + 1}


# ─── Mode fallback : execution sequentielle sans LangGraph ────────────────────


def run_sequential(
    user_request: str,
    *,
    layer_context: str = "",
    registry: NodeRegistry = DEFAULT_REGISTRY,
    max_attempts: int = MAX_REPLAN_ATTEMPTS,
) -> AgentState:
    """
    Execute le graph en pure Python sans LangGraph. Equivalent comportemental
    a la version LangGraph pour les tests et environnements sans deps.

    Boucle : PLAN -> EXECUTE -> VERIFY -> (PLAN ou REPORT).
    """
    state = init_state(user_request, layer_context)

    for attempt in range(max_attempts):
        state = registry.plan_fn(state)
        state = registry.execute_fn(state)
        state = registry.verify_fn(state)
        if state.get("verify_passed"):
            break
        if attempt < max_attempts - 1:
            state = increment_replan(state)
            logger.info(
                "VERIFY echec (attempt %d) : %s -> re-plan",
                attempt + 1, state.get("verify_message"),
            )

    state = registry.report_fn(state)
    return state


# ─── Mode LangGraph natif ─────────────────────────────────────────────────────


def is_langgraph_available() -> tuple[bool, str]:
    try:
        import langgraph  # noqa: F401
    except ImportError as e:
        return False, f"langgraph non installe : {e}. 'pip install langgraph langchain-core'."
    return True, ""


def build_graph(registry: NodeRegistry = DEFAULT_REGISTRY) -> Any:
    """
    Compile un StateGraph LangGraph natif. Reserve aux environnements ou
    LangGraph est installe (Sprint 7+).
    """
    ok, reason = is_langgraph_available()
    if not ok:
        raise RuntimeError(reason)

    from langgraph.graph import StateGraph, END  # type: ignore

    graph: Any = StateGraph(AgentState)
    graph.add_node("plan", registry.plan_fn)
    graph.add_node("execute", registry.execute_fn)
    graph.add_node("verify", registry.verify_fn)
    graph.add_node("report", registry.report_fn)
    graph.add_node("increment_replan", increment_replan)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "verify")
    graph.add_conditional_edges(
        "verify",
        route_after_verify,
        {"plan": "increment_replan", "report": "report"},
    )
    graph.add_edge("increment_replan", "plan")
    graph.add_edge("report", END)

    return graph.compile()


def run_langgraph(
    user_request: str,
    *,
    layer_context: str = "",
    registry: NodeRegistry = DEFAULT_REGISTRY,
) -> AgentState:
    """Lance le graph LangGraph compile. Echoue si langgraph absent."""
    compiled = build_graph(registry)
    initial = init_state(user_request, layer_context)
    return compiled.invoke(initial)


# ─── API publique ─────────────────────────────────────────────────────────────


def run_agent(
    user_request: str,
    *,
    layer_context: str = "",
    registry: NodeRegistry = DEFAULT_REGISTRY,
    prefer_langgraph: bool = True,
) -> AgentState:
    """
    Point d'entree principal. Tente d'utiliser LangGraph si disponible,
    sinon retombe sur l'execution sequentielle.
    """
    if prefer_langgraph:
        ok, _ = is_langgraph_available()
        if ok:
            return run_langgraph(
                user_request,
                layer_context=layer_context,
                registry=registry,
            )
    return run_sequential(
        user_request,
        layer_context=layer_context,
        registry=registry,
    )
