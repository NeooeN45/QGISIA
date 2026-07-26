# -*- coding: utf-8 -*-
"""Tests de la couche HTTP de sécurité du bridge (module pur, sans QGIS).

Deux niveaux :
- tests unitaires des primitives (origine, hôte, jeton, MIME, corps) ;
- tests d'intégration sur un vrai serveur loopback câblé exactement comme la
  production (`bridge_http.guard_request` + `bridge_http.send_guard_error`),
  qui vérifient que le dispatcher n'est JAMAIS atteint quand la garde refuse.
"""
import http.client
import io
import json
import os
import socketserver
import sys
import threading
import http.server

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "QGISIA2"))

import bridge_http as bh  # noqa: E402


class _FakeHandler:
    def __init__(self, headers, body=b""):
        self.headers = headers
        self.rfile = io.BytesIO(body)


# ── is_local_origin ───────────────────────────────────────────────────────────

def test_local_origins_allowed():
    for o in ("http://localhost:3000", "http://127.0.0.1", "https://localhost:8157"):
        assert bh.is_local_origin(o) is True


def test_remote_origins_rejected():
    for o in ("http://evil.com", "https://attacker.localhost.com", "", None):
        assert bh.is_local_origin(o) is False


# ── parse_content_length ──────────────────────────────────────────────────────

def test_parse_content_length():
    assert bh.parse_content_length("5") == 5
    assert bh.parse_content_length(None) == 0
    assert bh.parse_content_length("abc") == 0


# ── read_json_body ────────────────────────────────────────────────────────────

def test_read_valid_json():
    body = json.dumps({"query": "buffer"}).encode("utf-8")
    h = _FakeHandler({"Content-Length": str(len(body))}, body)
    assert bh.read_json_body(h) == {"query": "buffer"}


def test_read_empty_body():
    h = _FakeHandler({"Content-Length": "0"})
    assert bh.read_json_body(h) == {}


def test_oversized_body_rejected_without_reading():
    logged = []
    h = _FakeHandler({"Content-Length": str(bh.MAX_REQUEST_BYTES + 1)}, b"x")
    out = bh.read_json_body(h, log_fn=logged.append)
    assert out == {}
    assert logged  # un message d'avertissement a été émis
    # le corps n'a pas été lu (anti-DoS)
    assert h.rfile.tell() == 0


def test_non_dict_json_returns_empty():
    body = b"[1, 2, 3]"
    h = _FakeHandler({"Content-Length": str(len(body))}, body)
    assert bh.read_json_body(h) == {}


def test_invalid_json_returns_empty():
    body = b"{not json"
    h = _FakeHandler({"Content-Length": str(len(body))}, body)
    assert bh.read_json_body(h) == {}


# ── Jeton d'authentification ──────────────────────────────────────────────────

def test_generate_token_is_random_and_long():
    tokens = {bh.generate_token() for _ in range(50)}
    # 50 tirages, 50 valeurs distinctes : pas de constante codée en dur.
    assert len(tokens) == 50
    for token in tokens:
        # secrets.token_urlsafe(32) => >= 43 caractères url-safe.
        assert len(token) >= 43
        assert set(token) <= set(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        )


def test_tokens_match_requires_exact_value():
    secret = bh.generate_token()
    assert bh.tokens_match(secret, secret) is True
    assert bh.tokens_match(secret, None) is False
    assert bh.tokens_match(secret, "") is False
    assert bh.tokens_match(secret, secret[:-1]) is False       # préfixe
    assert bh.tokens_match(secret, secret + "x") is False      # extension
    assert bh.tokens_match(secret, secret.upper()) is False    # casse


def test_tokens_match_never_accepts_empty_expected():
    # Un serveur sans jeton configuré ne doit rien laisser passer.
    assert bh.tokens_match("", "") is False
    assert bh.tokens_match(None, None) is False


# ── En-tête Host (anti DNS-rebinding) ─────────────────────────────────────────

def test_local_host_headers_allowed():
    for host in ("127.0.0.1:8157", "localhost:8157", "127.0.0.1", "[::1]:8157"):
        assert bh.is_local_host(host) is True


def test_remote_host_headers_rejected():
    hostile = (
        "evil.com:8157",           # rebinding DNS classique
        "127.0.0.1.evil.com:8157",  # suffixe trompeur
        "localhost.evil.com",
        "evil.com",
        "",
        None,
    )
    for host in hostile:
        assert bh.is_local_host(host) is False


# ── Type MIME ─────────────────────────────────────────────────────────────────

def test_json_content_types_accepted():
    for ctype in ("application/json", "application/json; charset=utf-8", "APPLICATION/JSON"):
        assert bh.is_json_content_type(ctype) is True


def test_non_json_content_types_rejected():
    # text/plain, form-urlencoded et multipart sont les MIME « simple request »
    # que permet un formulaire HTML cross-origin : ils ne doivent jamais servir
    # à piloter QGIS.
    for ctype in (
        "text/plain",
        "text/plain;charset=UTF-8",
        "application/x-www-form-urlencoded",
        "multipart/form-data; boundary=x",
        "application/jsonx",
        "",
        None,
    ):
        assert bh.is_json_content_type(ctype) is False


# ── guard_request : ordre et codes ────────────────────────────────────────────

TOKEN = "jeton-de-test-uniquement-non-secret"


def _headers(**overrides):
    base = {
        "Host": "127.0.0.1:8157",
        "Origin": "http://127.0.0.1:8157",
        bh.TOKEN_HEADER: TOKEN,
        "Content-Type": "application/json",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def test_guard_accepts_a_well_formed_request():
    h = _FakeHandler(_headers())
    assert bh.guard_request(h, TOKEN, "POST").ok is True


def test_guard_rejects_hostile_origin_with_403():
    h = _FakeHandler(_headers(Origin="http://evil.com"))
    result = bh.guard_request(h, TOKEN, "POST")
    assert result.ok is False
    assert result.status == 403


def test_guard_rejects_missing_origin_on_post_with_403():
    h = _FakeHandler(_headers(Origin=None))
    result = bh.guard_request(h, TOKEN, "POST")
    assert result.ok is False
    assert result.status == 403


def test_guard_rejects_hostile_host_with_403():
    h = _FakeHandler(_headers(Host="evil.com:8157"))
    result = bh.guard_request(h, TOKEN, "POST")
    assert result.ok is False
    assert result.status == 403


def test_guard_rejects_missing_token_with_401():
    h = _FakeHandler(_headers(**{bh.TOKEN_HEADER: None}))
    result = bh.guard_request(h, TOKEN, "POST")
    assert result.ok is False
    assert result.status == 401


def test_guard_rejects_invalid_token_with_401():
    h = _FakeHandler(_headers(**{bh.TOKEN_HEADER: "mauvais-jeton"}))
    result = bh.guard_request(h, TOKEN, "POST")
    assert result.ok is False
    assert result.status == 401


def test_guard_rejects_non_json_post_with_415():
    h = _FakeHandler(_headers(**{"Content-Type": "text/plain"}))
    result = bh.guard_request(h, TOKEN, "POST")
    assert result.ok is False
    assert result.status == 415


def test_guard_checks_origin_before_token():
    # Une origine hostile est refusée en 403 même si le jeton est absent :
    # l'attaquant distant n'apprend rien sur la validité du jeton.
    h = _FakeHandler(_headers(Origin="http://evil.com", **{bh.TOKEN_HEADER: None}))
    assert bh.guard_request(h, TOKEN, "POST").status == 403


def test_guard_checks_token_before_content_type():
    # Sans jeton valide, le MIME n'est même pas évalué : 401, pas 415.
    h = _FakeHandler(
        _headers(**{bh.TOKEN_HEADER: None, "Content-Type": "text/plain"})
    )
    assert bh.guard_request(h, TOKEN, "POST").status == 401


def test_guard_tolerates_absent_origin_on_get():
    # Un GET same-origin n'émet pas d'en-tête Origin : le jeton reste la
    # défense principale, l'origine n'est vérifiée que si elle est présente.
    h = _FakeHandler(_headers(Origin=None, **{"Content-Type": None}))
    assert bh.guard_request(h, TOKEN, "GET").ok is True


def test_guard_rejects_hostile_origin_on_get():
    h = _FakeHandler(_headers(Origin="http://evil.com", **{"Content-Type": None}))
    assert bh.guard_request(h, TOKEN, "GET").status == 403


def test_guard_never_passes_when_server_token_is_empty():
    h = _FakeHandler(_headers(**{bh.TOKEN_HEADER: ""}))
    assert bh.guard_request(h, "", "POST").status == 401


# ── Transmission du jeton à l'UI ─────────────────────────────────────────────

def test_token_is_injected_into_the_head():
    html = "<!doctype html><html><head><title>x</title></head><body></body></html>"
    out = bh.inject_token_meta(html, "SECRET123")
    assert f'<meta name="{bh.TOKEN_META_NAME}" content="SECRET123">' in out
    # Injecté à l'intérieur du <head>, avant le reste de son contenu.
    assert out.index(bh.TOKEN_META_NAME) < out.index("<title>")


def test_token_injection_works_without_a_head_tag():
    out = bh.inject_token_meta("<body>hello</body>", "SECRET123")
    assert bh.TOKEN_META_NAME in out
    assert "hello" in out


def test_token_injection_escapes_html_metacharacters():
    out = bh.inject_token_meta("<head></head>", '"><script>alert(1)</script>')
    assert "<script>" not in out
    assert "&quot;&gt;" in out


def test_token_never_travels_in_the_url():
    # Le jeton est un secret : il ne doit apparaître que dans le corps HTML,
    # jamais dans une URL (historique, Referer, journaux de proxy).
    html = bh.inject_token_meta("<head></head>", "SECRET123")
    assert "?token=" not in html
    assert "&token=" not in html


# ── Intégration : vrai serveur loopback, dispatcher espionné ─────────────────


class _SpyServer:
    """Serveur loopback câblé comme la production, avec dispatcher espion."""

    def __init__(self, token):
        self.token = token
        self.dispatch_calls = []
        spy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                return

            def _serve(self, method):
                result = bh.guard_request(self, spy.token, method)
                if not result.ok:
                    bh.send_guard_error(self, result)
                    return
                body = bh.read_json_body(self) if method == "POST" else {}
                spy.dispatch_calls.append((self.path, body))
                payload = json.dumps({"ok": True}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):
                self._serve("POST")

            def do_GET(self):
                self._serve("GET")

        class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.httpd = Server(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def request(self, method="POST", path="/api/qgis/runScript", headers=None, body=b"{}"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def spy_server():
    server = _SpyServer(bh.generate_token())
    yield server
    server.close()


def _live_headers(server, **overrides):
    base = {
        "Host": f"127.0.0.1:{server.port}",
        "Origin": f"http://127.0.0.1:{server.port}",
        bh.TOKEN_HEADER: server.token,
        "Content-Type": "application/json",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def test_live_valid_request_reaches_dispatcher(spy_server):
    assert spy_server.request(headers=_live_headers(spy_server)) == 200
    assert len(spy_server.dispatch_calls) == 1


def test_live_hostile_origin_is_403_and_dispatcher_untouched(spy_server):
    status = spy_server.request(
        headers=_live_headers(spy_server, Origin="http://evil.com")
    )
    assert status == 403
    assert spy_server.dispatch_calls == []


def test_live_missing_origin_post_is_403_and_dispatcher_untouched(spy_server):
    status = spy_server.request(headers=_live_headers(spy_server, Origin=None))
    assert status == 403
    assert spy_server.dispatch_calls == []


def test_live_dns_rebinding_host_is_403_and_dispatcher_untouched(spy_server):
    status = spy_server.request(
        headers=_live_headers(
            spy_server,
            Host=f"127.0.0.1.evil.com:{spy_server.port}",
            Origin=f"http://127.0.0.1.evil.com:{spy_server.port}",
        )
    )
    assert status == 403
    assert spy_server.dispatch_calls == []


def test_live_missing_token_is_401_and_dispatcher_untouched(spy_server):
    status = spy_server.request(
        headers=_live_headers(spy_server, **{bh.TOKEN_HEADER: None})
    )
    assert status == 401
    assert spy_server.dispatch_calls == []


def test_live_invalid_token_is_401_and_dispatcher_untouched(spy_server):
    status = spy_server.request(
        headers=_live_headers(spy_server, **{bh.TOKEN_HEADER: "mauvais-jeton"})
    )
    assert status == 401
    assert spy_server.dispatch_calls == []


def test_live_text_plain_is_415_and_dispatcher_untouched(spy_server):
    status = spy_server.request(
        headers=_live_headers(spy_server, **{"Content-Type": "text/plain"}),
        body=b'{"script": "print(1)"}',
    )
    assert status == 415
    assert spy_server.dispatch_calls == []


def test_live_form_urlencoded_is_415_and_dispatcher_untouched(spy_server):
    # MIME atteignable par un <form> cross-origin sans préflight : doit tomber.
    status = spy_server.request(
        headers=_live_headers(
            spy_server, **{"Content-Type": "application/x-www-form-urlencoded"}
        ),
        body=b"script=print(1)",
    )
    assert status == 415
    assert spy_server.dispatch_calls == []


def test_live_guard_error_never_leaks_the_token(spy_server):
    conn = http.client.HTTPConnection("127.0.0.1", spy_server.port, timeout=5)
    try:
        conn.request(
            "POST",
            "/api/qgis/runScript",
            body=b"{}",
            headers=_live_headers(spy_server, **{bh.TOKEN_HEADER: "mauvais-jeton"}),
        )
        response = conn.getresponse()
        payload = response.read().decode("utf-8", "replace")
        headers = str(response.headers)
    finally:
        conn.close()
    assert spy_server.token not in payload
    assert spy_server.token not in headers
