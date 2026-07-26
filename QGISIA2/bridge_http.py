# -*- coding: utf-8 -*-
"""
bridge_http — utilitaires HTTP de sécurité du bridge QGISIA+.

Module PUR (stdlib uniquement, pas de Qt/QGIS) extrait de geoai_assistant pour
être testable en CI. Centralise :
- la politique CORS restreinte aux origines locales (anti DNS-rebinding / CSRF) ;
- le bornage du body de requête (anti-DoS mémoire) ;
- la lecture JSON sûre du corps de requête.

Le bridge n'écoute que sur 127.0.0.1 : seules les origines locales sont
autorisées. Remplace l'ancien `Access-Control-Allow-Origin: *`.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Optional

# Taille max d'un body de requête. 32 Mo autorise les images base64 (vision)
# tout en bloquant les payloads de saturation mémoire (DoS).
MAX_REQUEST_BYTES = 32 * 1024 * 1024

_ALLOWED_ORIGIN_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$", re.I)


def is_local_origin(origin: Optional[str]) -> bool:
    """True si l'origine est locale (localhost / 127.0.0.1, port optionnel)."""
    return bool(origin) and bool(_ALLOWED_ORIGIN_RE.match(origin))


def send_cors_headers(handler) -> None:
    """Écrit des en-têtes CORS restreints aux origines locales.

    L'UI same-origin (http://127.0.0.1:<port>) reste autorisée ; toute origine
    distante est refusée.
    """
    origin = handler.headers.get("Origin", "")
    if is_local_origin(origin):
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")


def parse_content_length(raw: Optional[str]) -> int:
    """Parse l'en-tête Content-Length de façon robuste (0 si invalide)."""
    try:
        return int(raw or "0")
    except (TypeError, ValueError):
        return 0


def read_json_body(
    handler,
    max_bytes: int = MAX_REQUEST_BYTES,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Lit et parse le body JSON d'une requête, borné à `max_bytes`.

    Retourne {} si vide, trop volumineux, ou JSON invalide (le payload démesuré
    n'est jamais chargé en mémoire).
    """
    length = parse_content_length(handler.headers.get("Content-Length"))
    if length <= 0:
        return {}
    if length > max_bytes:
        if log_fn:
            log_fn(f"Requête bridge rejetée: body {length} octets > max {max_bytes}")
        return {}
    raw_body = handler.rfile.read(length)
    if not raw_body:
        return {}
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
