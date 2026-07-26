# Documentation — QGISIA+ / GeoSylva AI

Index de la documentation, classée par thème.

## 📐 architecture/
Conception technique du plugin et du backend agentique.
- [AGENTIC_BACKEND.md](architecture/AGENTIC_BACKEND.md) — vue d'ensemble du backend agentique
- [AGENT_GRAPH.md](architecture/AGENT_GRAPH.md) — graphe d'orchestration des agents
- [MCP_SERVER.md](architecture/MCP_SERVER.md) — serveur MCP (70+ outils exposés)
- [API_DOCUMENTATION.md](architecture/API_DOCUMENTATION.md) — endpoints HTTP du bridge
- [SPRINT_1_ARCHITECTURE.md](architecture/SPRINT_1_ARCHITECTURE.md) — décisions d'architecture sprint 1

## 🔒 security/
Modèle de menace et contrat de sécurité du bridge local.
- [THREAT_MODEL.md](security/THREAT_MODEL.md) — modèle de menace avant/après, attaquants couverts, limites assumées
- [BRIDGE_SECURITY.md](security/BRIDGE_SECURITY.md) — contrat d'accès du bridge (jeton, Origin, Host, MIME), bac à sable, API de commandes

## 📖 guides/
Installation et utilisation.
- [PLUGIN_INSTALLATION.md](guides/PLUGIN_INSTALLATION.md) — installation du plugin QGIS
- [INSTALL_QGIS4.0.txt](guides/INSTALL_QGIS4.0.txt) — installation sur QGIS 4.0 (symlink)
- [AGENTS_USAGE.md](guides/AGENTS_USAGE.md) — utilisation des agents
- [BEST_MODELS_GUIDE.md](guides/BEST_MODELS_GUIDE.md) — choix des modèles LLM
- [GEMMA4_TEST_GUIDE.md](guides/GEMMA4_TEST_GUIDE.md) — test Gemma 4
- [HUGGINGFACE_GEMMA4_GUIDE.md](guides/HUGGINGFACE_GEMMA4_GUIDE.md) — Gemma 4 via HuggingFace

## 🎯 product/
Vision produit, stratégie, roadmap.
- [MOONSHOT.md](product/MOONSHOT.md) — vision long terme
- [ROADMAP.md](product/ROADMAP.md) — plan d'exécution séquencé
- [VISION_METIERS.md](product/VISION_METIERS.md) — packs métier (foresterie, incendie, urbanisme)
- [CHARTE_PRODUIT.md](product/CHARTE_PRODUIT.md) — charte produit
- [GEOSYLVA_VISION_V2.md](product/GEOSYLVA_VISION_V2.md) — vision détaillée v2
- [TECH_LANDSCAPE_2026.md](product/TECH_LANDSCAPE_2026.md) — paysage technologique 2026
- [PRESENTATION_QGISIA_PLUS.md](product/PRESENTATION_QGISIA_PLUS.md) — présentation
- [QUESTIONNAIRE_STRATEGIQUE.md](product/QUESTIONNAIRE_STRATEGIQUE.md) — questionnaire stratégique

## 🧪 testing/
Plans de test, checklists, scénarios.
- [CHECKLIST_ASK_USER_TESTING.md](testing/CHECKLIST_ASK_USER_TESTING.md) — checklist ask_user (4 scénarios)
- [TEST_ASK_USER_QGIS_4.0.md](testing/TEST_ASK_USER_QGIS_4.0.md) — plan de test ask_user QGIS 4.0
- [CHECKLIST_QGIS4_DEPLOY.md](testing/CHECKLIST_QGIS4_DEPLOY.md) — checklist déploiement QGIS 4
- [CHECKLIST_TEST_V1b.md](testing/CHECKLIST_TEST_V1b.md) — checklist test v1b
- [SCENARIO_PSG_EXAMPLE.md](testing/SCENARIO_PSG_EXAMPLE.md) — scénario exemple PSG
- [test-prompts.md](testing/test-prompts.md) — prompts de test

## 🤖 devin/
Délégation de modules à Kimi (agent Devin).
- [DEVIN_TASKS.md](devin/DEVIN_TASKS.md) — file de prompts pour Kimi
- [PROMPT_11_PSG_BLUEPRINT.md](devin/PROMPT_11_PSG_BLUEPRINT.md) — prompt PSG blueprint
- [DEVIN_SIGNATURE.md](devin/DEVIN_SIGNATURE.md) — convention de livraison
- [DEVIN_AUDIT.log](devin/DEVIN_AUDIT.log) — journal d'audit

## 🔍 audits/
Audits, analyses, plans d'optimisation.
- [AUDIT_CRITIQUE.md](audits/AUDIT_CRITIQUE.md) — audit critique
- [AUDIT_SERVICES_TAB.md](audits/AUDIT_SERVICES_TAB.md) — audit onglet Services
- [OPTIMISATION_PLAN.md](audits/OPTIMISATION_PLAN.md) — plan d'optimisation
- [GEMMA4_ANALYSIS.md](audits/GEMMA4_ANALYSIS.md) — analyse Gemma 4

## 📦 superpowers/
Plans de chantier historiques (généré par l'outillage superpowers).
