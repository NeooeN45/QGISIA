# Contrat de sécurité du bridge QGISIA+

> Référence d'implémentation : `QGISIA2/bridge_http.py`.
> Tests de conformité : `tests/test_bridge_http.py` (unitaires **et**
> intégration sur un vrai serveur loopback).

---

## 1. Contrat d'accès

Toute requête vers `/api/**` traverse `bridge_http.guard_request` **avant**
que le corps ne soit lu et **avant** tout dispatch. L'ordre des contrôles est
significatif : il évite de divulguer à un attaquant distant une information
qu'il n'a pas le droit d'obtenir.

| Ordre | Contrôle | Échec | Raison de la position |
|---|---|---|---|
| 1 | `Host` local (`127.0.0.1`, `localhost`, `[::1]`, port optionnel) | **403** | anti DNS-rebinding ; doit précéder tout le reste |
| 2 | `Origin` locale si présente ; obligatoire sur POST/PUT/PATCH/DELETE | **403** | une origine hostile est refusée sans qu'on lui dise si son jeton était bon |
| 3 | `X-QGISIA-Token` valide (comparaison à temps constant) | **401** | authentification proprement dite |
| 4 | `Content-Type: application/json` sur POST | **415** | ferme les MIME « simple request » |

Un refus produit une réponse JSON explicite avec le bon statut. **Ce n'est
jamais une simple omission d'en-tête CORS** : la faille corrigée tenait
précisément à ce que la requête agissait malgré l'absence de CORS.

### Pourquoi `Origin` est obligatoire sur les méthodes mutantes

Les navigateurs émettent systématiquement `Origin` sur `POST`. Son absence
signale donc un client non navigateur, qui n'est pas soumis à la politique
d'origine. Sur `GET` en revanche, une requête same-origin n'émet pas
d'`Origin` : l'exiger casserait l'UI sans rien apporter, puisque le jeton
reste requis.

### Pourquoi `application/json` est imposé

`text/plain`, `application/x-www-form-urlencoded` et `multipart/form-data`
sont les trois MIME qu'un `<form>` cross-origin peut envoyer **sans
préflight CORS**. Les refuser garantit qu'une requête mutante venue d'une
autre origine déclenche un préflight — que la vérification d'`Origin`
bloquera.

---

## 2. Cycle de vie du jeton

| Propriété | Valeur |
|---|---|
| Génération | `secrets.token_urlsafe(32)` — 256 bits d'entropie |
| Portée | un démarrage de `ThreadedAssetServer` |
| Persistance | **aucune** : ni fichier, ni `QgsSettings`, ni variable d'environnement |
| Transmission | balise `<meta name="qgisia-bridge-token">` injectée dans la page servie depuis `127.0.0.1` |
| Comparaison | `hmac.compare_digest` (temps constant) |
| Journalisation | jamais — les réponses d'erreur ne le contiennent pas (test dédié) |

Le jeton ne transite **jamais par l'URL**. Il n'apparaît donc ni dans
l'historique du navigateur, ni dans un en-tête `Referer`, ni dans les
journaux d'un proxy. La page qui le porte est servie avec `Cache-Control:
no-store` et `Referrer-Policy: no-referrer`.

Un serveur dont le jeton serait vide n'autorise rien : `tokens_match` renvoie
`False` si l'un des deux jetons est vide, pour qu'aucune erreur de
configuration n'ouvre le bridge par accident.

---

## 3. Exécution de code

### Ce qui n'existe plus

| Supprimé | Pourquoi |
|---|---|
| `/api/qgis/runScriptDirect` | seul chemin d'exécution sans confirmation |
| slot `runScriptDirect` | idem, côté QWebChannel |
| `runScriptDirect` côté TypeScript | idem, côté client |
| champ `requireConfirmation` sur le réseau | rendait la confirmation pilotable à distance |
| `ScriptWorker` | portait `exec()` dans le processus QGIS |

Un client qui envoie encore `requireConfirmation` reçoit **400**, et non un
silence : une tentative de désactivation doit être visible, pas absorbée.

### Les deux barrières

1. **Validation statique** (`script_validation`) — allowlist de racines
   d'import, refus des dunders (attribut, nom, littéral), refus des scripts
   non analysables. Un script refusé ne fait lancer **aucun** processus.
2. **Bac à sable hors-processus** (`script_sandbox` + `sandbox_runner`) —
   sous-processus `python -I -S -B`, builtins réduits, `__import__` filtré,
   environnement vidé, pas de `open`, terminaison par l'OS au timeout.

Les tests exercent chaque barrière **séparément**, pour que la défense en
profondeur soit démontrée et non supposée.

### Conséquence fonctionnelle

Un script brut ne peut plus modifier la session QGIS : le sous-processus n'y
a aucun accès. Les mutations passent par l'**API de commandes autorisées**.

---

## 4. API de commandes autorisées

`POST /api/qgis/runCommands`

```json
{
  "commands": [
    {"command": "zoomToLayer",     "params": {"layerId": "L1"}},
    {"command": "setLayerOpacity", "params": {"layerId": "L1", "opacity": 0.5}}
  ]
}
```

- `GET /api/qgis/listCommands` énumère les commandes et celles qui écrivent
  sur le disque.
- Commande inconnue, paramètre inconnu, type incorrect → **400**.
- Un lot est **tout ou rien** : aucune mutation partielle n'est appliquée.
- Aucune commande ne mappe vers `runScript*` — vérifié par test.

Le typage est strict : `"0.5"` n'est pas accepté là où un nombre est attendu,
et `True` n'est pas accepté comme nombre (bien que `bool` dérive de `int`).

---

## 5. Vérifier une installation

```bash
python scripts/build_release.py --inspect releases/QGISIA2_vX.Y.zip
```

Sortie attendue : `OK : aucun motif interdit`.

Reconstruire et comparer l'empreinte d'un artefact :

```bash
python scripts/build_release.py --check-reproducible
```

Deux constructions du même commit doivent donner le même SHA-256.
