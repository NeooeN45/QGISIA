"""Clustering DBSCAN 2D pur Python — stdlib uniquement."""

from __future__ import annotations

import math


def _region_query(
    points: list[tuple[float, float]], point_idx: int, eps: float
) -> list[int]:
    """Retourne les indices des points situés à une distance <= eps du point cible."""
    px, py = points[point_idx]
    neighbors = []
    for idx, (x, y) in enumerate(points):
        if math.hypot(px - x, py - y) <= eps:
            neighbors.append(idx)
    return neighbors


def dbscan(
    points: list[tuple[float, float]], eps: float, min_pts: int
) -> list[int]:
    """DBSCAN simple : retourne un label par point (-1 = bruit)."""
    n = len(points)
    labels = [-1] * n
    visited = [False] * n
    cluster_id = 0

    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True
        neighbors = _region_query(points, i, eps)
        if len(neighbors) < min_pts:
            continue

        labels[i] = cluster_id
        seeds = [idx for idx in neighbors if idx != i]
        k = 0
        while k < len(seeds):
            q = seeds[k]
            k += 1
            if not visited[q]:
                visited[q] = True
                q_neighbors = _region_query(points, q, eps)
                if len(q_neighbors) >= min_pts:
                    for qn in q_neighbors:
                        if qn not in seeds:
                            seeds.append(qn)
            if labels[q] == -1:
                labels[q] = cluster_id
        cluster_id += 1

    return labels


def centroids(
    points: list[tuple[float, float]], labels: list[int]
) -> dict[int, tuple[float, float]]:
    """Calcule le centroïde de chaque cluster (ignore le bruit -1)."""
    clusters: dict[int, list[tuple[float, float]]] = {}
    for pt, lbl in zip(points, labels):
        if lbl == -1:
            continue
        clusters.setdefault(lbl, []).append(pt)

    result: dict[int, tuple[float, float]] = {}
    for lbl, pts in clusters.items():
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        result[lbl] = (cx, cy)
    return result
