"""
Workflows Multi-Agents pour QGISIA+.
Chaînage intelligent d'agents pour tâches complexes.
"""
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import json

from agent_federation import (
    AgentFederation, AgentType, AgentConfig, 
    AgentResult, AGENT_REGISTRY
)


class WorkflowType(Enum):
    """Types de workflows prédéfinis."""
    CODE_FROM_DESCRIPTION = "code_from_description"    # Description → Code
    MAP_ANALYSIS = "map_analysis"                      # Image → Analyse → Code
    SPATIAL_REASONING = "spatial_reasoning"           # Requête → Raisonnement → Code
    DATA_EXTRACTION = "data_extraction"              # Texte → JSON → Code
    TRANSLATE_AND_CODE = "translate_and_code"        # EN → FR → Code
    MULTI_ANALYSIS = "multi_analysis"                 # Multi-agents → Synthèse
    SAFETY_CHECKED_CODE = "safety_checked_code"      # Code → Vérification


@dataclass
class WorkflowStep:
    """Étape d'un workflow."""
    name: str
    agent_type: AgentType
    input_transform: Optional[Callable] = None  # Transforme l'input
    output_key: str = "result"                   # Clé pour stocker le résultat
    condition: Optional[Callable] = None        # Condition pour exécuter


# Workflows prédéfinis
WORKFLOWS: Dict[WorkflowType, List[WorkflowStep]] = {
    # 1. Génération de code depuis description
    WorkflowType.CODE_FROM_DESCRIPTION: [
        WorkflowStep(
            name="Extraction des besoins",
            agent_type=AgentType.DATA_EXTRACTOR,
            input_transform=lambda q: f"Extrait les paramètres techniques de cette requête en JSON: {q}",
            output_key="parameters"
        ),
        WorkflowStep(
            name="Génération du code",
            agent_type=AgentType.CODE_GENERATOR,
            input_transform=lambda q, ctx: f"Génère du code PyQGIS avec ces paramètres: {ctx.get('parameters', {})}\n\nRequête: {q}",
            output_key="code"
        ),
        WorkflowStep(
            name="Vérification sécurité",
            agent_type=AgentType.SAFETY_GUARD,
            input_transform=lambda q, ctx: ctx.get("code", ""),
            output_key="safety_check"
        ),
    ],
    
    # 2. Analyse de carte complète
    WorkflowType.MAP_ANALYSIS: [
        WorkflowStep(
            name="Analyse visuelle",
            agent_type=AgentType.VISION_ANALYZER,
            output_key="visual_analysis"
        ),
        WorkflowStep(
            name="Extraction des entités",
            agent_type=AgentType.DATA_EXTRACTOR,
            input_transform=lambda q, ctx: f"Extrait les entités géographiques identifiées: {ctx.get('visual_analysis', '')}",
            output_key="entities"
        ),
        WorkflowStep(
            name="Raisonnement spatial",
            agent_type=AgentType.REASONING,
            input_transform=lambda q, ctx: f"Analyse spatiale de: {ctx.get('entities', {})}\n\nObjectif: {q}",
            output_key="spatial_analysis"
        ),
        WorkflowStep(
            name="Génération du script",
            agent_type=AgentType.CODE_GENERATOR,
            input_transform=lambda q, ctx: f"Basé sur cette analyse: {ctx.get('spatial_analysis', '')}\n\nGénère le code PyQGIS pour: {q}",
            output_key="final_code"
        ),
    ],
    
    # 3. Raisonnement spatial complexe
    WorkflowType.SPATIAL_REASONING: [
        WorkflowStep(
            name="Analyse de la requête",
            agent_type=AgentType.REASONING,
            input_transform=lambda q: f"Analyse cette requête spatiale et identifie les étapes nécessaires:\n{q}",
            output_key="reasoning_steps"
        ),
        WorkflowStep(
            name="Synthèse du plan",
            agent_type=AgentType.SUMMARIZER,
            input_transform=lambda q, ctx: f"Résume ces étapes en plan d'action: {ctx.get('reasoning_steps', '')}",
            output_key="action_plan"
        ),
        WorkflowStep(
            name="Code par étape",
            agent_type=AgentType.CODE_GENERATOR,
            input_transform=lambda q, ctx: f"Implémente ce plan en PyQGIS:\n{ctx.get('action_plan', '')}\n\nRequête originale: {q}",
            output_key="step_by_step_code"
        ),
    ],
    
    # 4. Extraction et traitement de données
    WorkflowType.DATA_EXTRACTION: [
        WorkflowStep(
            name="Extraction structurée",
            agent_type=AgentType.DATA_EXTRACTOR,
            output_key="extracted_data"
        ),
        WorkflowStep(
            name="Validation du format",
            agent_type=AgentType.QGIS_EXPERT,
            input_transform=lambda q, ctx: f"Valide ce JSON pour QGIS: {ctx.get('extracted_data', {})}",
            output_key="validation"
        ),
        WorkflowStep(
            name="Génération de l'import",
            agent_type=AgentType.CODE_GENERATOR,
            input_transform=lambda q, ctx: f"Génère le code pour importer ces données: {ctx.get('extracted_data', {})}",
            output_key="import_code"
        ),
    ],
    
    # 5. Traduction et code
    WorkflowType.TRANSLATE_AND_CODE: [
        WorkflowStep(
            name="Traduction",
            agent_type=AgentType.TRANSLATOR,
            input_transform=lambda q: f"Traduis en français pour QGIS: {q}",
            output_key="french_query"
        ),
        WorkflowStep(
            name="Génération code FR",
            agent_type=AgentType.CODE_GENERATOR,
            input_transform=lambda q, ctx: f"Génère du code PyQGIS (commentaires en français): {ctx.get('french_query', q)}",
            output_key="french_code"
        ),
    ],
    
    # 6. Analyse multi-agents
    WorkflowType.MULTI_ANALYSIS: [
        # Exécution parallèle simulée
        WorkflowStep(
            name="Analyse technique",
            agent_type=AgentType.QGIS_EXPERT,
            output_key="technical"
        ),
        WorkflowStep(
            name="Analyse spatiale",
            agent_type=AgentType.REASONING,
            output_key="spatial"
        ),
        WorkflowStep(
            name="Synthèse finale",
            agent_type=AgentType.SUMMARIZER,
            input_transform=lambda q, ctx: f"Synthétise ces analyses:\nTechnique: {ctx.get('technical', '')}\nSpatiale: {ctx.get('spatial', '')}",
            output_key="synthesis"
        ),
    ],
    
    # 7. Code avec vérification safety
    WorkflowType.SAFETY_CHECKED_CODE: [
        WorkflowStep(
            name="Génération du code",
            agent_type=AgentType.CODE_GENERATOR,
            output_key="generated_code"
        ),
        WorkflowStep(
            name="Check sécurité",
            agent_type=AgentType.SAFETY_GUARD,
            input_transform=lambda q, ctx: ctx.get("generated_code", ""),
            output_key="safety_status"
        ),
        WorkflowStep(
            name="Correction si nécessaire",
            agent_type=AgentType.CODE_GENERATOR,
            input_transform=lambda q, ctx: (
                f"Corrige ce code (problème détecté: {ctx.get('safety_status', '')}):\n{ctx.get('generated_code', '')}"
                if "UNSAFE" in ctx.get("safety_status", "").upper()
                else ctx.get("generated_code", "")
            ),
            condition=lambda ctx: "UNSAFE" in ctx.get("safety_status", "").upper(),
            output_key="corrected_code"
        ),
    ],
}


class WorkflowEngine:
    """Moteur d'exécution de workflows multi-agents."""
    
    def __init__(self, federation: AgentFederation):
        self.federation = federation
        self.workflow_history: List[Dict] = []
    
    def execute(
        self,
        workflow_type: WorkflowType,
        user_query: str,
        context: Optional[Dict] = None,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Exécute un workflow complet.
        """
        workflow = WORKFLOWS.get(workflow_type, [])
        if not workflow:
            return {"error": f"Workflow {workflow_type.value} non trouvé"}
        
        results = {
            "workflow_type": workflow_type.value,
            "query": user_query,
            "steps": [],
            "context": context or {},
            "success": True,
        }
        
        if progress_callback:
            progress_callback(f"🚀 Démarrage workflow: {workflow_type.value}")
        
        # Exécution séquentielle des étapes
        for i, step in enumerate(workflow, 1):
            if progress_callback:
                progress_callback(f"  Étape {i}/{len(workflow)}: {step.name}")
            
            # Vérifier condition
            if step.condition and not step.condition(results["context"]):
                if progress_callback:
                    progress_callback(f"    ⏭️  Étape ignorée (condition non remplie)")
                continue
            
            # Transformer l'input
            if step.input_transform:
                try:
                    # Signature: (query, context) ou (query)
                    import inspect
                    sig = inspect.signature(step.input_transform)
                    if len(sig.parameters) == 2:
                        step_input = step.input_transform(user_query, results["context"])
                    else:
                        step_input = step.input_transform(user_query)
                except Exception as e:
                    step_input = f"{user_query}\n\nErreur transform: {e}"
            else:
                step_input = user_query
            
            # Exécution de l'agent
            agent_result = self.federation.execute_agent(
                step.agent_type,
                step_input,
                results["context"],
                lambda msg: progress_callback(f"    {msg}") if progress_callback else None
            )
            
            # Stocker le résultat
            results["context"][step.output_key] = agent_result.content
            results["steps"].append({
                "name": step.name,
                "agent": step.agent_type.value,
                "model": agent_result.model_used,
                "latency_ms": agent_result.latency_ms,
                "success": agent_result.success,
                "output_key": step.output_key,
            })
            
            if not agent_result.success:
                results["success"] = False
                results["error"] = f"Échec à l'étape {step.name}: {agent_result.error}"
                if progress_callback:
                    progress_callback(f"    ❌ Échec: {agent_result.error}")
                break
        
        if progress_callback and results["success"]:
            progress_callback(f"✅ Workflow terminé avec succès")
        
        self.workflow_history.append(results)
        return results
    
    def execute_parallel(
        self,
        agents: List[AgentType],
        user_query: str,
        context: Optional[Dict] = None,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Exécute plusieurs agents en parallèle et synthétise.
        """
        if progress_callback:
            progress_callback(f"🔄 Exécution parallèle de {len(agents)} agents...")
        
        # Pour l'instant, exécution séquentielle (threading possible)
        results = {}
        for agent_type in agents:
            agent_config = AGENT_REGISTRY[agent_type]
            if progress_callback:
                progress_callback(f"  → {agent_config.name}")
            
            result = self.federation.execute_agent(
                agent_type, user_query, context
            )
            results[agent_type.value] = {
                "content": result.content,
                "model": result.model_used,
                "latency_ms": result.latency_ms,
                "success": result.success,
            }
        
        # Synthèse automatique
        if progress_callback:
            progress_callback("📝 Synthèse des résultats...")
        
        synthesis_input = "\n\n".join([
            f"[{k}]:\n{v['content'][:500]}"
            for k, v in results.items() if v["success"]
        ])
        
        synthesis_result = self.federation.execute_agent(
            AgentType.SUMMARIZER,
            f"Synthétise ces analyses en une réponse cohérente:\n\n{synthesis_input}",
            progress_callback=lambda x: None
        )
        
        return {
            "parallel_results": results,
            "synthesis": synthesis_result.content if synthesis_result.success else None,
            "success": any(v["success"] for v in results.values()),
        }


def demo_workflows():
    """Démonstration des workflows disponibles."""
    print("=" * 70)
    print("🔄 WORKFLOWS MULTI-AGENTS DISPONIBLES")
    print("=" * 70)
    
    for workflow_type, steps in WORKFLOWS.items():
        print(f"\n📦 {workflow_type.value.upper()}")
        print("-" * 50)
        for i, step in enumerate(steps, 1):
            agent_config = AGENT_REGISTRY[step.agent_type]
            print(f"  {i}. {step.name}")
            print(f"     Agent: {agent_config.name}")
            print(f"     Modèle: {agent_config.model}")
            if step.condition:
                print(f"     Condition: oui")
        print()
    
    print(f"{'=' * 70}")
    print(f"Total: {len(WORKFLOWS)} workflows avec {sum(len(s) for s in WORKFLOWS.values())} étapes")
    print(f"{'=' * 70}")
    
    return {
        "workflows_count": len(WORKFLOWS),
        "total_steps": sum(len(s) for s in WORKFLOWS.values()),
        "workflows": list(WORKFLOWS.keys())
    }


if __name__ == "__main__":
    import sys
    result = demo_workflows()
    print(f"\n✅ {result['workflows_count']} workflows disponibles")
