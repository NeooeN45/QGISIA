"""
Federation d'Agents Multi-Modeles NVIDIA NIM pour QGISIA+.
Architecture: Router -> Agents Specialises -> Synthesize
"""
import json
import time
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum


class AgentType(Enum):
    """Types d'agents disponibles."""
    ROUTER = "router"
    CODE_GENERATOR = "code"
    VISION_ANALYZER = "vision"
    REASONING = "reasoning"
    SUMMARIZER = "summarizer"
    TRANSLATOR = "translator"
    SAFETY_GUARD = "safety"
    DATA_EXTRACTOR = "extractor"
    QGIS_EXPERT = "qgis_expert"


@dataclass
class AgentConfig:
    """Configuration d'un agent."""
    name: str
    agent_type: AgentType
    model: str
    temperature: float = 0.2
    max_tokens: int = 2048
    system_prompt: str = ""
    fallback_models: List[str] = field(default_factory=list)
    timeout_seconds: int = 60


@dataclass
class AgentResult:
    """Resultat d'execution."""
    agent_type: AgentType
    success: bool
    content: str
    latency_ms: float
    model_used: str
    tokens_used: Optional[int] = None
    error: Optional[str] = None


# Chaque agent pointe sur un ALIAS de QGISIA2/config/models.json (source unique de
# verite). Le gateway resout l'alias -> modele NVIDIA valide + chaine de fallback curee.
# On ne code donc plus de modeles en dur ici (fini les modeles morts).
AGENT_REGISTRY: Dict[AgentType, AgentConfig] = {
    AgentType.ROUTER: AgentConfig(
        name="Intent Router",
        agent_type=AgentType.ROUTER,
        model="intent-router",
        temperature=0.0,
        max_tokens=16,
        system_prompt="""Tu es un routeur d'intention pour un assistant SIG/QGIS. Retourne UNIQUEMENT un mot-cle parmi: CODE, VISION, REASONING, EXTRACTOR, QGIS_EXPERT, SUMMARIZER, TRANSLATOR.

Regles:
- CODE = generer du code / une action spatiale: buffer, intersection, reprojection, traitement processing, creer une couche, calcul raster, statistiques. Ex: "Cree un buffer de 500m" -> CODE ; "Calcule l'intersection des parcelles" -> CODE.
- VISION = analyser une image/carte/photo/orthophoto. Ex: "Que vois-tu sur cette carte ?" -> VISION.
- REASONING = choisir/optimiser/comparer, analyse multicritere. Ex: "Meilleure localisation pour une ecole" -> REASONING.
- EXTRACTOR = extraire des donnees structurees (coordonnees, tableau) en JSON depuis un texte.
- QGIS_EXPERT = question sur l'interface/les outils QGIS. Ex: "Comment changer le CRS dans QGIS ?" -> QGIS_EXPERT.
- SUMMARIZER = resumer un texte/rapport.
- TRANSLATOR = traduire.

Reponds UNIQUEMENT avec le mot-cle, rien d'autre.""",
        fallback_models=[],
        timeout_seconds=10
    ),

    AgentType.CODE_GENERATOR: AgentConfig(
        name="PyQGIS Code Generator",
        agent_type=AgentType.CODE_GENERATOR,
        model="code-pyqgis",
        temperature=0.1,
        max_tokens=4096,
        system_prompt="""Tu es un expert PyQGIS et GDAL. Genere du code Python propre, commente et fonctionnel. Utilise QGIS 3.x API. Inclut gestion d'erreurs try/except. Prefere processing.run(). Retourne code uniquement sans markdown.""",
        fallback_models=[],
        timeout_seconds=120
    ),

    AgentType.VISION_ANALYZER: AgentConfig(
        name="Vision Cartographique",
        agent_type=AgentType.VISION_ANALYZER,
        model="vision",
        temperature=0.2,
        max_tokens=2048,
        system_prompt="""Tu es un expert en cartographie. Analyse les cartes IGN, orthophotos, plans et images satellites. Identifie elements geographiques, legendes, echelles.""",
        fallback_models=[],
        timeout_seconds=60
    ),

    AgentType.REASONING: AgentConfig(
        name="Spatial Reasoning Expert",
        agent_type=AgentType.REASONING,
        model="reasoning",
        temperature=0.2,
        max_tokens=4096,
        system_prompt="""Tu es un expert en analyse spatiale. Capacites: analyse de proximite, calculs de densite, requetes spatiales complexes, analyses de reseaux, optimisation spatiale, analyses multicriteres. Explique ton raisonnement etape par etape.""",
        fallback_models=[],
        timeout_seconds=180
    ),

    AgentType.SUMMARIZER: AgentConfig(
        name="Content Synthesizer",
        agent_type=AgentType.SUMMARIZER,
        model="smart-default",
        temperature=0.3,
        max_tokens=1024,
        system_prompt="""Synthese concise. Extraire points cles, langage clair, maximum 3-4 phrases par concept.""",
        fallback_models=[],
        timeout_seconds=30
    ),

    AgentType.TRANSLATOR: AgentConfig(
        name="Multilingual Translator",
        agent_type=AgentType.TRANSLATOR,
        model="translate",
        temperature=0.0,
        max_tokens=2048,
        system_prompt="Traduction precise FR-EN pour documentation SIG et termes techniques. Preserve terminologie geospatiale. Reponds uniquement avec la traduction.",
        fallback_models=[],
        timeout_seconds=10
    ),

    AgentType.SAFETY_GUARD: AgentConfig(
        name="Content Safety Guard",
        agent_type=AgentType.SAFETY_GUARD,
        model="safety",
        temperature=0.0,
        max_tokens=50,
        system_prompt="""Verifie la securite du contenu. Reponds: SAFE (acceptable), UNSAFE (problem), ou CHECK (verification humaine).""",
        fallback_models=[],
        timeout_seconds=10
    ),

    AgentType.DATA_EXTRACTOR: AgentConfig(
        name="Structured Data Extractor",
        agent_type=AgentType.DATA_EXTRACTOR,
        model="extract-json",
        temperature=0.1,
        max_tokens=2048,
        system_prompt="""Extraction de donnees structurees. Retourne UNIQUEMENT du JSON valide. Pas de markdown. Exemple: {"parcelles": [{"id": "123", "surface_m2": 1500}]}""",
        fallback_models=[],
        timeout_seconds=60
    ),

    AgentType.QGIS_EXPERT: AgentConfig(
        name="QGIS Native Expert",
        agent_type=AgentType.QGIS_EXPERT,
        model="smart-default",
        temperature=0.2,
        max_tokens=2048,
        system_prompt="""Expert QGIS natif. Interface, outils, plugins, Processing framework, expressions, styles, layouts, SQL spatial. Donne instructions precises etape par etape.""",
        fallback_models=[],
        timeout_seconds=30
    )
}


class AgentFederation:
    """Federation d'agents multi-modeles."""
    
    def __init__(self, api_keys: Dict[str, str]):
        self.api_keys = api_keys
        self.history: List[Dict] = []
        
    def route_intent(self, user_query: str) -> AgentType:
        """Determine l'agent le plus adapte."""
        router_config = AGENT_REGISTRY[AgentType.ROUTER]
        
        messages = [
            {"role": "system", "content": router_config.system_prompt},
            {"role": "user", "content": f"Requete: {user_query}\n\nType d'agent:"}
        ]
        
        try:
            from llm_gateway import chat
            
            response = chat(
                model=router_config.model,
                messages=messages,
                api_keys=self.api_keys,
                stream=False,
                temperature=router_config.temperature,
                max_tokens=router_config.max_tokens,
            )
            
            intent = response["choices"][0]["message"]["content"].strip().upper()
            
            intent_map = {
                "CODE": AgentType.CODE_GENERATOR,
                "VISION": AgentType.VISION_ANALYZER,
                "REASONING": AgentType.REASONING,
                "SUMMARIZER": AgentType.SUMMARIZER,
                "TRANSLATOR": AgentType.TRANSLATOR,
                "SAFETY": AgentType.SAFETY_GUARD,
                "EXTRACTOR": AgentType.DATA_EXTRACTOR,
                "QGIS_EXPERT": AgentType.QGIS_EXPERT,
            }
            
            return intent_map.get(intent, AgentType.QGIS_EXPERT)
            
        except Exception:
            return AgentType.QGIS_EXPERT
    
    def execute_agent(
        self,
        agent_type: AgentType,
        query: str,
        context: Optional[Dict] = None,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> AgentResult:
        """Execute un agent specialise."""
        config = AGENT_REGISTRY[agent_type]
        start_time = time.time()
        
        if progress_callback:
            progress_callback(f"Agent {config.name} demarre ({config.model})")
        
        messages = [{"role": "system", "content": config.system_prompt}]
        
        if context:
            context_str = json.dumps(context, ensure_ascii=False, indent=2)
            messages.append({
                "role": "user",
                "content": f"Contexte:\n{context_str}\n\nRequete: {query}"
            })
        else:
            messages.append({"role": "user", "content": query})
        
        models_to_try = [config.model] + config.fallback_models
        
        for model in models_to_try:
            try:
                if progress_callback:
                    progress_callback(f"Utilisation de {model}...")
                
                from llm_gateway import chat
                
                response = chat(
                    model=model,
                    messages=messages,
                    api_keys=self.api_keys,
                    stream=False,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                )
                
                content = response["choices"][0]["message"]["content"]
                latency_ms = (time.time() - start_time) * 1000
                
                if progress_callback:
                    progress_callback(f"Reponse recue en {latency_ms:.0f}ms")
                
                return AgentResult(
                    agent_type=agent_type,
                    success=True,
                    content=content,
                    latency_ms=latency_ms,
                    model_used=model
                )
                
            except Exception as e:
                if progress_callback:
                    progress_callback(f"Erreur {model}: {str(e)[:50]}")
                continue
        
        return AgentResult(
            agent_type=agent_type,
            success=False,
            content="",
            latency_ms=(time.time() - start_time) * 1000,
            model_used="",
            error="All models failed"
        )
    
    def process(
        self,
        user_query: str,
        auto_route: bool = True,
        context: Optional[Dict] = None,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """Traitement complet avec routing et safety check."""
        results = {
            "query": user_query,
            "routing": None,
            "agent_results": [],
            "synthesis": None,
            "total_latency_ms": 0,
        }
        
        total_start = time.time()
        
        if auto_route:
            if progress_callback:
                progress_callback("Analyse de l'intention...")
            
            agent_type = self.route_intent(user_query)
            results["routing"] = agent_type.value
            
            if progress_callback:
                progress_callback(f"Route vers: {agent_type.value}")
        else:
            agent_type = AgentType.QGIS_EXPERT
            results["routing"] = "manual"
        
        agent_result = self.execute_agent(
            agent_type, user_query, context, progress_callback
        )
        results["agent_results"].append(agent_result)
        
        if agent_result.success and len(agent_result.content) > 100:
            if progress_callback:
                progress_callback("Verification de securite...")
            
            safety_result = self.execute_agent(
                AgentType.SAFETY_GUARD,
                agent_result.content,
                progress_callback=lambda msg: None
            )
            
            if "UNSAFE" in safety_result.content.upper():
                return {
                    **results,
                    "error": "Content flagged by safety guard",
                    "total_latency_ms": (time.time() - total_start) * 1000
                }
        
        if auto_route and agent_type == AgentType.REASONING:
            if progress_callback:
                progress_callback("Synthese du raisonnement...")
            
            synthesis_query = f"Synthetise ce raisonnement spatial en 3 points cles: {agent_result.content[:2000]}"
            synthesis_result = self.execute_agent(
                AgentType.SUMMARIZER,
                synthesis_query,
                progress_callback=lambda msg: None
            )
            results["synthesis"] = synthesis_result.content if synthesis_result.success else None
        
        results["total_latency_ms"] = (time.time() - total_start) * 1000
        
        return results


def demo_federation():
    """Demonstration de la federation d'agents."""
    print("=" * 70)
    print("FEDERATION D'AGENTS NVIDIA NIM")
    print("=" * 70)
    
    print("\nAGENTS SPECIALISES DISPONIBLES:")
    print("-" * 70)
    
    for agent_type, config in AGENT_REGISTRY.items():
        print(f"\n{agent_type.value.upper()}")
        print(f"  Nom: {config.name}")
        print(f"  Modele: {config.model}")
        print(f"  Fallbacks: {len(config.fallback_models)}")
        print(f"  Timeout: {config.timeout_seconds}s")
    
    print(f"\n{'=' * 70}")
    print(f"Total: {len(AGENT_REGISTRY)} agents avec {sum(len(c.fallback_models) for c in AGENT_REGISTRY.values())} modeles de fallback")
    print(f"{'=' * 70}")
    
    return {
        "agents_count": len(AGENT_REGISTRY),
        "total_models": sum(1 + len(c.fallback_models) for c in AGENT_REGISTRY.values()),
        "agents": {k.value: v.name for k, v in AGENT_REGISTRY.items()}
    }


if __name__ == "__main__":
    import sys
    result = demo_federation()
    print("\nDemonstration terminee")
    print(f"   Agents: {result['agents_count']}")
    print(f"   Modeles totaux: {result['total_models']}")
