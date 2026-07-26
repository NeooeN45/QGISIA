# -*- coding: utf-8 -*-
"""
bridge_http — garde et utilitaires HTTP du bridge QGISIA+.

Module PUR (stdlib uniquement, pas de Qt/QGIS) extrait de geoai_assistant pour
être testable en CI. Il porte le **contrat d'accès** du bridge loopback.

Contrat (voir docs/security/BRIDGE_SECURITY.md) — évalué dans cet ordre, et
TOUJOURS avant la lecture du corps de la requête :

1. `Host` doit désigner la boucle locale (127.0.0.1 / localhost / [::1]),
   sinon **403**. C'est la défense anti DNS-rebinding : un attaquant qui fait
   pointer son domaine vers 127.0.0.1 conserve son propre `Host`.
2. `Origin`, si présent, doit être local, sinon **403**. Sur une méthode
   mutante (POST/PUT/PATCH/DELETE) l'en-tête est *obligatoire* : les
   navigateurs l'émettent systématiquement, son absence signale un client non
   navigateur qui contourne la politique d'origine.
3. `X-QGISIA-Token` doit correspondre au jeton tiré au démarrage du serveur
   (comparaison à temps constant), sinon **401**.
4. Sur POST, `Content-Type` doit être `application/json`, sinon **415**. Cela
   ferme les MIME « simple request » (text/plain, form-urlencoded, multipart)
   qu'un `<form>` cross-origin peut émettre sans préflight.

Un refus n'est jamais une simple omission d'en-tête CORS : la requête est
rejetée avec un statut explicite et le dispatcher n'est pas atteint.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
from html import escape as html_escape
from typing import Any, Callable, Dict, NamedTuple, Optional
from urllib.parse import urlsplit

# Taille max d'un body de requête. 32 Mo autorise les images base64 (vision)
# tout en bloquant les payloads de saturation mémoire (DoS).
MAX_REQUEST_BYTES = 32 * 1024 * 1024

# En-tête portant le jeton d'authentification du bridge.
TOKEN_HEADER = "X-QGISIA-Token"

# Octets d'entropie du jeton (secrets.token_urlsafe).
TOKEN_ENTROPY_BYTES = 32

# Méthodes mutantes : l'en-tête Origin y est obligatoire.
_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_ALLOWED_ORIGIN_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$", re.I)
_ALLOWED_HOST_RE = re.compile(r"^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$", re.I)


class GuardResult(NamedTuple):
    """Décision de la garde : `ok` vrai, ou (status, error) à renvoyer tel quel."""

    ok: bool
    status: int
    error: str


_GUARD_OK = GuardResult(True, 200, "")


# ── Jeton ─────────────────────────────────────────────────────────────────────


def generate_token() -> str:
    """Tire un jeton cryptographiquement aléatoire, neuf à chaque démarrage."""
    return secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def tokens_match(expected: Optional[str], provided: Optional[str]) -> bool:
    """Compare deux jetons à temps constant.

    Retourne False si l'un des deux est vide : un serveur sans jeton configuré
    ne doit rien laisser passer (pas de mode « ouvert » par accident).
    """
    if not expected or not provided:
        return False
    return hmac.compare_digest(
        str(expected).encode("utf-8"), str(provided).encode("utf-8")
    )


# ── Origine, hôte, type MIME ──────────────────────────────────────────────────


def is_local_origin(origin: Optional[str]) -> bool:
    """True si l'origine est locale (localhost / 127.0.0.1, port optionnel)."""
    return bool(origin) and bool(_ALLOWED_ORIGIN_RE.match(origin))


def is_local_host(host: Optional[str]) -> bool:
    """True si l'en-tête Host désigne la boucle locale (anti DNS-rebinding).

    `127.0.0.1.evil.com` et `localhost.evil.com` sont refusés : l'ancre de fin
    de la regex interdit tout suffixe.
    """
    return bool(host) and bool(_ALLOWED_HOST_RE.match(host))


def is_json_content_type(value: Optional[str]) -> bool:
    """True si le Content-Type est exactement application/json (paramètres ok)."""
    if not value:
        return False
    return value.split(";", 1)[0].strip().lower() == "application/json"


# ── Garde ─────────────────────────────────────────────────────────────────────


def guard_request(handler, expected_token: Optional[str], method: str) -> GuardResult:
    """Applique le contrat d'accès du bridge. À appeler AVANT de lire le corps.

    `method` est la méthode HTTP ("GET", "POST", ...).
    """
    headers = handler.headers
    method = (method or "").upper()

    if not is_local_host(headers.get("Host")):
        return GuardResult(False, 403, "Hôte non local refusé.")

    origin = headers.get("Origin")
    if origin:
        if not is_local_origin(origin):
            return GuardResult(False, 403, "Origine non locale refusée.")
    elif method in _STATE_CHANGING_METHODS:
        return GuardResult(False, 403, "En-tête Origin obligatoire sur cette méthode.")

    if not tokens_match(expected_token, headers.get(TOKEN_HEADER)):
        return GuardResult(False, 401, "Jeton de bridge absent ou invalide.")

    if method == "POST" and not is_json_content_type(headers.get("Content-Type")):
        return GuardResult(False, 415, "Content-Type application/json requis.")

    return _GUARD_OK


def send_guard_error(handler, result: GuardResult) -> None:
    """Renvoie le refus de la garde. Ne divulgue jamais le jeton attendu."""
    body = json.dumps(
        {"ok": False, "error": result.error}, ensure_ascii=False
    ).encode("utf-8")
    handler.send_response(result.status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    send_cors_headers(handler)
    handler.end_headers()
    handler.wfile.write(body)


# ── Clients locaux de confiance (MCP, agent) ──────────────────────────────────
#
# L'UI navigateur reçoit le jeton par balise <meta>. Mais le plugin a aussi des
# clients Python légitimes — le serveur MCP et la boucle d'outils de l'agent —
# qui appellent le bridge en HTTP sans être des navigateurs. Ils doivent donc
# s'authentifier explicitement, et fournir l'`Origin` que le contrat exige sur
# les méthodes mutantes.
#
# Le jeton actif est publié en mémoire par le serveur au démarrage. Pour un
# serveur MCP lancé dans un AUTRE processus, il est repris de la variable
# d'environnement QGISIA_BRIDGE_TOKEN.

_ACTIVE_TOKEN: Optional[str] = None

TOKEN_ENV_VAR = "QGISIA_BRIDGE_TOKEN"


def set_active_token(token: Optional[str]) -> None:
    """Publie le jeton du serveur courant pour les clients locaux in-process."""
    global _ACTIVE_TOKEN
    _ACTIVE_TOKEN = token


def get_active_token() -> str:
    """Jeton du bridge : mémoire du processus, sinon variable d'environnement."""
    return _ACTIVE_TOKEN or os.environ.get(TOKEN_ENV_VAR, "") or ""


def origin_for(bridge_url: Optional[str]) -> str:
    """Origine (schéma://hôte:port) déduite d'une URL de bridge."""
    parts = urlsplit(bridge_url or "")
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return "http://127.0.0.1"


def local_client_headers(
    bridge_url: Optional[str] = None, token: Optional[str] = None
) -> Dict[str, str]:
    """En-têtes qu'un client local de confiance doit envoyer au bridge.

    Un client qui les utilise satisfait `guard_request` : c'est le pendant
    exact du contrat côté serveur, pour qu'ils ne puissent pas diverger.
    """
    return {
        "Content-Type": "application/json",
        "Origin": origin_for(bridge_url),
        TOKEN_HEADER: token if token is not None else get_active_token(),
    }


# ── Transmission du jeton à l'UI locale ───────────────────────────────────────

# Nom de la balise <meta> qui porte le jeton dans la page servie localement.
TOKEN_META_NAME = "qgisia-bridge-token"

_HEAD_RE = re.compile(r"<head\b[^>]*>", re.I)


def inject_token_meta(html: str, token: str) -> str:
    """Insère le jeton dans le `<head>` de la page servie depuis 127.0.0.1.

    Le jeton passe par le corps du document, jamais par l'URL : il n'atterrit
    donc ni dans l'historique du navigateur, ni dans un en-tête `Referer`, ni
    dans les journaux d'un proxy. Seul du JavaScript de même origine peut le
    lire — une page tierce en est empêchée par la politique d'origine, et un
    rebinding DNS est arrêté en amont par le contrôle de l'en-tête `Host`.
    """
    escaped = html_escape(token or "", quote=True)
    meta = f'<meta name="{TOKEN_META_NAME}" content="{escaped}">'
    match = _HEAD_RE.search(html)
    if match:
        return html[: match.end()] + meta + html[match.end():]
    return meta + html


# ── CORS ──────────────────────────────────────────────────────────────────────


def send_cors_headers(handler) -> None:
    """Écrit des en-têtes CORS restreints aux origines locales.

    Complément de `guard_request`, pas un substitut : l'omission de
    `Access-Control-Allow-Origin` empêche un navigateur de *lire* la réponse,
    mais seule la garde empêche la requête d'*agir*.
    """
    origin = handler.headers.get("Origin", "")
    if is_local_origin(origin):
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", f"Content-Type, {TOKEN_HEADER}")


# ── Corps de requête ──────────────────────────────────────────────────────────


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
