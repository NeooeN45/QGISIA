"""Moteur de pipeline d'analyse declarative (coeur de l'autonomie).

Decrit des pipelines SIG en JSON (etapes + dependances) et produit un plan
ordonne et valide. Generalise study_plan.
"""
from __future__ import annotations

from typing import Optional

ACTION_SCHEMA: dict[str, dict] = {
    "add_basemap": {
        "required_params": ["source_id"],
        "produces": "basemap_layer",
        "consumes": [],
    },
    "load_satellite": {
        "required_params": ["source_id"],
        "produces": "raster_layer",
        "consumes": [],
    },
    "compute_index": {
        "required_params": ["index"],
        "produces": "index_raster",
        "consumes": ["raster_layer"],
    },
    "raster_difference": {
        "required_params": [],
        "produces": "diff_raster",
        "consumes": ["raster_layer", "raster_layer"],
    },
    "zonal_stats": {
        "required_params": ["vector_layer"],
        "produces": "stats_table",
        "consumes": ["raster_layer", "vector_layer"],
    },
    "classify": {
        "required_params": ["method"],
        "produces": "class_raster",
        "consumes": ["raster_layer"],
    },
    "buffer": {
        "required_params": ["distance"],
        "produces": "buffer_layer",
        "consumes": ["vector_layer"],
    },
    "suitability": {
        "required_params": ["preset_id"],
        "produces": "suit_raster",
        "consumes": ["raster_layer"],
    },
    "hotspot": {
        "required_params": [],
        "produces": "hotspot_layer",
        "consumes": ["vector_layer"],
    },
    "terrain": {
        "required_params": ["method"],
        "produces": "terrain_raster",
        "consumes": ["raster_layer"],
    },
    "layout": {
        "required_params": [],
        "produces": "layout",
        "consumes": ["raster_layer"],
    },
    "atlas": {
        "required_params": [],
        "produces": "atlas",
        "consumes": ["layout"],
    },
    "report": {
        "required_params": [],
        "produces": "report",
        "consumes": ["stats_table"],
    },
}

HEAVY_ACTIONS = {"load_satellite", "suitability", "terrain", "atlas", "classify"}
NETWORK_ACTIONS = {"load_satellite", "add_basemap"}


def _find_cycles(graph: dict[str, set[str]]) -> list[str]:
    """Detecte les cycles dans un graphe oriente. Renvoie liste de messages d'erreur."""
    errors: list[str] = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}
    parent: dict[str, Optional[str]] = {}

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        for neighbor in graph.get(node, set()):
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                errors.append("Cycle detecte: " + " -> ".join(cycle))
            elif color[neighbor] == WHITE:
                parent[neighbor] = node
                dfs(neighbor, path + [neighbor])
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            parent[node] = None
            dfs(node, [node])

    return errors


def validate_pipeline(pipeline: dict) -> list[str]:
    """Valide un pipeline. Renvoie la liste des erreurs detectees."""
    errors: list[str] = []
    steps = pipeline.get("steps", [])
    if not isinstance(steps, list):
        return ["'steps' doit etre une liste"]

    ids = []
    id_to_step: dict[str, dict] = {}
    for step in steps:
        sid = step.get("id")
        if sid in id_to_step:
            errors.append(f"ID duplique: '{sid}'")
        else:
            ids.append(sid)
            id_to_step[sid] = step

    for step in steps:
        sid = step.get("id")
        action = step.get("action")
        if action not in ACTION_SCHEMA:
            errors.append(f"[{sid}] action inconnue: '{action}'")
            continue

        schema = ACTION_SCHEMA[action]
        params = step.get("params", {})
        for req in schema.get("required_params", []):
            if req not in params:
                errors.append(f"[{sid}] param requis manquant: '{req}'")

        for dep in step.get("needs", []):
            if dep not in id_to_step:
                errors.append(f"[{sid}] dependance inexistante: '{dep}'")

    # Detection de cycle via needs
    graph = {sid: set() for sid in ids}
    for step in steps:
        sid = step.get("id")
        for dep in step.get("needs", []):
            if dep in graph:
                graph[sid].add(dep)
    cycle_errors = _find_cycles(graph)
    errors.extend(cycle_errors)

    return errors


def topological_order(pipeline: dict) -> list[str]:
    """Tri topologique des etapes selon 'needs'. Leve ValueError si cycle."""
    steps = pipeline.get("steps", [])
    in_degree: dict[str, int] = {}
    adj: dict[str, list[str]] = {}

    for step in steps:
        sid = step["id"]
        in_degree[sid] = 0
        adj[sid] = []

    for step in steps:
        sid = step["id"]
        for dep in step.get("needs", []):
            if dep in adj:
                adj[dep].append(sid)
                in_degree[sid] = in_degree.get(sid, 0) + 1

    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    order: list[str] = []

    while queue:
        node = queue.pop(0)
        order.append(node)
        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(order) != len(steps):
        raise ValueError("Cycle detecte dans le pipeline")
    return order


def resolve_io(pipeline: dict) -> dict[str, dict]:
    """Relie les sorties (produces) aux entrees (consumes) entre etapes."""
    steps = pipeline.get("steps", [])
    step_map = {step["id"]: step for step in steps}
    order = topological_order(pipeline)

    available_outputs: dict[str, str] = {}  # type_token -> step_id
    result: dict[str, dict] = {}

    for sid in order:
        step = step_map[sid]
        action = step.get("action", "")
        schema = ACTION_SCHEMA.get(action, {})
        consumes = schema.get("consumes", [])
        produces = schema.get("produces")

        inputs_from: list[str] = []
        for needed_type in consumes:
            source = available_outputs.get(needed_type)
            if source and source not in inputs_from:
                inputs_from.append(source)

        result[sid] = {
            "inputs_from": inputs_from,
            "output": produces,
        }

        if produces:
            available_outputs[produces] = sid

    return result


def estimate_cost(pipeline: dict) -> dict[str, int]:
    """Estime la charge du pipeline : total, reseau, lourd."""
    steps = pipeline.get("steps", [])
    total = len(steps)
    network_steps = 0
    heavy_steps = 0

    for step in steps:
        action = step.get("action", "")
        if action in NETWORK_ACTIONS:
            network_steps += 1
        if action in HEAVY_ACTIONS:
            heavy_steps += 1

    return {
        "steps": total,
        "network_steps": network_steps,
        "heavy_steps": heavy_steps,
    }
