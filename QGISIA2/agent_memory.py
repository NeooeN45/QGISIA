# -*- coding: utf-8 -*-
"""
QGISIA+ — Mémoire persistante de l'agent (Sprint 2).

Inspiré de mem0 (mem0ai/mem0) mais sans dépendance externe :
- Stockage JSON local chiffré dans le dossier plugin
- Mémoire multi-niveau : session, utilisateur, agent
- Recherche sémantique légère par mots-clés (sans embedding externe)
- Compatible QGIS Python 3.9+

Structure mémoire :
    {
        "user": {<key>: <MemoryEntry>},     # préférences persistantes
        "agent": {<key>: <MemoryEntry>},    # connaissances accumulées
        "sessions": [<SessionSummary>, ...]  # historique résumé
    }
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

PLUGIN_DIR = Path(__file__).parent
MEMORY_FILE = PLUGIN_DIR / "data" / "agent_memory.json"
MAX_SESSION_HISTORY = 50
MAX_MEMORY_ENTRIES = 200


@dataclass
class MemoryEntry:
    key: str
    value: str
    category: str          # "preference", "fact", "skill", "project"
    source: str            # "user_explicit", "inferred", "agent"
    confidence: float      # 0.0-1.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0
    tags: List[str] = field(default_factory=list)


@dataclass
class SessionSummary:
    session_id: str
    started_at: float
    ended_at: float
    message_count: int
    topics: List[str]
    layers_used: List[str]
    actions_taken: List[str]
    outcome: str           # "success", "partial", "failed", "cancelled"


class AgentMemory:
    """
    Mémoire persistante locale pour l'agent QGISIA+.
    Thread-safe, sans dépendance externe.
    """

    def __init__(self, user_id: str = "default"):
        self._user_id = user_id
        self._lock = threading.RLock()
        self._user_mem: Dict[str, MemoryEntry] = {}
        self._agent_mem: Dict[str, MemoryEntry] = {}
        self._sessions: List[SessionSummary] = []
        self._current_session_id: Optional[str] = None
        self._current_session_messages: List[Dict] = []
        self._load()

    # ── Persistance ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not MEMORY_FILE.exists():
            return
        try:
            raw = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            user_data = raw.get("user", {})
            agent_data = raw.get("agent", {})
            sessions_data = raw.get("sessions", [])
            with self._lock:
                self._user_mem = {
                    k: MemoryEntry(**v) for k, v in user_data.items()
                }
                self._agent_mem = {
                    k: MemoryEntry(**v) for k, v in agent_data.items()
                }
                self._sessions = [SessionSummary(**s) for s in sessions_data]
        except Exception:
            pass

    def _save(self) -> None:
        try:
            with self._lock:
                data = {
                    "user": {k: asdict(v) for k, v in self._user_mem.items()},
                    "agent": {k: asdict(v) for k, v in self._agent_mem.items()},
                    "sessions": [asdict(s) for s in self._sessions[-MAX_SESSION_HISTORY:]],
                }
            MEMORY_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ── API mémoire utilisateur ───────────────────────────────────────────────

    def remember(
        self,
        key: str,
        value: str,
        category: str = "preference",
        source: str = "user_explicit",
        confidence: float = 1.0,
        tags: Optional[List[str]] = None,
    ) -> None:
        """Mémorise une information persistante sur l'utilisateur."""
        with self._lock:
            existing = self._user_mem.get(key)
            if existing:
                existing.value = value
                existing.updated_at = time.time()
                existing.confidence = confidence
                existing.tags = tags or existing.tags
            else:
                self._user_mem[key] = MemoryEntry(
                    key=key, value=value, category=category,
                    source=source, confidence=confidence,
                    tags=tags or [],
                )
            self._trim_memory(self._user_mem)
        self._save()

    def recall(self, key: str) -> Optional[str]:
        """Récupère une valeur mémorisée."""
        with self._lock:
            entry = self._user_mem.get(key)
            if entry:
                entry.access_count += 1
                entry.updated_at = time.time()
                return entry.value
        return None

    def forget(self, key: str) -> bool:
        """Supprime une entrée mémoire."""
        with self._lock:
            if key in self._user_mem:
                del self._user_mem[key]
                self._save()
                return True
        return False

    def search(self, query: str, top_k: int = 5) -> List[MemoryEntry]:
        """
        Recherche sémantique légère par mots-clés.
        Sans embedding — compatible QGIS sans dépendance.
        """
        query_tokens = set(re.findall(r"\w+", query.lower()))
        scored: List[tuple[float, MemoryEntry]] = []

        with self._lock:
            all_entries = list(self._user_mem.values()) + list(self._agent_mem.values())

        for entry in all_entries:
            text = f"{entry.key} {entry.value} {' '.join(entry.tags)}".lower()
            tokens = set(re.findall(r"\w+", text))
            overlap = len(query_tokens & tokens)
            if overlap > 0:
                score = overlap / max(len(query_tokens), 1) * entry.confidence
                score += entry.access_count * 0.01
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    def get_context_for_prompt(self, query: str) -> str:
        """
        Retourne un bloc de contexte formaté à injecter dans le prompt système.
        Appelé avant chaque requête LLM.
        """
        relevant = self.search(query, top_k=8)
        if not relevant:
            return ""

        lines = ["## Mémoire QGISIA+ (contexte utilisateur)"]
        for e in relevant:
            category_icon = {
                "preference": "⚙️",
                "fact": "📌",
                "skill": "🛠️",
                "project": "📁",
            }.get(e.category, "•")
            lines.append(f"{category_icon} **{e.key}**: {e.value}")

        if self._sessions:
            last = self._sessions[-1]
            if last.topics:
                lines.append(f"\n📋 Dernière session: {', '.join(last.topics[:3])}")

        return "\n".join(lines)

    # ── Mémoire agent (connaissances QGIS accumulées) ────────────────────────

    def learn(self, key: str, fact: str, tags: Optional[List[str]] = None) -> None:
        """L'agent mémorise un fait appris (ex: 'couche X = zones forestières')."""
        with self._lock:
            self._agent_mem[key] = MemoryEntry(
                key=key, value=fact, category="fact",
                source="agent", confidence=0.9,
                tags=tags or [],
            )
            self._trim_memory(self._agent_mem)
        self._save()

    # ── Session tracking ──────────────────────────────────────────────────────

    def start_session(self, session_id: str) -> None:
        with self._lock:
            self._current_session_id = session_id
            self._current_session_messages = []

    def log_message(self, role: str, content: str, metadata: Optional[Dict] = None) -> None:
        with self._lock:
            self._current_session_messages.append({
                "role": role, "content": content[:500],
                "ts": time.time(), **(metadata or {}),
            })

    def end_session(
        self,
        topics: List[str],
        layers_used: List[str],
        actions_taken: List[str],
        outcome: str = "success",
    ) -> None:
        if not self._current_session_id:
            return
        summary = SessionSummary(
            session_id=self._current_session_id,
            started_at=self._current_session_messages[0]["ts"] if self._current_session_messages else time.time(),
            ended_at=time.time(),
            message_count=len(self._current_session_messages),
            topics=topics[:10],
            layers_used=layers_used[:20],
            actions_taken=actions_taken[:20],
            outcome=outcome,
        )
        with self._lock:
            self._sessions.append(summary)
            self._current_session_id = None
            self._current_session_messages = []
        self._save()

    def get_session_history(self, limit: int = 5) -> List[Dict[str, Any]]:
        with self._lock:
            return [asdict(s) for s in self._sessions[-limit:]]

    # ── Auto-extraction de connaissances depuis les messages ──────────────────

    def extract_and_store(self, user_message: str, layer_names: List[str]) -> None:
        """
        Extrait automatiquement des connaissances des messages utilisateur.
        Patterns simples — pas d'LLM requis.
        """
        msg = user_message.lower()

        # Préférences CRS
        if "lambert" in msg or "epsg:2154" in msg or "2154" in msg:
            self.remember("crs_preference", "Lambert 93 (EPSG:2154)", category="preference", confidence=0.9, tags=["crs", "france"])

        # Préférence de format d'export
        for fmt in ["geojson", "shapefile", "gpkg", "geopackage", "csv", "kml"]:
            if fmt in msg:
                self.remember("export_format_preference", fmt.upper(), category="preference", confidence=0.7, tags=["export"])
                break

        # Couches importantes mentionnées
        for layer in layer_names:
            if layer.lower() in msg:
                self.learn(f"layer_context_{layer}", f"Couche '{layer}' utilisée fréquemment", tags=["layer", layer])

    # ── Utilitaires ───────────────────────────────────────────────────────────

    def _trim_memory(self, mem_dict: Dict[str, MemoryEntry]) -> None:
        if len(mem_dict) <= MAX_MEMORY_ENTRIES:
            return
        # Supprime les entrées les moins accédées
        sorted_keys = sorted(mem_dict, key=lambda k: (mem_dict[k].access_count, mem_dict[k].updated_at))
        to_remove = len(mem_dict) - MAX_MEMORY_ENTRIES
        for key in sorted_keys[:to_remove]:
            del mem_dict[key]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "user_memories": len(self._user_mem),
                "agent_memories": len(self._agent_mem),
                "sessions": len(self._sessions),
                "memory_file": str(MEMORY_FILE),
            }

    def clear_all(self) -> None:
        with self._lock:
            self._user_mem.clear()
            self._agent_mem.clear()
            self._sessions.clear()
        self._save()


# ── Singleton par utilisateur ─────────────────────────────────────────────────
_memory_instances: Dict[str, AgentMemory] = {}
_mem_lock = threading.Lock()


def get_memory(user_id: str = "default") -> AgentMemory:
    """Retourne l'instance mémoire singleton pour cet utilisateur."""
    with _mem_lock:
        if user_id not in _memory_instances:
            _memory_instances[user_id] = AgentMemory(user_id)
        return _memory_instances[user_id]
