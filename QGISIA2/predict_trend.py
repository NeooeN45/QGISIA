"""Analyse et projection de tendances temporelles sur séries d'indices (dNDVI, etc.)."""

from __future__ import annotations


def linear_trend(points: list[tuple[float, float]]) -> dict[str, float]:
    """Retourne slope, intercept et r² par moindres carrés ordinaires."""
    if len(points) < 2:
        return {"slope": 0.0, "intercept": 0.0, "r2": 0.0}

    n = len(points)
    sum_x = sum(x for x, _ in points)
    sum_y = sum(y for _, y in points)
    sum_xy = sum(x * y for x, y in points)
    sum_x2 = sum(x * x for x, _ in points)
    sum_y2 = sum(y * y for _, y in points)

    denominator = n * sum_x2 - sum_x * sum_x
    if denominator == 0:
        return {"slope": 0.0, "intercept": sum_y / n, "r2": 0.0}

    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n

    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in points)
    ss_tot = sum((y - sum_y / n) ** 2 for _, y in points)
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot != 0 else 1.0

    return {"slope": slope, "intercept": intercept, "r2": r2}


def project(points: list[tuple[float, float]], horizon_steps: int) -> list[float]:
    """Extrapole `horizon_steps` valeurs futures à partir de la tendance linéaire."""
    if not points or horizon_steps <= 0:
        return []

    model = linear_trend(points)
    slope = model["slope"]
    intercept = model["intercept"]
    last_x = points[-1][0]

    return [slope * (last_x + step) + intercept for step in range(1, horizon_steps + 1)]


def classify_trend(slope: float) -> str:
    """Classifie une pente en dégradation, stable ou amélioration."""
    THRESHOLD = 0.01
    if slope < -THRESHOLD:
        return "degradation"
    if slope > THRESHOLD:
        return "amelioration"
    return "stable"
