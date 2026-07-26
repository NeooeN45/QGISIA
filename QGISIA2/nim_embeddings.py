# -*- coding: utf-8 -*-
"""
nim_embeddings — Embeddings sémantiques via NVIDIA NIM (API OpenAI-compatible).

Module PUR (stdlib uniquement : urllib), sans dépendance QGIS/torch. Permet au
RAG d'utiliser de vrais embeddings denses (sémantiques) au lieu du TF-IDF par
mots-clés, sans installer sentence-transformers/torch côté plugin.

Endpoint : https://integrate.api.nvidia.com/v1/embeddings (Bearer NVIDIA_API_KEY)
Modèle par défaut : nvidia/nv-embedqa-e5-v5 (1024 dimensions).

L'API NIM exige `input_type` ∈ {"query", "passage"} (asymétrie requête/document).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import List, Optional

NIM_EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"
DEFAULT_MODEL = "nvidia/nv-embedqa-e5-v5"
EMBED_DIM = 1024
DEFAULT_TIMEOUT = 30


class EmbeddingError(RuntimeError):
    """Échec d'appel à l'API d'embeddings NIM."""


def embed_texts(
    texts: List[str],
    api_key: str,
    input_type: str = "passage",
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
) -> List[List[float]]:
    """Retourne un vecteur d'embedding par texte. Lève EmbeddingError sur échec.

    input_type : "passage" pour indexer un document, "query" pour une requête.
    """
    if not api_key:
        raise EmbeddingError("Clé API NVIDIA NIM manquante pour les embeddings.")
    if not texts:
        return []

    payload = {
        "input": texts,
        "model": model,
        "input_type": input_type,
        "encoding_format": "float",
    }
    req = urllib.request.Request(
        NIM_EMBED_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise EmbeddingError(f"HTTP {exc.code} embeddings NIM: {detail}") from exc
    except Exception as exc:  # réseau, timeout, JSON…
        raise EmbeddingError(f"Échec embeddings NIM: {exc}") from exc

    items = data.get("data")
    if not isinstance(items, list) or len(items) != len(texts):
        raise EmbeddingError("Réponse embeddings NIM invalide.")
    # L'API peut renvoyer les items dans le désordre → trier par 'index'.
    items_sorted = sorted(items, key=lambda it: it.get("index", 0))
    return [it["embedding"] for it in items_sorted]


def embed_query(text: str, api_key: str, model: str = DEFAULT_MODEL,
                timeout: float = DEFAULT_TIMEOUT) -> List[float]:
    """Embedding d'une requête (input_type='query')."""
    return embed_texts([text], api_key, input_type="query", model=model, timeout=timeout)[0]


def is_configured(api_key: Optional[str]) -> bool:
    return bool(api_key)
