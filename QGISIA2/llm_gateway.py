# -*- coding: utf-8 -*-
"""
Gateway LLM unifie (base LiteLLM).

Responsabilites:
- Resoudre un alias (`smart-default`, `vision`, ...) vers un modele concret
- Appeler litellm.completion avec fallback chain
- Streamer en SSE-friendly (generateur de chunks)
- Tracker cout / budget par jour
- Jamais persister les cles API (passees par call)

Ce module est concu pour etre portable :
- Pas d'import QGIS (utilisable en standalone FastAPI plus tard)
- Pas d'etat global (sauf budget tracker thread-safe)
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

try:
    from .llm_installer import ensure_vendor_on_path, is_vendor_ready
except ImportError:
    # Fallback pour import absolu (standalone)
    from llm_installer import ensure_vendor_on_path, is_vendor_ready

ensure_vendor_on_path()

CONFIG_PATH = Path(__file__).parent / "config" / "models.json"

# Mapping alias prefix litellm -> provider env var (indicatif)
_PROVIDER_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "nvidia_nim": "NVIDIA_API_KEY",   # NVIDIA NIM (build.nvidia.com)
    "groq": "GROQ_API_KEY",            # Groq LPU (console.groq.com)
    "cerebras": "CEREBRAS_API_KEY",    # Cerebras (cloud.cerebras.ai)
    "mistral": "MISTRAL_API_KEY",      # Mistral direct
    "ollama": None,  # pas de cle
}


@dataclass
class BudgetTracker:
    """Suivi journalier du cout, thread-safe."""
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _day: date = field(default_factory=date.today)
    _total_usd: float = 0.0
    _by_model: Dict[str, float] = field(default_factory=dict)
    _request_count: int = 0

    def _reset_if_new_day(self) -> None:
        today = date.today()
        if today != self._day:
            self._day = today
            self._total_usd = 0.0
            self._by_model.clear()
            self._request_count = 0

    def add(self, model: str, cost_usd: float) -> None:
        with self._lock:
            self._reset_if_new_day()
            self._total_usd += cost_usd
            self._by_model[model] = self._by_model.get(model, 0.0) + cost_usd
            self._request_count += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            self._reset_if_new_day()
            return {
                "day": self._day.isoformat(),
                "total_usd": round(self._total_usd, 4),
                "by_model": {k: round(v, 4) for k, v in self._by_model.items()},
                "request_count": self._request_count,
            }


_budget = BudgetTracker()


class GatewayNotReadyError(RuntimeError):
    pass


class BudgetExceededError(RuntimeError):
    pass


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"aliases": {}, "budgets": {}, "retry": {}}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def list_aliases() -> List[Dict[str, Any]]:
    cfg = load_config()
    return [
        {"alias": name, **data}
        for name, data in cfg.get("aliases", {}).items()
    ]


def resolve_alias(alias_or_model: str) -> Dict[str, Any]:
    """Retourne {primary, fallbacks, temperature, max_cost_usd}."""
    cfg = load_config()
    aliases = cfg.get("aliases", {})
    if alias_or_model in aliases:
        return aliases[alias_or_model]
    # Considere comme un nom de modele direct
    return {"primary": alias_or_model, "fallbacks": []}


def _extract_provider(model_name: str) -> str:
    """'openrouter/anthropic/claude-...' -> 'openrouter'."""
    if "/" in model_name:
        raw = model_name.split("/", 1)[0]
        # Alias nvidia -> nvidia_nim (NVIDIA NIM endpoint)
        return "nvidia_nim" if raw == "nvidia" else raw
    return ""


def build_vision_messages(prompt: str, image_b64: str, mime: str = "image/png") -> List[Dict[str, Any]]:
    """Construit des messages OpenAI multimodaux (texte + image base64) pour un VLM.

    L'image est passee en data URL ; LiteLLM la transmet au provider (NVIDIA NIM via
    openai/). Utilise par la boucle vision (critique d'un rendu cartographique).
    """
    return [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
        ],
    }]


def _build_completion_kwargs(
    model: str,
    messages: List[Dict[str, Any]],
    api_keys: Dict[str, str],
    stream: bool,
    temperature: Optional[float],
    max_tokens: Optional[int],
    tools: Optional[List[Dict[str, Any]]],
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if tools:
        kwargs["tools"] = tools
    if timeout is not None:
        # litellm propage `timeout` au client HTTP du provider.
        kwargs["timeout"] = timeout

    provider = _extract_provider(model)
    api_key = api_keys.get(provider)

    # ── NVIDIA NIM ─────────────────────────────────────────────────────────────
    # Si api_keys contient 'nvidia_nim', on route TOUJOURS vers NVIDIA NIM
    # quelle que soit la forme du modele (nvidia/..., mistralai/..., meta/...).
    # L'API NVIDIA NIM est 100 % OpenAI-compatible ; on prefixe avec 'openai/'.
    nvidia_key = api_keys.get("nvidia_nim")
    if nvidia_key:
        # Retire le prefixe nvidia_nim/ si present (ex: alias smart-default
        # resout vers "nvidia_nim/nvidia/..." -> on veut "openai/nvidia/...")
        model_for_nvidia = model.removeprefix("nvidia_nim/") if model.startswith("nvidia_nim/") else model
        kwargs["model"] = f"openai/{model_for_nvidia}"
        kwargs["api_base"] = "https://integrate.api.nvidia.com/v1"
        kwargs["api_key"] = nvidia_key
        if tools:
            kwargs["tool_choice"] = "auto"
        return kwargs

    # ── OpenRouter (fallback) ─────────────────────────────────────────────────
    # Providers non natifs routes via openrouter/...
    _OPENROUTER_PROVIDERS = {"mistralai", "anthropic", "meta-llama", "perplexity", "deepseek", "qwen", "google"}
    if provider in _OPENROUTER_PROVIDERS:
        kwargs["model"] = f"openrouter/{model}"
        openrouter_key = api_keys.get("openrouter")
        if openrouter_key:
            kwargs["api_key"] = openrouter_key
        if tools:
            kwargs["tool_choice"] = "auto"
        return kwargs

    if api_key:
        kwargs["api_key"] = api_key
    # Ollama : URL par defaut, surchargeable
    if provider == "ollama":
        kwargs["api_base"] = api_keys.get("ollama_base_url", "http://localhost:11434")
    if tools:
        kwargs["tool_choice"] = "auto"
    return kwargs


def budget_status(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Retourne l'état du budget journalier et lève si le plafond est atteint.

    Renvoie {spent_usd, daily_max_usd, percent, warning} où `warning` passe à
    True dès que le seuil `warn_at_percent` (def. 80%) est franchi.
    """
    budgets = cfg.get("budgets", {})
    daily_max = budgets.get("daily_max_usd")
    snap = _budget.snapshot()
    spent = snap["total_usd"]
    if daily_max is None:
        return {"spent_usd": spent, "daily_max_usd": None, "percent": None, "warning": False}

    percent = round((spent / daily_max) * 100, 1) if daily_max else 0.0
    if spent >= daily_max:
        raise BudgetExceededError(
            f"Budget quotidien atteint: {spent}$ / {daily_max}$"
        )
    warn_at = budgets.get("warn_at_percent", 80)
    return {
        "spent_usd": spent,
        "daily_max_usd": daily_max,
        "percent": percent,
        "warning": percent >= warn_at,
    }


def _check_budget(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Compat : vérifie le budget (lève si dépassé) et retourne le statut."""
    return budget_status(cfg)


def chat(
    model: str,
    messages: List[Dict[str, Any]],
    api_keys: Optional[Dict[str, str]] = None,
    stream: bool = False,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    """
    Chat unifie avec fallback chain.

    - stream=False : retourne dict OpenAI ChatCompletion
    - stream=True  : retourne un generateur de chunks (format OpenAI delta)
    """
    if not is_vendor_ready():
        raise GatewayNotReadyError(
            "Gateway IA non initialise. Lancez l'installation via llm_installer."
        )

    import litellm  # import tardif: vendor doit etre pret
    litellm.drop_params = True  # tolere params non-supportes par le provider
    litellm.suppress_debug_info = True

    api_keys = api_keys or {}
    cfg = load_config()
    budget = _check_budget(cfg)

    resolved = resolve_alias(model)
    candidates: List[str] = [resolved["primary"], *resolved.get("fallbacks", [])]

    retry_cfg = cfg.get("retry", {})
    max_attempts = int(retry_cfg.get("max_attempts", len(candidates)) or len(candidates))
    backoff: List[float] = retry_cfg.get("backoff_seconds", []) or []
    timeout_s = retry_cfg.get("request_timeout_seconds")
    last_error: Optional[Exception] = None

    attempts_made = 0
    for attempt, candidate in enumerate(candidates):
        if attempts_made >= max_attempts:
            break
        kwargs = _build_completion_kwargs(
            model=candidate,
            messages=messages,
            api_keys=api_keys,
            stream=stream,
            temperature=temperature if temperature is not None else resolved.get("temperature"),
            max_tokens=max_tokens,
            tools=tools,
            timeout=timeout_s,
        )
        try:
            if stream:
                return _stream_with_tracking(candidate, kwargs)
            start = time.time()
            response = litellm.completion(**kwargs)
            _track_cost(candidate, response)
            response_dict = response.model_dump() if hasattr(response, "model_dump") else dict(response)
            response_dict["_gateway"] = {
                "model_used": candidate,
                "attempt": attempt,
                "latency_ms": int((time.time() - start) * 1000),
                "budget": budget,
            }
            return response_dict
        except Exception as exc:  # pylint: disable=broad-except
            last_error = exc
            attempts_made += 1
            # Backoff avant le prochain candidat (sauf dernier essai).
            has_next = attempts_made < max_attempts and attempt < len(candidates) - 1
            if has_next and backoff:
                time.sleep(backoff[min(attempt, len(backoff) - 1)])
            continue

    raise RuntimeError(f"Tous les modeles ont echoue. Dernier: {last_error}")


def _stream_with_tracking(model: str, kwargs: Dict[str, Any]) -> Generator[Dict[str, Any], None, None]:
    """Wrappe le stream litellm pour tracer le cout a la fin."""
    import litellm  # noqa: F401
    from litellm import completion  # type: ignore

    accumulated_content = ""
    stream = completion(**kwargs)
    for chunk in stream:
        chunk_dict = chunk.model_dump() if hasattr(chunk, "model_dump") else dict(chunk)
        # Accumule le texte pour estimation cost (si provider ne le renvoie pas)
        try:
            delta = chunk_dict["choices"][0].get("delta", {}).get("content") or ""
            accumulated_content += delta
        except (KeyError, IndexError):
            pass
        yield chunk_dict

    # Fin du stream : track cost approximatif
    try:
        from litellm import completion_cost  # type: ignore
        cost = completion_cost(
            model=model,
            prompt=json.dumps(kwargs.get("messages", [])),
            completion=accumulated_content,
        )
        _budget.add(model, float(cost or 0.0))
    except Exception:  # pylint: disable=broad-except
        pass


def _track_cost(model: str, response: Any) -> None:
    try:
        from litellm import completion_cost  # type: ignore
        cost = completion_cost(completion_response=response)
        _budget.add(model, float(cost or 0.0))
    except Exception:  # pylint: disable=broad-except
        pass


def get_budget() -> Dict[str, Any]:
    cfg = load_config()
    snap = _budget.snapshot()
    snap["limits"] = cfg.get("budgets", {})
    return snap


def health() -> Dict[str, Any]:
    return {
        "vendor_ready": is_vendor_ready(),
        "config_loaded": CONFIG_PATH.exists(),
        "aliases": list(load_config().get("aliases", {}).keys()),
    }
