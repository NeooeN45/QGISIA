"""
Bridge QGIS pour la Fédération d'Agents NVIDIA NIM.
Expose les agents et workflows au frontend via QWebChannel.
"""
import json
from typing import Dict, List, Any, Optional

try:
    from geoai_assistant import BridgeQObject, BridgeSlot
except ImportError:
    # Fallback pour tests standalone
    BridgeQObject = object
    def BridgeSlot(*args, **kwargs):
        return lambda f: f

from agent_federation import AgentFederation, AgentType
from agent_workflows import WorkflowEngine, WorkflowType


class AgentBridge(BridgeQObject):
    """
    Bridge Qt pour exposer les agents au frontend.
    Intégration avec la UI QGISIA+.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.federation: Optional[AgentFederation] = None
        self.workflow_engine: Optional[WorkflowEngine] = None
        self._progress_callbacks: Dict[str, Any] = {}
    
    def setup(self, api_keys: Dict[str, str]):
        """Initialise la fédération avec les clés API."""
        self.federation = AgentFederation(api_keys)
        self.workflow_engine = WorkflowEngine(self.federation)
    
    @BridgeSlot(result=str)
    def listAgents(self) -> str:
        """Liste tous les agents disponibles."""
        from agent_federation import AGENT_REGISTRY
        
        agents = []
        for agent_type, config in AGENT_REGISTRY.items():
            agents.append({
                "type": agent_type.value,
                "name": config.name,
                "model": config.model,
                "temperature": config.temperature,
                "fallbacks": config.fallback_models,
                "timeout": config.timeout_seconds,
            })
        
        return json.dumps({
            "agents": agents,
            "total": len(agents),
            "models": sum(1 + len(a["fallbacks"]) for a in agents)
        }, ensure_ascii=False)
    
    @BridgeSlot(result=str)
    def listWorkflows(self) -> str:
        """Liste tous les workflows disponibles."""
        from agent_workflows import WORKFLOWS, WorkflowType
        
        workflows = []
        for wf_type, steps in WORKFLOWS.items():
            workflows.append({
                "type": wf_type.value,
                "steps_count": len(steps),
                "steps": [
                    {
                        "name": step.name,
                        "agent": step.agent_type.value,
                        "output_key": step.output_key,
                    }
                    for step in steps
                ]
            })
        
        return json.dumps({
            "workflows": workflows,
            "total": len(workflows),
        }, ensure_ascii=False)
    
    @BridgeSlot(str, str, result=str)
    def executeAgent(self, agent_type: str, query: str) -> str:
        """Exécute un agent spécifique."""
        if not self.federation:
            return json.dumps({"error": "Federation not initialized"})
        
        try:
            agent_enum = AgentType(agent_type)
        except ValueError:
            return json.dumps({"error": f"Unknown agent type: {agent_type}"})
        
        result = self.federation.execute_agent(agent_enum, query)
        
        return json.dumps({
            "success": result.success,
            "content": result.content,
            "latency_ms": result.latency_ms,
            "model_used": result.model_used,
            "error": result.error,
        }, ensure_ascii=False)
    
    @BridgeSlot(str, str, result=str)
    def executeWorkflow(self, workflow_type: str, query: str) -> str:
        """Exécute un workflow complet."""
        if not self.workflow_engine:
            return json.dumps({"error": "Workflow engine not initialized"})
        
        try:
            wf_enum = WorkflowType(workflow_type)
        except ValueError:
            return json.dumps({"error": f"Unknown workflow type: {workflow_type}"})
        
        # Progress callback via signal
        logs = []
        def progress(msg):
            logs.append({"time": len(logs), "message": msg})
        
        result = self.workflow_engine.execute(wf_enum, query, progress_callback=progress)
        result["progress_logs"] = logs
        
        return json.dumps(result, ensure_ascii=False)
    
    @BridgeSlot(str, result=str)
    def routeIntent(self, query: str) -> str:
        """Route une requête vers le meilleur agent."""
        if not self.federation:
            return json.dumps({"error": "Federation not initialized"})
        
        agent_type = self.federation.route_intent(query)
        agent_config = AGENT_REGISTRY.get(agent_type)
        
        return json.dumps({
            "query": query,
            "routed_to": agent_type.value,
            "agent_name": agent_config.name if agent_config else "Unknown",
            "model": agent_config.model if agent_config else "Unknown",
        }, ensure_ascii=False)
    
    @BridgeSlot(str, str, result=str)
    def smartProcess(self, query: str, context_json: str = "{}") -> str:
        """
        Traitement intelligent: route → execute → (workflow si complexe).
        Point d'entrée principal pour le frontend.
        """
        if not self.federation:
            return json.dumps({"error": "Federation not initialized"})
        
        try:
            context = json.loads(context_json) if context_json else {}
        except json.JSONDecodeError:
            context = {}
        
        logs = []
        def progress(msg):
            logs.append({"time": len(logs), "message": msg})
        
        # Détecter si c'est une requête complexe nécessitant un workflow
        complex_keywords = [
            "analyse de carte", "image", "photo", "orthophoto",
            "multi-étapes", "workflow", "séquentiel", "puis",
            "d'abord", "ensuite", "enfin"
        ]
        is_complex = any(kw in query.lower() for kw in complex_keywords)
        
        if is_complex:
            # Utiliser un workflow adapté
            if "image" in query.lower() or "carte" in query.lower():
                wf_type = WorkflowType.MAP_ANALYSIS
            elif "code" in query.lower() and "raisonnement" in query.lower():
                wf_type = WorkflowType.SPATIAL_REASONING
            else:
                wf_type = WorkflowType.CODE_FROM_DESCRIPTION
            
            progress(f"🔄 Workflow détecté: {wf_type.value}")
            result = self.workflow_engine.execute(wf_type, query, context, progress)
        else:
            # Traitement simple avec routing
            progress("🎯 Traitement simple avec routing")
            result = self.federation.process(query, auto_route=True, context=context, progress_callback=progress)
        
        result["progress_logs"] = logs
        return json.dumps(result, ensure_ascii=False)
    
    @BridgeSlot(str, result=str)
    def getAgentCatalog(self) -> str:
        """Retourne le catalogue complet des modèles NVIDIA NIM."""
        try:
            with open("QGISIA2/config/models.json", "r", encoding="utf-8") as f:
                config = json.load(f)
            
            nvidia_catalog = config.get("nvidia_nim_catalog", {})
            
            return json.dumps({
                "total_models": nvidia_catalog.get("total_models", 0),
                "base_url": nvidia_catalog.get("base_url"),
                "categories": list(nvidia_catalog.get("models", {}).keys()),
                "updated_at": nvidia_catalog.get("updated_at"),
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})


# Singleton pour l'application
_agent_bridge_instance: Optional[AgentBridge] = None


def get_agent_bridge() -> AgentBridge:
    """Retourne l'instance singleton du bridge agents."""
    global _agent_bridge_instance
    if _agent_bridge_instance is None:
        _agent_bridge_instance = AgentBridge()
    return _agent_bridge_instance


def demo_bridge():
    """Démonstration du bridge agents."""
    print("=" * 70)
    print("🌉 AGENT BRIDGE - Intégration QGISIA+")
    print("=" * 70)
    
    bridge = AgentBridge()
    
    # Test sans initialisation
    print("\n📋 Agents disponibles:")
    agents_result = bridge.listAgents()
    agents_data = json.loads(agents_result)
    print(f"   Total: {agents_data['total']} agents")
    print(f"   Modèles: {agents_data['models']} modèles (primaires + fallbacks)")
    
    print("\n🔄 Workflows disponibles:")
    wf_result = bridge.listWorkflows()
    wf_data = json.loads(wf_result)
    print(f"   Total: {wf_data['total']} workflows")
    
    print("\n" + "=" * 70)
    print("✅ Agent Bridge prêt pour intégration QWebChannel")
    print("   Slots exposés:")
    print("   - listAgents()")
    print("   - listWorkflows()")
    print("   - executeAgent(agent_type, query)")
    print("   - executeWorkflow(workflow_type, query)")
    print("   - routeIntent(query)")
    print("   - smartProcess(query, context_json)")
    print("   - getAgentCatalog()")
    print("=" * 70)
    
    return bridge


if __name__ == "__main__":
    import sys
    demo_bridge()
