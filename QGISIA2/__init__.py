# -*- coding: utf-8 -*-
import threading


def _bootstrap_rag():
    """Lance l'indexation RAG en arrière-plan (non-bloquant pour QGIS)."""
    try:
        from .rag_indexer import bootstrap_knowledge_base
        result = bootstrap_knowledge_base()
        print(f"[QGISIA+] RAG ready: {result}", flush=True)
    except Exception as e:
        print(f"[QGISIA+] RAG bootstrap skip: {e}", flush=True)


def classFactory(iface):
    threading.Thread(target=_bootstrap_rag, daemon=True, name="QGISIAPlusRAG").start()
    from .geoai_assistant import GeoAIAssistant
    return GeoAIAssistant(iface)
