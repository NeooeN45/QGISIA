# Modèle de menace — bridge local et exécution de scripts

> Périmètre : le serveur HTTP loopback du plugin QGISIA2 et le chemin
> d'exécution des scripts PyQGIS produits par un LLM.
> Statut : `Validated` — remplace l'état antérieur à la correction P0.
> Dernière révision : 2026-07-26.

---

## 1. Ce que le système protège

L'actif principal n'est pas le plugin : c'est **le poste du forestier**. Le
bridge tourne sur `127.0.0.1` dans le processus QGIS, avec les droits de
l'utilisateur. Un chemin d'exécution non authentifié y donne donc accès :

| Actif | Exposition si le bridge est compromis |
|---|---|
| Système de fichiers de l'utilisateur | lecture et écriture avec ses droits |
| Projet QGIS ouvert | modification, suppression de couches |
| Clés API (NVIDIA, OpenRouter, Gemini) | lisibles via `QgsSettings` et l'environnement |
| Réseau local de l'organisation | pivot depuis le poste |
| Données forestières et cadastrales | exfiltration |

---

## 2. Attaquants considérés

| # | Attaquant | Capacité supposée |
|---|---|---|
| A1 | Page web malveillante visitée par l'utilisateur | exécute du JS dans le navigateur, connaît le port (liste courte et déterministe : 8157-8161) |
| A2 | Domaine hostile pratiquant le rebinding DNS | fait pointer son domaine vers `127.0.0.1` après le premier chargement |
| A3 | LLM compromis, empoisonné ou simplement halluciné | contrôle le contenu du script proposé à l'exécution |
| A4 | Processus local non privilégié du même utilisateur | émet des requêtes HTTP arbitraires vers le port |

**Hors périmètre** : attaquant déjà administrateur du poste, accès physique,
compromission de QGIS lui-même. Ces cas dépassent ce que le plugin peut
contenir et ne sont pas revendiqués comme couverts.

---

## 3. État AVANT correction

Chemin d'attaque complet, sans aucune authentification :

```
A1 (page web) ──POST /api/qgis/runScriptDirect──> bridge ──> exec() dans QGIS
                     aucun jeton                            builtins complets
```

| # | Faiblesse | Conséquence |
|---|---|---|
| V1 | Aucune authentification sur le bridge | toute page ou tout processus local pilote QGIS |
| V2 | `Origin` distante : l'en-tête CORS était seulement *omis* | la requête s'exécutait quand même ; le navigateur bloquait la lecture de la réponse, pas l'effet de bord |
| V3 | `Host` non vérifié | rebinding DNS : la page hostile devenait same-origin et lisait tout |
| V4 | Aucun contrôle de `Content-Type` | un `<form>` cross-origin (`text/plain`) suffisait, sans préflight |
| V5 | `/api/qgis/runScriptDirect` | exécution **sans confirmation** de l'utilisateur |
| V6 | `runScriptDetailed(requireConfirmation=false)` | la confirmation était pilotable depuis le réseau |
| V7 | `exec()` dans le processus QGIS avec `"__builtins__": __builtins__` | accès complet à `open`, `__import__`, `eval` |
| V8 | Validation par blocklist | `pathlib`, `shutil`, `tempfile`, `glob`, `sqlite3`, `importlib` passaient |
| V9 | Timeout non tuant | `thread.join(timeout)` signalait l'expiration ; le thread `daemon` continuait à tourner |

**Gravité combinée : critique.** V1+V5+V7 forment une exécution de code à
distance en une seule requête, déclenchée par la simple visite d'une page.

---

## 4. État APRÈS correction

```
requête ──> [Host local ?] ──403──> [Origin locale ?] ──403──> [jeton valide ?] ──401──>
            [application/json ?] ──415──> lecture du corps ──> dispatch
                                                                │
                                    script ──> validation statique (allowlist)
                                           ──> confirmation utilisateur (obligatoire)
                                           ──> sous-processus isolé, tuable
                                                (ni fichier, ni réseau, ni projet QGIS)
```

| # | Contre-mesure | Où |
|---|---|---|
| C1 | Jeton aléatoire par démarrage (`secrets`), comparé en temps constant | `bridge_http.tokens_match` |
| C2 | Jeton transmis par `<meta>` dans la page servie localement, jamais par URL | `bridge_http.inject_token_meta` |
| C3 | `Host` non local → 403 (anti-rebinding) | `bridge_http.is_local_host` |
| C4 | `Origin` distante → 403 ; absente sur méthode mutante → 403 | `bridge_http.guard_request` |
| C5 | POST non `application/json` → 415 | `bridge_http.is_json_content_type` |
| C6 | `runScriptDirect` supprimé (route + slot + client TS) | `geoai_assistant`, `src/lib/qgis.ts` |
| C7 | `requireConfirmation` hors contrat réseau ; sa présence → 400 | `_reject_confirmation_override` |
| C8 | Confirmation inconditionnelle côté plugin | `_execute_script_payload` |
| C9 | Exécution dans un sous-processus `-I -S -B`, builtins réduits | `script_sandbox`, `sandbox_runner` |
| C10 | Terminaison par l'OS au timeout, puis moisson | `script_sandbox._kill` |
| C11 | Allowlist d'imports (défaut = refus) | `script_validation.ALLOWED_IMPORT_ROOTS` |
| C12 | Mutations du projet via table figée de commandes typées | `script_commands` |
| C13 | Environnement du sous-processus vidé (pas de clés API) | `script_sandbox.spawn_sandboxed` |

### Couverture par attaquant

| Attaquant | Avant | Après | Barrière décisive |
|---|---|---|---|
| A1 page web | exécution de code | bloqué | ne peut pas lire le jeton (politique d'origine) → 401 |
| A2 rebinding DNS | exécution de code | bloqué | `Host` non local → 403, avant même de servir la page |
| A3 LLM hostile | exécution de code dans QGIS | contenu | validation + confirmation + bac à sable sans capacité |
| A4 processus local | exécution de code | bloqué | ne connaît pas le jeton (jamais écrit sur disque ni journalisé) |

---

## 5. Limites assumées

Ce modèle ne revendique **pas** un bac à sable Python inviolable — aucun ne
l'est. Les limites suivantes sont explicites, testées, et à réévaluer :

1. **Traversée de dunders.** Le sous-processus n'interdit pas
   `().__class__.__bases__`. C'est la *validation statique* qui la refuse, en
   amont. Deux tests l'affirment plutôt que de le sous-entendre :
   `test_dunder_traversal_is_blocked_by_static_validation` et
   `test_dunder_traversal_is_not_claimed_to_be_blocked_by_the_sandbox`.
2. **Chaîne dunder reconstruite à l'exécution.** `'__cla' + 'ss__'` échappe à
   l'analyse statique. La containment repose alors sur l'absence de `getattr`
   et de capacités dans le bac à sable.
3. **Limites OS partielles sous Windows.** `RLIMIT_FSIZE` / `RLIMIT_AS` ne
   sont posées que sous POSIX. Sous Windows, la containment repose sur
   l'absence de capacités et sur `TerminateProcess`.
4. **A4 reste possible si le jeton fuit.** Un processus local capable de lire
   la mémoire du processus QGIS obtient le jeton — mais il a déjà gagné.
5. **Le rate-limiter est par IP**, donc sans effet discriminant en loopback ;
   il protège des boucles d'agent runaway, pas d'un attaquant.

---

## 6. Ce qui reste à décider (hors périmètre technique)

- Retrait / rotation de l'artefact `QGISIA2_v3.9.zip` déjà distribué.
- Politique de communication auprès des utilisateurs ayant installé v3.9.
- Réintroduction éventuelle de `vendor/` dans l'artefact (installation hors
  ligne) — voir le compte rendu de la correction.
