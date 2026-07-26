# ═══════════════════════════════════════════════════════════════════════════════
# IMPLÉMENTÉ PAR DEVIN CLI (Cognition AI)
# Superviseur : Claude Code 4.8 — Camil
# Date : 2026-06-08 | Branche : chore/hygiene-puis-nvidia
# Review obligatoire avant merge dans main.
# ═══════════════════════════════════════════════════════════════════════════════
# -*- coding: utf-8 -*-
"""
devin_utils — Pastille de traçabilité Devin CLI.

Fournit :
- @devin_authored : décorateur marquant les fonctions/classes implémentées par Devin.
  N'altère PAS le comportement. Permet l'audit statique et runtime.
- SecurityAuditLog : journal d'audit des actions agent (sans PII ni clés).
  Écrit dans DEVIN_AUDIT.log (gitignoré). Thread-safe.

Usage :
    from QGISIA2.devin_utils import devin_authored, audit_log

    @devin_authored
    def ma_fonction(): ...

    audit_log.record("tool_called", tool="computeNDVI", user_id="local")
"""
from __future__ import annotations

import functools
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar

# Résolution du dossier racine — robuste même depuis QGIS
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_AUDIT_LOG_PATH = _PACKAGE_ROOT / "DEVIN_AUDIT.log"

# TypeVar pour préserver les types à travers le décorateur
_F = TypeVar("_F", bound=Callable[..., Any])

# Métadonnées globales de la session Devin (readonly après init)
DEVIN_AGENT_ID = "devin-cli/cognition"
DEVIN_SUPERVISOR = "claude-code-4.8/camil"


# ── Décorateur @devin_authored ────────────────────────────────────────────────


def devin_authored(func: _F) -> _F:
    """
    Marque une fonction/classe comme implémentée par Devin CLI.

    Attributs ajoutés :
        __devin_authored__  : True
        __devin_agent__     : identifiant de l'agent
        __devin_supervisor__: superviseur du projet

    N'altère pas le comportement (wrapper transparent via functools.wraps).
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    wrapper.__devin_authored__ = True  # type: ignore[attr-defined]
    wrapper.__devin_agent__ = DEVIN_AGENT_ID  # type: ignore[attr-defined]
    wrapper.__devin_supervisor__ = DEVIN_SUPERVISOR  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]


# ── SecurityAuditLog ──────────────────────────────────────────────────────────

# Clés sensibles interdites dans les logs — jamais tracées même partiellement
_SENSITIVE_KEYS = frozenset({
    "api_key", "apikey", "nvidia_api_key", "openrouter_api_key",
    "gemini_api_key", "anthropic_api_key", "openai_api_key",
    "password", "passwd", "secret", "token", "authorization",
    "bearer", "credential", "private_key",
})

_API_KEY_PATTERN = re.compile(
    r"(nvapi-|sk-|eyJ)[A-Za-z0-9_\-\.]{8,}",
    re.IGNORECASE,
)


def _redact_value(key: str, value: Any) -> Any:
    """Remplace une valeur sensible par '[REDACTED]'."""
    if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, str):
        return _API_KEY_PATTERN.sub("[REDACTED]", value)
    return value


def _sanitize_record(data: Dict[str, Any]) -> Dict[str, Any]:
    """Supprime récursivement les valeurs sensibles d'un dict de log."""
    result: Dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, dict):
            result[k] = _sanitize_record(v)
        else:
            result[k] = _redact_value(k, v)
    return result


class SecurityAuditLog:
    """
    Journal d'audit thread-safe pour les actions de l'agent.

    - Écrit dans DEVIN_AUDIT.log (une entrée JSON par ligne).
    - Ne logue jamais de clés API, tokens, passwords.
    - Taille maximale : 5 Mo (rotation auto).
    - Toutes les entrées portent le marquage Devin.
    """

    MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5 Mo

    def __init__(self, log_path: Path = _AUDIT_LOG_PATH) -> None:
        self._path = log_path
        self._lock = threading.Lock()

    def record(
        self,
        event: str,
        *,
        level: str = "INFO",
        **kwargs: Any,
    ) -> None:
        """
        Enregistre un événement d'audit.

        Args:
            event: identifiant de l'événement (ex: "tool_called", "guardrail_blocked")
            level: "INFO" | "WARN" | "ERROR" | "SECURITY"
            **kwargs: données contextuelles (clés sensibles automatiquement purgées)
        """
        entry = _sanitize_record({
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "level": level,
            "event": event,
            "agent": DEVIN_AGENT_ID,
            "supervisor": DEVIN_SUPERVISOR,
            **kwargs,
        })
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock:
            self._rotate_if_needed()
            try:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                # En environnement read-only (CI, sandbox), on ignore silencieusement
                pass

    def _rotate_if_needed(self) -> None:
        """Rotation du log si > MAX_SIZE_BYTES (archive → .1)."""
        try:
            if self._path.exists() and self._path.stat().st_size > self.MAX_SIZE_BYTES:
                archive = self._path.with_suffix(".log.1")
                self._path.rename(archive)
        except OSError:
            pass

    def last_entries(self, n: int = 20) -> list:
        """Retourne les n dernières entrées pour introspection/debug."""
        with self._lock:
            if not self._path.exists():
                return []
            try:
                lines = self._path.read_text(encoding="utf-8").splitlines()
                return [json.loads(l) for l in lines[-n:] if l.strip()]
            except (OSError, json.JSONDecodeError):
                return []


# Singleton partagé — importer depuis ici, ne pas réinstancier
audit_log = SecurityAuditLog()
