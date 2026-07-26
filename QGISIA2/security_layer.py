# ═══════════════════════════════════════════════════════════════════════════════
# IMPLÉMENTÉ PAR DEVIN CLI (Cognition AI)
# Superviseur : Claude Code 4.8 — Camil
# Date : 2026-06-08 | Branche : chore/hygiene-puis-nvidia
# Review obligatoire avant merge dans main.
# ═══════════════════════════════════════════════════════════════════════════════
# -*- coding: utf-8 -*-
"""
security_layer — Couche de sécurité HTTP pour le bridge QGISIA+.

Fournit :
- RateLimiter    : limite le nombre de requêtes par IP par fenêtre glissante.
                   Protège contre les boucles d'agent runaway et les abus locaux.
- InputSanitizer : nettoie et valide les payloads JSON entrants.
                   Bloque les prompt injections, code arbitraire et dépassements de taille.
- SecurityMiddleware : façade combinée à brancher sur le BaseHTTPServer.

Toutes les actions de blocage sont loguées via SecurityAuditLog.
Module pur Python — pas de dépendance QGIS, testable standalone.
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    from .devin_utils import audit_log, devin_authored
except ImportError:
    from devin_utils import audit_log, devin_authored  # type: ignore[no-redef]


# ── Constantes ────────────────────────────────────────────────────────────────

# Taille maximale acceptée pour le body d'une requête (256 Ko)
MAX_BODY_BYTES = 256 * 1024

# Longueur maximale d'un champ texte unique (prompt, query, etc.)
MAX_FIELD_LENGTH = 16_000

# Patterns de prompt injection / attaques connues
_INJECTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.I),
    re.compile(r"system\s*:\s*you\s+are\s+now", re.I),
    re.compile(r"<\s*script\s*>", re.I),
    re.compile(r"javascript\s*:", re.I),
    re.compile(r"\beval\s*\(", re.I),
    re.compile(r"__import__\s*\(", re.I),
    re.compile(r"os\.system\s*\(", re.I),
    re.compile(r"subprocess\.(call|run|Popen)\s*\(", re.I),
    re.compile(r"\brm\s+-rf\b", re.I),
    re.compile(r"del\s+/[sq]\b", re.I),       # Windows del /s /q
]

# Clés de payload dont la valeur doit être traitée comme texte utilisateur
_USER_TEXT_FIELDS = frozenset({
    "message", "prompt", "query", "text", "content",
    "voice_input", "user_input", "instruction",
})


# ── RateLimiter ───────────────────────────────────────────────────────────────


@dataclass
class RateLimiter:
    """
    Rate limiter à fenêtre glissante par client (IP ou clé).

    Paramètres:
        max_requests : nombre max de requêtes dans la fenêtre
        window_seconds : durée de la fenêtre glissante en secondes
    """
    max_requests: int = 60
    window_seconds: float = 60.0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _clients: Dict[str, deque] = field(default_factory=dict)

    @devin_authored
    def is_allowed(self, client_id: str) -> bool:
        """
        Vérifie si le client peut émettre une nouvelle requête.

        Returns:
            True si autorisé, False si le quota est dépassé.
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            if client_id not in self._clients:
                self._clients[client_id] = deque()

            timestamps = self._clients[client_id]
            # Purger les timestamps hors de la fenêtre
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()

            if len(timestamps) >= self.max_requests:
                audit_log.record(
                    "rate_limit_exceeded",
                    level="WARN",
                    client_id=client_id,
                    count=len(timestamps),
                    max_requests=self.max_requests,
                    window_seconds=self.window_seconds,
                )
                return False

            timestamps.append(now)
            return True

    @devin_authored
    def reset(self, client_id: Optional[str] = None) -> None:
        """Réinitialise les compteurs d'un client ou de tous les clients."""
        with self._lock:
            if client_id:
                self._clients.pop(client_id, None)
            else:
                self._clients.clear()

    @devin_authored
    def client_count(self, client_id: str) -> int:
        """Nombre de requêtes dans la fenêtre courante pour un client."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            if client_id not in self._clients:
                return 0
            return sum(1 for ts in self._clients[client_id] if ts >= cutoff)


# ── InputSanitizer ────────────────────────────────────────────────────────────


@dataclass
class SanitizationResult:
    is_safe: bool
    reason: Optional[str] = None
    sanitized_body: Optional[dict] = None


@devin_authored
def sanitize_request_body(raw_body: bytes) -> SanitizationResult:
    """
    Valide et nettoie un body JSON de requête HTTP.

    Vérifie :
    1. Taille du body (≤ MAX_BODY_BYTES)
    2. JSON valide
    3. Longueur des champs texte utilisateur (≤ MAX_FIELD_LENGTH)
    4. Absence de patterns d'injection connus

    Returns:
        SanitizationResult.is_safe=True si le payload est acceptable.
    """
    # 1. Vérification de taille
    if len(raw_body) > MAX_BODY_BYTES:
        audit_log.record(
            "input_rejected_size",
            level="WARN",
            body_bytes=len(raw_body),
            max_bytes=MAX_BODY_BYTES,
        )
        return SanitizationResult(
            is_safe=False,
            reason=f"Payload trop volumineux ({len(raw_body)} octets, max {MAX_BODY_BYTES})",
        )

    # 2. Parsing JSON
    try:
        payload = json.loads(raw_body.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError) as exc:
        return SanitizationResult(is_safe=False, reason=f"JSON invalide: {exc}")

    if not isinstance(payload, dict):
        return SanitizationResult(is_safe=False, reason="Payload doit être un objet JSON")

    # 3 & 4. Parcours des champs utilisateur
    for key, value in payload.items():
        if not isinstance(value, str):
            continue
        if key.lower() in _USER_TEXT_FIELDS:
            if len(value) > MAX_FIELD_LENGTH:
                audit_log.record(
                    "input_rejected_field_length",
                    level="WARN",
                    field=key,
                    length=len(value),
                    max_length=MAX_FIELD_LENGTH,
                )
                return SanitizationResult(
                    is_safe=False,
                    reason=f"Champ '{key}' trop long ({len(value)} chars, max {MAX_FIELD_LENGTH})",
                )
            injection_hit = _detect_injection(value)
            if injection_hit:
                audit_log.record(
                    "input_rejected_injection",
                    level="SECURITY",
                    field=key,
                    pattern=injection_hit,
                )
                return SanitizationResult(
                    is_safe=False,
                    reason=f"Pattern dangereux détecté dans le champ '{key}'",
                )

    return SanitizationResult(is_safe=True, sanitized_body=payload)


@devin_authored
def _detect_injection(text: str) -> Optional[str]:
    """
    Retourne le nom du pattern d'injection détecté, ou None si propre.
    """
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


# ── SecurityMiddleware ────────────────────────────────────────────────────────


class SecurityMiddleware:
    """
    Façade combinant RateLimiter + InputSanitizer.

    Usage dans BaseHTTPRequestHandler :

        from QGISIA2.security_layer import security_middleware

        class MyHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                allowed, err = security_middleware.check_rate(self.client_address[0])
                if not allowed:
                    self._send_json(429, {"error": err})
                    return
                body = self.rfile.read(int(self.headers.get("content-length", 0)))
                result = security_middleware.sanitize(body)
                if not result.is_safe:
                    self._send_json(400, {"error": result.reason})
                    return
                payload = result.sanitized_body
                ...
    """

    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: float = 60.0,
    ) -> None:
        self._limiter = RateLimiter(
            max_requests=max_requests,
            window_seconds=window_seconds,
        )

    @devin_authored
    def check_rate(self, client_id: str) -> Tuple[bool, Optional[str]]:
        """
        Returns (True, None) si autorisé, (False, message_erreur) si bloqué.
        """
        if self._limiter.is_allowed(client_id):
            return True, None
        remaining_window = self._limiter.window_seconds
        return False, (
            f"Trop de requêtes. Réessaie dans {int(remaining_window)} secondes."
        )

    @devin_authored
    def sanitize(self, raw_body: bytes) -> SanitizationResult:
        """Délègue à sanitize_request_body."""
        return sanitize_request_body(raw_body)

    @devin_authored
    def reset_client(self, client_id: str) -> None:
        """Réinitialise le compteur d'un client (ex: après auth réussie)."""
        self._limiter.reset(client_id)


# Singleton partagé — importer et utiliser directement
security_middleware = SecurityMiddleware(max_requests=60, window_seconds=60.0)
