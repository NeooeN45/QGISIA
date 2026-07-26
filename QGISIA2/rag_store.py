# -*- coding: utf-8 -*-
"""
QGISIA+ — RAG Vector Store (Sprint 3).

Architecture hybride (par ordre de priorité) :
- Embeddings sémantiques : NVIDIA NIM (nim_embeddings) si une clé API est
  configurée — index dense en mémoire + cosine, persisté, sans torch.
- Qdrant local           : si la lib qdrant_client est installée.
- Fallback complet       : TF-IDF Python pur (mots-clés), toujours dispo, hors-ligne.

Aucune dépendance QGIS directe — utilisable standalone et dans QGIS.
Compatible Python 3.9+.

Collections prédéfinies :
    "pyqgis_docs"   → documentation PyQGIS (API, exemples)
    "project_layers" → métadonnées couches du projet courant
    "user_notes"    → notes et contexte ajoutés par l'utilisateur
    "web_snippets"  → pages web / docs externes indexées
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

PLUGIN_DIR = Path(__file__).parent
RAG_DIR = PLUGIN_DIR / "data" / "rag"
RAG_DIR.mkdir(parents=True, exist_ok=True)

COLLECTIONS = ["pyqgis_docs", "project_layers", "user_notes", "web_snippets"]
MAX_CHUNK_SIZE = 800     # tokens approx
CHUNK_OVERLAP = 100
TOP_K_DEFAULT = 5


# ── Structures de données ─────────────────────────────────────────────────────

@dataclass
class Document:
    doc_id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    collection: str = "user_notes"
    created_at: float = field(default_factory=time.time)
    chunk_index: int = 0
    source_url: Optional[str] = None


@dataclass
class SearchResult:
    doc_id: str
    content: str
    score: float
    metadata: Dict[str, Any]
    collection: str
    source_url: Optional[str] = None


# ── Chunker ──────────────────────────────────────────────────────────────────

def chunk_text(text: str, max_size: int = MAX_CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Découpe un texte en chunks chevauchants."""
    words = text.split()
    if len(words) <= max_size:
        return [text]
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + max_size, len(words))
        chunks.append(" ".join(words[start:end]))
        start += max_size - overlap
    return chunks


# ── Embeddings légers (TF-IDF + cosine) ──────────────────────────────────────

class TFIDFIndex:
    """
    Index TF-IDF Python pur.
    Fallback quand sentence-transformers ou Qdrant ne sont pas disponibles.
    Recherche sémantique légère par similarité cosine sur TF-IDF.
    """

    def __init__(self) -> None:
        self._docs: Dict[str, Document] = {}
        self._tf_idf: Dict[str, Dict[str, float]] = {}  # doc_id → {term: score}
        self._idf: Dict[str, float] = {}
        self._lock = threading.RLock()

    def add(self, doc: Document) -> None:
        with self._lock:
            self._docs[doc.doc_id] = doc
            tokens = self._tokenize(doc.content)
            tf = self._compute_tf(tokens)
            self._tf_idf[doc.doc_id] = tf
            self._update_idf()

    def remove(self, doc_id: str) -> bool:
        with self._lock:
            if doc_id in self._docs:
                del self._docs[doc_id]
                del self._tf_idf[doc_id]
                self._update_idf()
                return True
        return False

    def search(
        self,
        query: str,
        top_k: int = TOP_K_DEFAULT,
        collection: Optional[str] = None,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        with self._lock:
            query_tokens = self._tokenize(query)
            query_tf = self._compute_tf(query_tokens)
            query_vec = {t: tf * self._idf.get(t, 0.0) for t, tf in query_tf.items()}

            scored: List[Tuple[float, Document]] = []
            for doc_id, doc in self._docs.items():
                if collection and doc.collection != collection:
                    continue
                if filter_metadata:
                    if not all(doc.metadata.get(k) == v for k, v in filter_metadata.items()):
                        continue
                doc_vec = {t: tf * self._idf.get(t, 0.0) for t, tf in self._tf_idf.get(doc_id, {}).items()}
                score = self._cosine(query_vec, doc_vec)
                if score > 0:
                    scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SearchResult(
                doc_id=d.doc_id, content=d.content, score=s,
                metadata=d.metadata, collection=d.collection,
                source_url=d.source_url,
            )
            for s, d in scored[:top_k]
        ]

    def count(self, collection: Optional[str] = None) -> int:
        with self._lock:
            if collection:
                return sum(1 for d in self._docs.values() if d.collection == collection)
            return len(self._docs)

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"\b[a-zA-ZÀ-ÿ_]{2,}\b", text.lower())

    def _compute_tf(self, tokens: List[str]) -> Dict[str, float]:
        if not tokens:
            return {}
        freq: Dict[str, int] = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1
        total = len(tokens)
        return {t: c / total for t, c in freq.items()}

    def _update_idf(self) -> None:
        n_docs = max(len(self._docs), 1)
        term_doc_count: Dict[str, int] = {}
        for tf in self._tf_idf.values():
            for term in tf:
                term_doc_count[term] = term_doc_count.get(term, 0) + 1
        self._idf = {
            term: math.log(n_docs / (count + 1)) + 1
            for term, count in term_doc_count.items()
        }

    @staticmethod
    def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
        common = set(a) & set(b)
        if not common:
            return 0.0
        dot = sum(a[t] * b[t] for t in common)
        norm_a = math.sqrt(sum(v * v for v in a.values()))
        norm_b = math.sqrt(sum(v * v for v in b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


# ── Store principal ───────────────────────────────────────────────────────────

class RAGStore:
    """
    Store RAG hybride pour QGISIA+.

    Stratégie :
    1. Tente d'utiliser Qdrant local (fichiers dans rag/qdrant/)
    2. Fallback sur TF-IDF si Qdrant absent
    3. Persiste les documents dans rag/documents.json (toujours)
    """

    def __init__(self) -> None:
        self._index = TFIDFIndex()
        self._qdrant_client: Optional[Any] = None
        self._use_qdrant = False
        self._lock = threading.RLock()
        self._docs_file = RAG_DIR / "documents.json"
        # Backend embeddings sémantiques (NVIDIA NIM). Index dense en mémoire,
        # persisté, indépendant de Qdrant/torch. Inactif tant que non configuré.
        self._embed_fn: Optional[Callable[[List[str], str], List[List[float]]]] = None
        self._embeddings: Dict[str, List[float]] = {}
        self._emb_file = RAG_DIR / "embeddings.json"
        self._load_persisted()
        self._load_embeddings()
        self._try_init_qdrant()

    # ── Configuration du backend embeddings sémantique (NIM) ───────────────────

    def configure(self, api_key: Optional[str], model: Optional[str] = None) -> bool:
        """Active les embeddings sémantiques via NVIDIA NIM si une clé est fournie.

        Retourne True si le backend sémantique est actif. Idempotent.
        L'indexation des documents déjà présents se fait paresseusement à la
        prochaine recherche (ou via reindex_embeddings()).
        """
        if not api_key:
            self._embed_fn = None
            return False
        try:
            from . import nim_embeddings
        except ImportError:  # pragma: no cover - fallback standalone
            import nim_embeddings  # type: ignore[no-redef]

        mdl = model or nim_embeddings.DEFAULT_MODEL

        def _embed(texts: List[str], input_type: str) -> List[List[float]]:
            return nim_embeddings.embed_texts(texts, api_key, input_type=input_type, model=mdl)

        self._embed_fn = _embed  # type: ignore[assignment]
        return True

    @property
    def semantic_enabled(self) -> bool:
        return self._embed_fn is not None

    def reindex_embeddings(self) -> int:
        """Calcule les embeddings manquants pour les documents déjà indexés."""
        if not self._embed_fn:
            return 0
        with self._lock:
            missing = [d for did, d in self._index._docs.items() if did not in self._embeddings]
        count = 0
        for doc in missing:
            if self._embed_document(doc):
                count += 1
        if count:
            self._persist_embeddings()
        return count

    def _try_init_qdrant(self) -> None:
        """Tente d'initialiser Qdrant local (mode fichier, sans serveur)."""
        try:
            from qdrant_client import QdrantClient  # type: ignore
            from qdrant_client.models import Distance, VectorParams  # type: ignore
            qdrant_path = str(RAG_DIR / "qdrant")
            self._qdrant_client = QdrantClient(path=qdrant_path)
            for col in COLLECTIONS:
                existing = [c.name for c in self._qdrant_client.get_collections().collections]
                if col not in existing:
                    self._qdrant_client.create_collection(
                        collection_name=col,
                        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                    )
            self._use_qdrant = True
        except ImportError:
            self._use_qdrant = False
        except Exception:
            self._use_qdrant = False

    # ── API publique ──────────────────────────────────────────────────────────

    def add_document(
        self,
        content: str,
        collection: str = "user_notes",
        metadata: Optional[Dict[str, Any]] = None,
        source_url: Optional[str] = None,
        auto_chunk: bool = True,
    ) -> List[str]:
        """
        Indexe un document (avec chunking automatique).
        Retourne la liste des doc_id créés.
        """
        if collection not in COLLECTIONS:
            collection = "user_notes"
        chunks = chunk_text(content) if auto_chunk else [content]
        doc_ids = []

        for i, chunk in enumerate(chunks):
            doc_id = str(uuid.uuid4())[:12]
            doc = Document(
                doc_id=doc_id,
                content=chunk,
                metadata=metadata or {},
                collection=collection,
                chunk_index=i,
                source_url=source_url,
            )
            with self._lock:
                self._index.add(doc)
                if self._use_qdrant:
                    self._add_to_qdrant(doc)
            if self._embed_fn:
                self._embed_document(doc)
            doc_ids.append(doc_id)

        self._persist()
        if self._embed_fn:
            self._persist_embeddings()
        return doc_ids

    def search(
        self,
        query: str,
        top_k: int = TOP_K_DEFAULT,
        collection: Optional[str] = None,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Recherche dans le store.

        Priorité : (1) embeddings sémantiques NIM si configurés, (2) Qdrant,
        (3) repli TF-IDF par mots-clés (toujours disponible, hors-ligne).
        """
        if self._embed_fn:
            try:
                semantic = self._search_semantic(query, top_k, collection, filter_metadata)
                if semantic:
                    return semantic
            except Exception:
                pass  # repli silencieux sur les backends suivants
        if self._use_qdrant:
            try:
                return self._search_qdrant(query, top_k, collection, filter_metadata)
            except Exception:
                pass
        return self._index.search(query, top_k, collection, filter_metadata)

    def delete_document(self, doc_id: str) -> bool:
        with self._lock:
            removed = self._index.remove(doc_id)
            self._embeddings.pop(doc_id, None)
        if removed:
            self._persist()
            self._persist_embeddings()
        return removed

    def delete_collection(self, collection: str) -> int:
        with self._lock:
            to_delete = [
                doc_id for doc_id, doc in self._index._docs.items()
                if doc.collection == collection
            ]
            for doc_id in to_delete:
                self._index.remove(doc_id)
                self._embeddings.pop(doc_id, None)
        self._persist()
        self._persist_embeddings()
        return len(to_delete)

    def count(self, collection: Optional[str] = None) -> int:
        return self._index.count(collection)

    def stats(self) -> Dict[str, Any]:
        if self._embed_fn:
            backend = "nim-embeddings"
        elif self._use_qdrant:
            backend = "qdrant"
        else:
            backend = "tfidf"
        return {
            "backend": backend,
            "semantic_enabled": self.semantic_enabled,
            "embedded_documents": len(self._embeddings),
            "total_documents": self._index.count(),
            "by_collection": {col: self._index.count(col) for col in COLLECTIONS},
            "rag_dir": str(RAG_DIR),
        }

    def get_context_for_prompt(self, query: str, top_k: int = 5, collection: Optional[str] = None) -> str:
        """
        Retourne un bloc de contexte RAG formaté pour injection dans le prompt.
        """
        results = self.search(query, top_k=top_k, collection=collection)
        if not results:
            return ""
        lines = ["## Contexte RAG QGISIA+"]
        for i, r in enumerate(results, 1):
            src = f" *(source: {r.source_url})*" if r.source_url else ""
            lines.append(f"\n### [{i}] {r.metadata.get('title', r.collection)}{src}")
            lines.append(r.content[:600])
        return "\n".join(lines)

    # ── Embeddings sémantiques (NIM) ───────────────────────────────────────────

    def _embed_document(self, doc: Document) -> bool:
        """Calcule et stocke l'embedding d'un document. False si échec."""
        if not self._embed_fn:
            return False
        try:
            vec = self._embed_fn([doc.content], "passage")[0]
        except Exception:
            return False
        with self._lock:
            self._embeddings[doc.doc_id] = vec
        return True

    def _search_semantic(
        self, query: str, top_k: int, collection: Optional[str], filter_meta: Optional[Dict]
    ) -> List[SearchResult]:
        """Recherche par similarité cosine sur les embeddings denses NIM."""
        if not self._embed_fn:
            return []
        # Indexation paresseuse des documents non encore vectorisés.
        with self._lock:
            pending = [d for did, d in self._index._docs.items() if did not in self._embeddings]
        if pending:
            for doc in pending:
                self._embed_document(doc)
            self._persist_embeddings()

        query_vec = self._embed_fn([query], "query")[0]

        with self._lock:
            scored: List[Tuple[float, Document]] = []
            for doc_id, doc in self._index._docs.items():
                if collection and doc.collection != collection:
                    continue
                if filter_meta and not all(doc.metadata.get(k) == v for k, v in filter_meta.items()):
                    continue
                vec = self._embeddings.get(doc_id)
                if not vec:
                    continue
                score = self._cosine_dense(query_vec, vec)
                if score > 0:
                    scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SearchResult(
                doc_id=d.doc_id, content=d.content, score=s,
                metadata=d.metadata, collection=d.collection, source_url=d.source_url,
            )
            for s, d in scored[:top_k]
        ]

    @staticmethod
    def _cosine_dense(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _persist_embeddings(self) -> None:
        try:
            with self._lock:
                snapshot = dict(self._embeddings)
            self._emb_file.write_text(
                json.dumps(snapshot, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _load_embeddings(self) -> None:
        if not self._emb_file.exists():
            return
        try:
            raw = json.loads(self._emb_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._embeddings = {k: list(v) for k, v in raw.items()}
        except Exception:
            self._embeddings = {}

    # ── Qdrant helpers ────────────────────────────────────────────────────────

    def _add_to_qdrant(self, doc: Document) -> None:
        from qdrant_client.models import PointStruct  # type: ignore
        vec = self._embed(doc.content)
        self._qdrant_client.upsert(
            collection_name=doc.collection,
            points=[PointStruct(
                id=abs(hash(doc.doc_id)) % (2**31),
                vector=vec,
                payload={"doc_id": doc.doc_id, "content": doc.content, **doc.metadata},
            )],
        )

    def _search_qdrant(
        self, query: str, top_k: int, collection: Optional[str], filter_meta: Optional[Dict]
    ) -> List[SearchResult]:
        from qdrant_client.models import Filter, FieldCondition, MatchValue  # type: ignore
        vec = self._embed(query)
        collections_to_search = [collection] if collection else COLLECTIONS
        all_results: List[SearchResult] = []

        for col in collections_to_search:
            qfilter = None
            if filter_meta:
                conditions = [
                    FieldCondition(key=k, match=MatchValue(value=v))
                    for k, v in filter_meta.items()
                ]
                qfilter = Filter(must=conditions)
            hits = self._qdrant_client.search(
                collection_name=col,
                query_vector=vec,
                limit=top_k,
                query_filter=qfilter,
            )
            for hit in hits:
                all_results.append(SearchResult(
                    doc_id=hit.payload.get("doc_id", ""),
                    content=hit.payload.get("content", ""),
                    score=hit.score,
                    metadata={k: v for k, v in hit.payload.items() if k not in ("doc_id", "content")},
                    collection=col,
                ))

        all_results.sort(key=lambda x: x.score, reverse=True)
        return all_results[:top_k]

    def _embed(self, text: str) -> List[float]:
        """Embedding : sentence-transformers si dispo, sinon TF-IDF → vecteur sparse."""
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            if not hasattr(self, "_st_model"):
                self._st_model = SentenceTransformer("all-MiniLM-L6-v2")
            return self._st_model.encode(text).tolist()
        except ImportError:
            return self._tfidf_to_dense(text, dim=384)

    def _tfidf_to_dense(self, text: str, dim: int = 384) -> List[float]:
        """Projette TF-IDF vers un vecteur dense de taille dim (hash trick)."""
        tokens = re.findall(r"\b[a-zA-ZÀ-ÿ_]{2,}\b", text.lower())
        vec = [0.0] * dim
        for token in tokens:
            idx = hash(token) % dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    # ── Persistance JSON ──────────────────────────────────────────────────────

    def _persist(self) -> None:
        try:
            with self._lock:
                docs = {
                    doc_id: asdict(doc)
                    for doc_id, doc in self._index._docs.items()
                }
            self._docs_file.write_text(
                json.dumps(docs, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _load_persisted(self) -> None:
        if not self._docs_file.exists():
            return
        try:
            raw = json.loads(self._docs_file.read_text(encoding="utf-8"))
            for doc_id, data in raw.items():
                doc = Document(**data)
                self._index.add(doc)
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────────────────────
_store_instance: Optional[RAGStore] = None
_store_lock = threading.Lock()


def get_store() -> RAGStore:
    global _store_instance
    with _store_lock:
        if _store_instance is None:
            _store_instance = RAGStore()
    return _store_instance
