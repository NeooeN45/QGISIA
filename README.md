<div align="center">

# GeoSylva AI — Agent SIG intelligent pour QGIS

### Un véritable agent IA qui *agit* dans QGIS

**Parlez à vos données géographiques en langage naturel.**
L'agent route votre demande vers le meilleur modèle, appelle les outils
QGIS, interroge le web et l'imagerie satellite, génère du PyQGIS — et
exécute. Propulsé par NVIDIA NIM.

[![Version](https://img.shields.io/badge/version-3.10-blue?style=for-the-badge)](VERSION)
[![QGIS](https://img.shields.io/badge/QGIS-3.16%2B%20%7C%204.0-green?style=for-the-badge&logo=qgis&logoColor=white)](https://qgis.org)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=for-the-badge&logo=react&logoColor=white)](https://react.dev)
[![NVIDIA NIM](https://img.shields.io/badge/NVIDIA-NIM-76B900?style=for-the-badge&logo=nvidia&logoColor=white)](https://build.nvidia.com)
[![Licence](https://img.shields.io/badge/licence-MIT-orange?style=for-the-badge)](LICENSE)

**Version courante : 3.10** — source unique : fichier `VERSION` à la racine.
**Nom produit** : « GeoSylva AI » (marketing) = plugin QGIS « QGISIA2 » (identifiant technique).

> **QGISIA** est une spécialisation de
> [**Quintessences**](https://github.com/NeooeN45/Quintessences) —
> écosystème d'intelligence environnementale propulsé par le moteur
> GSIE (General System Intelligence Engine).

---

[Capacités](#-capacités) · [Installation](#-installation) · [Modèles](#-modèles--nvidia-nim) · [Architecture](#-architecture) · [Sécurité](#-sécurité) · [Tests](#-tests) · [Sources de données](#-sources-de-données) · [Compatibilité](#-compatibilité)

</div>

---

## Capacités

| | |
|---|---|
| **3 cerveaux, 1 chat** | Gateway unifié via NVIDIA NIM · routage multi-agents (code / vision / raisonnement) · Mode Action — l'agent **appelle les outils QGIS** jusqu'à accomplir la tâche |
| **Agit dans QGIS** (tool calling) | Lister / filtrer / styler / zoomer les couches · reprojeter · statistiques zonales (NDVI/parcelle) · **diagnostic satellite** (NDVI/NDWI + détection de changement) · symbologies institutionnelles + génération PyQGIS sécurisée |
| **Grounding web & satellite** | Géocodage (OpenStreetMap / Nominatim) · météo + élévation (Open-Meteo) · imagerie **Sentinel-1/2, Landsat** (STAC, sans clé) · Wikipédia (faits vérifiés) |
| **Reproduction de carte** | Lit la **légende d'une image** de carte (vision) · extrait la symbologie → **génère un style QGIS** · l'applique automatiquement à la couche |

---

## Intégration GSIE

QGISIA est la projection SIG et analytique du jumeau numérique fédéré
GSIE. Il permet d'explorer, préparer, contrôler et exporter les
ressources de GeoSylva, Ignis, Hydro, Flora et Artemis selon les
contrats versionnés, sans devenir la source de vérité des autres
domaines.

Voir [GSIE_INTEGRATION.md](GSIE_INTEGRATION.md).

---

## Installation

### Plugin QGIS (recommandé)

```
1. QGIS → Extensions → Installer depuis un ZIP → choisir le build (releases/)
2. Activer « QGISIA2 » dans la liste des extensions
3. Paramètres > Gateway IA → coller la clé NVIDIA NIM (build.nvidia.com)
4. Activer « Utiliser le Gateway » (+ « SIG Intelligent » et/ou « Mode Action »)
```

### Développement

```bash
git clone https://github.com/NeooeN45/QGISIA2.git
cd QGISIA2
npm install
npm run dev          # UI sur http://localhost:3000
npm run build        # build du plugin (QGISIA2/web/)
```

Clés pour scripts/dev — copier `.env.example` en `.env.local` (gitignoré) :

```env
NVIDIA_API_KEY=nvapi-...
```

---

## Modèles — NVIDIA NIM

Le catalogue est **validé en live** (`scripts/validate_nvidia_models.py`)
et curé dans `QGISIA2/config/models.json`. Quelques alias :

| Alias | Modèle primaire | Usage |
|---|---|---|
| `smart-default` | `nemotron-3-super-120b` | Cerveau général (rapide + qualité) |
| `reasoning` | `nemotron-3-ultra-550b` | Raisonnement spatial lourd |
| `code-pyqgis` | `qwen3-coder-480b` | Génération de code PyQGIS |
| `vision` | `nemotron-3-nano-omni` | Analyse de cartes / images |
| `intent-router` | `nemotron-mini-4b` | Routage ultra-rapide |

Repli automatique vers OpenRouter / Groq / **Ollama (100% offline)** si besoin.

---

## Architecture

```
UI React (Chat)
  └─► HTTP ─► /api/llm/chat   (chat simple)
             /api/llm/smart   (fédération multi-agents)
             /api/llm/agent   (boucle de tool-calling)
                  │
          llm_gateway.py (LiteLLM) ── NVIDIA NIM (cœur) + fallbacks
                  │
     ┌────────────┼─────────────────┐
 fédération   tool-calling      outils natifs
 multi-agents (outils QGIS)     (web / géo / satellite)
                  │
          bridge QGIS (/api/qgis/*) ─► PyQGIS réel
```

Détails complets : [`docs/architecture/AGENTIC_BACKEND.md`](docs/architecture/AGENTIC_BACKEND.md).
Index de la doc : [`docs/README.md`](docs/README.md).

---

## Sécurité

- **Clés API** : chiffrées au repos via **AES-GCM 256 bits** (WebCrypto),
  clé maître *non extractible* dans IndexedDB ; jamais commitées, jamais
  envoyées au serveur sans action utilisateur. ⚠️ Pour une app côté
  client, aucun schéma local n'est inviolable face à un XSS/attaquant
  local — pour un secret hautement sensible, préférer un stockage
  backend (QgsSettings / keychain OS).
- **Exécution PyQGIS** : tout script généré par l'IA passe par une
  **double validation** avant `exec()` — blocklist regex *et* analyse
  AST (imports dangereux, accès duunter d'évasion, builtins
  `eval`/`exec`/`open`…) — puis par les **guardrails** (actions
  destructives bloquées ou soumises à confirmation, sauf Mode Auto).
  Note : ce n'est pas un sandbox complet ; ne pas exposer le bridge
  hors `127.0.0.1`.
- **Bridge HTTP local** : écoute uniquement sur `127.0.0.1`, CORS
  restreint aux origines locales, taille de requête bornée,
  rate-limiting actif.

---

## Tests

| Commande | Couvre |
|---|---|
| `python -m pytest tests/` | Tests unitaires (gateway, fédération, tools, vision) |
| `npm run test` | Tests front (Vitest) |
| `python tests/manual/test_live_e2e.py` | e2e **live** contre NVIDIA (chat, routage, tool-calling, géo) |
| `tests/_run_qgis.bat tests/qgis_real_smoke.py` | Bridge PyQGIS **réel dans QGIS** |
| `tests/_run_qgis.bat tests/qgis_grandeur_nature_smoke.py` | Scénarios utilisateur de bout en bout |

---

## Sources de données intégrées

🇫🇷 IGN / Géoplateforme · Cadastre (API Carto) · Overpass / OpenStreetMap ·
Copernicus · Hub'Eau · GBIF · DVF — 🌍 Nominatim · Open-Meteo · STAC Earth
Search (Sentinel-1/2, Landsat) · Wikipédia.

---

## Compatibilité

| | |
|---|---|
| **QGIS** | 3.16+ et 4.x (PyQt5 / PyQt6) — testé sur **3.44.8 LTR** |
| **OS** | Windows · Linux · macOS |
| **Python** | 3.9+ |

---

<div align="center">

**Fait avec ❤️ pour la communauté SIG francophone — propulsé par NVIDIA NIM**

[⭐ Star](https://github.com/NeooeN45/QGISIA2) · [🐛 Bug](https://github.com/NeooeN45/QGISIA2/issues) · [💡 Idée](https://github.com/NeooeN45/QGISIA2/issues)

</div>

---

## Contact

Pour toute question, réclamation ou collaboration :

**5jvw9s5zj@mozmail.com**
