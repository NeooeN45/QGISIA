# Documentation des APIs - GeoSylva AI QGIS

## Vue d'ensemble

Ce document documente toutes les APIs et systèmes implémentés dans GeoSylva AI pour QGIS. Tous les systèmes utilisent des implémentations réelles via le bridge QGIS, localStorage ou des algorithmes JavaScript purs.

---

## 1. FileManager

**Fichier**: `src/lib/file-manager.ts`

### Description
Gestionnaire de fichiers utilisant le bridge QGIS pour les opérations de fichiers réelles.

### Méthodes principales

#### `selectFile(fileFilter?: string, title?: string): Promise<string | null>`
- Sélectionne un fichier via le dialogue QGIS
- Utilise `pickQgisFile` du bridge QGIS
- Retourne le chemin du fichier sélectionné ou null

#### `readFile(path: string, options?: ReadOptions): Promise<string>`
- Lit le contenu d'un fichier
- Exécute un script Python via `runScriptDetailed`
- Utilise `open()` Python pour la lecture

#### `writeFile(path: string, content: string, options?: WriteOptions): Promise<void>`
- Écrit du contenu dans un fichier
- Exécute un script Python via `runScriptDetailed`
- Utilise `open()` Python pour l'écriture

#### `deleteFile(path: string): Promise<void>`
- Supprime un fichier
- Utilise `os.remove()` Python

#### `fileExists(path: string): Promise<boolean>`
- Vérifie si un fichier existe
- Utilise `os.path.exists()` Python

#### `listDirectory(path: string): Promise<string[]>`
- Liste le contenu d'un répertoire
- Utilise `os.listdir()` Python

#### `createDirectory(path: string): Promise<void>`
- Crée un répertoire
- Utilise `os.makedirs()` Python

#### `getFileMetadata(path: string): Promise<FileMetadata>`
- Obtient les métadonnées d'un fichier
- Utilise `os.stat()` Python
- Retourne: nom, extension, taille, date de modification

### Exemple d'utilisation

```typescript
import { FileManager } from "./lib/file-manager";

const fileManager = new FileManager();

// Sélectionner un fichier
const filePath = await fileManager.selectFile("*.csv", "Sélectionner un CSV");

// Lire un fichier
const content = await fileManager.readFile(filePath);

// Écrire dans un fichier
await fileManager.writeFile("/output/result.txt", "Contenu");

// Vérifier l'existence
const exists = await fileManager.fileExists(filePath);

// Obtenir les métadonnées
const metadata = await fileManager.getFileMetadata(filePath);
console.log(`Taille: ${metadata.size} octets`);
```

---

## 2. CacheManager

**Fichier**: `src/lib/cache-manager.ts`

### Description
Gestionnaire de cache avec persistance localStorage, TTL et LRU eviction.

### Méthodes principales

#### `get<T>(key: string): T | null`
- Récupère une valeur du cache
- Met à jour les statistiques de hits/misses
- Retourne null si la clé n'existe pas ou est expirée

#### `set<T>(key: string, value: T, ttl?: number): void`
- Stocke une valeur dans le cache
- TTL par défaut: 3600000ms (1 heure)
- Applique LRU eviction si la taille limite est atteinte

#### `delete(key: string): void`
- Supprime une entrée du cache

#### `clear(): void`
- Vide tout le cache

#### `getStats(): CacheStats`
- Retourne les statistiques du cache
- Inclut: hits, misses, hitRate, totalSize, entryCount

#### `cleanup(): void`
- Nettoie les entrées expirées
- Applique LRU eviction si nécessaire

### Configuration

```typescript
interface CacheOptions {
  maxSize: number;        // Taille maximale en octets (défaut: 50MB)
  defaultTTL: number;    // TTL par défaut en ms (défaut: 3600000)
  maxEntries: number;     // Nombre maximum d'entrées (défaut: 1000)
}
```

### Exemple d'utilisation

```typescript
import { CacheManager } from "./lib/cache-manager";

const cache = new CacheManager({
  maxSize: 100 * 1024 * 1024, // 100MB
  defaultTTL: 7200000,        // 2 heures
  maxEntries: 5000
});

// Stocker une valeur
cache.set("user:123", { name: "Jean", age: 30 }, 1800000);

// Récupérer une valeur
const user = cache.get<{ name: string; age: number }>("user:123");

// Obtenir les statistiques
const stats = cache.getStats();
console.log(`Hit rate: ${stats.hitRate}%`);
```

---

## 3. SessionManager

**Fichier**: `src/lib/session-manager.ts`

### Description
Gestionnaire de sessions avec persistance localStorage et restauration d'état QGIS.

### Méthodes principales

#### `createSession(name: string): string`
- Crée une nouvelle session
- Sauvegarde automatiquement dans localStorage
- Retourne l'ID de la session

#### `loadSession(sessionId: string): Promise<SessionState | null>`
- Charge une session existante
- Restaure l'état QGIS (CRS, couches)
- Retourne l'état de la session

#### `deleteSession(sessionId: string): void`
- Supprime une session

#### `listSessions(): SessionState[]`
- Liste toutes les sessions

#### `createSnapshot(sessionId: string, name: string): string`
- Crée un snapshot de l'état actuel
- Sauvegarde couches, CRS, visibilité

#### `restoreSnapshot(sessionId: string, snapshotId: string): Promise<void>`
- Restaure un snapshot
- Applique l'état sauvegardé à QGIS

#### `autoSave(sessionId: string): void`
- Sauvegarde automatiquement l'état actuel

### Exemple d'utilisation

```typescript
import { SessionManager } from "./lib/session-manager";

const sessionManager = new SessionManager();

// Créer une nouvelle session
const sessionId = sessionManager.createSession("Projet Forêt");

// Créer un snapshot
const snapshotId = sessionManager.createSnapshot(sessionId, "État initial");

// Plus tard, restaurer le snapshot
await sessionManager.restoreSnapshot(sessionId, snapshotId);

// Lister les sessions
const sessions = sessionManager.listSessions();
```

---

## 4. Data Parcel Matcher

**Fichier**: `src/lib/data-parcel-matcher.ts`

### Description
Système de correspondance de données de parcelles avec algorithmes JavaScript purs (Levenshtein, fuzzy matching).

### Méthodes principales

#### `matchDataToParcels(userData: UserProvidedData, parcels: IdentifiedParcel[], options?: MatchingOptions): MatchResult[]`
- Correspond les données utilisateur aux parcelles
- Utilise scoring multicritères
- Supporte correspondance exacte et floue

#### `fuzzyMatch(str1: string, str2: string, threshold: number): boolean`
- Correspondance floue entre deux chaînes
- Utilise la distance de Levenshtein
- Threshold par défaut: 0.7

#### `levenshteinDistance(str1: string, str2: string): number`
- Calcule la distance de Levenshtein
- Algorithme JavaScript pur

### Critères de correspondance

- ID de parcelle (exact/fuzzy)
- Code de parcelle (exact/fuzzy)
- Nom de parcelle (exact/fuzzy)
- Surface (plage de valeurs)
- Essence (exact/fuzzy)
- Âge (plage de valeurs)
- Volume (plage de valeurs)
- Propriétaire (exact/fuzzy)

### Exemple d'utilisation

```typescript
import { DataParcelMatcher } from "./lib/data-parcel-matcher";

const matcher = new Data ParcelMatcher();

const userData = {
  parcelIds: ["PARCELLE_001"],
  parcelCodes: ["CODE_123"],
  surfaceRange: { min: 1000, max: 5000 },
  essence: "Chêne"
};

const parcels = [/* ... */];

const matches = matcher.matchDataToParcels(userData, parcels, {
  strictMatching: false,
  fuzzyThreshold: 0.8
});

matches.forEach(match => {
  console.log(`${match.parcelId}: score=${match.score}, confiance=${match.confidence}`);
});
```

---

## 5. Parcel Identification Service

**Fichier**: `src/lib/parcel-identification-service.ts`

### Description
Service d'identification de parcelles via flux WFS/WMS et GeoJSON.

### Méthodes principales

#### `identifyParcels(criteria: IdentificationCriteria, sources?: string[]): Promise<ParcelIdentificationResult>`
- Identifie les parcelles selon les critères
- Interroge plusieurs sources en parallèle
- Fusionne et déduplique les résultats

#### `addMapService(id: string, config: MapServiceConfig): void`
- Ajoute un service de carte personnalisé

#### `removeMapService(id: string): void`
- Supprime un service de carte

### Sources supportées

- **WFS**: IGN, ONF, GEOFONCIER
- **GeoJSON**: Tout endpoint GeoJSON
- **WMS**: Lecture seule (pas de requêtes d'attributs)
- **ArcGIS REST**: À implémenter

### Exemple d'utilisation

```typescript
import { ParcelIdentificationService } from "./lib/parcel-identification-service";

const service = new ParcelIdentificationService();

const criteria = {
  forestName: "Forêt de Compiègne",
  surfaceRange: { min: 1000, max: 10000 },
  essence: "Chêne"
};

const result = await service.identifyParcels(criteria, ["IGN_WFS", "ONF_WFS"]);

console.log(`${result.parcels.length} parcelles trouvées`);
```

---

## 6. Selective Parcel Extractor

**Fichier**: `src/lib/selective-parcel-extractor.ts`

### Description
Extracteur sélectif de parcelles via le bridge QGIS.

### Méthodes principales

#### `extractParcels(sourceLayerId: string, selectedParcelIds: string[], options: ExtractionOptions): Promise<ExtractionResult>`
- Extrait les parcelles selon les options
- Modes: selected_only, all_with_highlight, all_with_filter

#### `createMultipleLayers(sourceLayerId: string, selectedParcelIds: string[], options: ExtractionOptions): Promise<string[]>`
- Crée plusieurs couches pour extraction complète

### Options d'extraction

```typescript
interface ExtractionOptions {
  extractMode: "selected_only" | "all_with_highlight" | "all_with_filter";
  highlightStyle: "boundary" | "fill" | "both";
  highlightColor: string;
  highlightOpacity: number;
  boundaryWidth: number;
  createSeparateLayers: boolean;
  preserveAttributes: boolean;
}
```

### Exemple d'utilisation

```typescript
import { SelectiveParcelExtractor } from "./lib/selective-parcel-extractor";

const extractor = new SelectiveParcelExtractor();

const result = await extractor.extractParcels(
  "layer_123",
  ["parcelle_001", "parcelle_002"],
  {
    extractMode: "all_with_highlight",
    highlightStyle: "boundary",
    highlightColor: "#FF0000",
    highlightOpacity: 0.5,
    boundaryWidth: 2
  }
);

console.log(`${result.parcelCount} parcelles extraites`);
```

---

## 7. Geoprocessing Manager

**Fichier**: `src/lib/geoprocessing-manager.ts`

### Description
Gestionnaire de géotraitement via le bridge QGIS (buffer, intersection, union, etc.).

### Méthodes principales

#### `createBuffer(layerId: string, outputLayerName: string, options: BufferOptions): Promise<GeoprocessingResult>`
- Crée un buffer autour d'une couche

#### `intersection(layerId1: string, layerId2: string, outputLayerName: string, options: IntersectionOptions): Promise<GeoprocessingResult>`
- Calcule l'intersection de deux couches

#### `union(layerId1: string, layerId2: string, outputLayerName: string, options: UnionOptions): Promise<GeoprocessingResult>`
- Calcule l'union de deux couches

#### `clip(inputLayerId: string, clipLayerId: string, outputLayerName: string): Promise<GeoprocessingResult>`
- Découpe une couche avec une autre

#### `dissolve(layerId: string, outputLayerName: string, dissolveField?: string): Promise<GeoprocessingResult>`
- Dissout les features d'une couche

### Exemple d'utilisation

```typescript
import { GeoprocessingManager } from "./lib/geoprocessing-manager";

const geoManager = new GeoprocessingManager();

// Créer un buffer de 100m
const bufferResult = await geoManager.createBuffer(
  "parcels_layer",
  "buffer_100m",
  {
    distance: 100,
    segments: 8,
    dissolve: true,
    endCapStyle: "round",
    joinStyle: "round"
  }
);

// Intersection avec une autre couche
const intersectionResult = await geoManager.intersection(
  "buffer_100m",
  "forests_layer",
  "forests_in_buffer",
  { outputType: "intersection", keepAttributes: true }
);
```

---

## 8. Symbology Applier

**Fichier**: `src/lib/symbology-applier.ts`

### Description
Moteur d'application de symbologie selon les normes cartographiques via le bridge QGIS.

### Méthodes principales

#### `applyStandardSymbology(layerId: string, layerTypeName: string, standard: CartographicStandard): Promise<SymbologyApplicationResult>`
- Applique une symbologie standard à une couche
- Génère et exécute des scripts PyQGIS

#### `applyStandardSymbologyBatch(layerMappings: Array<{ layerId: string; layerTypeName: string }>, standard: CartographicStandard): Promise<BatchSymbologyResult>`
- Applique la symbologie en lot à plusieurs couches

### Normes supportées

- Normes IGN
- Normes ONF
- Normes personnalisées via `CartographicStandard`

### Exemple d'utilisation

```typescript
import { applyStandardSymbology } from "./lib/symbology-applier";
import { CartographicStandard } from "./lib/cartographic-standards";

const standard: CartographicStandard = {
  id: "ign_forest",
  name: "IGN Forest Standard",
  symbologyRules: [
    {
      layerTypeId: "forest_parcels",
      rendererType: "categorized",
      categories: [
        { value: "Chêne", color: "#2E7D32", label: "Chênaie" },
        { value: "Hêtre", color: "#43A047", label: "Hêtraie" }
      ]
    }
  ]
};

const result = await applyStandardSymbology(
  "forest_layer",
  "forest_parcels",
  standard
);
```

---

## 9. Forest Document Retriever

**Fichier**: `src/lib/forest-document-retriever.ts`

### Description
Système de récupération et parsing de documents d'aménagement forestier.

### Méthodes principales

#### `searchDocument(options: DocumentRetrievalOptions): Promise<ForestDocument | null>`
- Recherche un document d'aménagement
- Interroge les sources officielles (ONF, IGN)

#### `downloadDocument(document: ForestDocument): Promise<string>`
- Télécharge un document
- Utilise DownloadManager

#### `parseDocument(filePath: string, format: string): Promise<ParcelData[]>`
- Parse un document de parcelles
- Formats supportés: GeoJSON, CSV, Shapefile, Excel

### Formats de parsing

- **GeoJSON**: Parsing via PyQGIS
- **CSV**: Parsing via PyQGIS
- **Shapefile**: À implémenter
- **Excel**: À implémenter

### Exemple d'utilisation

```typescript
import { ForestDocumentRetriever } from "./lib/forest-document-retriever";

const retriever = new ForestDocumentRetriever();

const document = await retriever.searchDocument({
  forestName: "Forêt de Compiègne",
  documentType: "PSG",
  year: 2024,
  includeParcels: true
});

if (document) {
  const parcelData = await retriever.parseDocument(document.localPath, "geojson");
  console.log(`${parcelData.length} parcelles parsées`);
}
```

---

## 10. Geospatial Validator

**Fichier**: `src/lib/geospatial-validator.ts`

### Description
Validateur géospatial via le bridge QGIS.

### Méthodes principales

#### `validateGeometry(layerId: string): Promise<ValidationResult>`
- Valide les géométries d'une couche
- Détecte: géométries nulles, invalides, auto-intersectantes

#### `validateTopology(layerId: string): Promise<ValidationResult>`
- Valide la topologie d'une couche
- Détecte: gaps, overlaps, slivers

#### `validateAttributes(layerId: string, rules: ValidationRule[]): Promise<ValidationResult>`
- Valide les attributs selon des règles

#### `validateCRS(layerId: string, expectedCRS: string): Promise<ValidationResult>`
- Valide le CRS d'une couche

#### `repairGeometry(layerId: string): Promise<RepairResult>`
- Répare les géométries invalides

### Exemple d'utilisation

```typescript
import { GeospatialValidator } from "./lib/geospatial-validator";

const validator = new GeospatialValidator();

// Valider les géométries
const geomResult = await validator.validateGeometry("parcels_layer");
console.log(`${geomResult.errorCount} erreurs géométriques`);

// Réparer les géométries
const repairResult = await validator.repairGeometry("parcels_layer");
console.log(`${repairResult.repairedCount} géométries réparées`);
```

---

## 11. Export Print Manager

**Fichier**: `src/lib/export-print-manager.ts`

### Description
Gestionnaire d'export PDF et impression via le bridge QGIS.

### Méthodes principales

#### `exportToPDF(layoutName: string, outputPath: string, options: Partial<ExportOptions>): Promise<ExportResult>`
- Exporte une mise en page en PDF

#### `printLayout(layoutName: string, options: PrintOptions): Promise<PrintResult>`
- Imprime une mise en page

#### `listPrinters(): Promise<{ success: boolean; printers: string[]; error?: string }>`
- Liste les imprimantes disponibles

#### `createAtlas(layoutName: string, coverageLayer: string, outputDirectory: string, options: Partial<ExportOptions>): Promise<ExportResult[]>`
- Crée un atlas de cartes

### Exemple d'utilisation

```typescript
import { ExportPrintManager } from "./lib/export-print-manager";

const printManager = new ExportPrintManager();

// Exporter en PDF
const result = await printManager.exportToPDF(
  "carte_forest",
  "/output/carte.pdf",
  { resolution: 300, format: "pdf" }
);

// Créer un atlas
const atlasResults = await printManager.createAtlas(
  "carte_forest",
  "parcels_layer",
  "/output/atlas",
  { resolution: 300 }
);
```

---

## 12. Multi-Format Export Manager

**Fichier**: `src/lib/multi-format-export-manager.ts`

### Description
Gestionnaire d'export multi-format (KML, GeoJSON, Shapefile, etc.) via le bridge QGIS.

### Méthodes principales

#### `exportLayer(layerId: string, options: ExportOptions): Promise<ExportResult>`
- Exporte une couche vers un format spécifié

#### `exportMultipleLayers(layerIds: string[], options: BatchExportOptions): Promise<ExportResult[]>`
- Exporte plusieurs couches

#### `getSupportedFormats(): ExportFormat[]`
- Retourne la liste des formats supportés

### Formats supportés

- **KML**: .kml
- **GeoJSON**: .geojson, .json
- **Shapefile**: .shp (avec .dbf, .shx, .prj)
- **CSV**: .csv
- **GML**: .gml

### Exemple d'utilisation

```typescript
import { MultiFormatExportManager } from "./lib/multi-format-export-manager";

const exportManager = new MultiFormatExportManager();

// Exporter en GeoJSON
const result = await exportManager.exportLayer(
  "parcels_layer",
  {
    format: exportManager.getSupportedFormats().find(f => f.name === "GeoJSON")!,
    outputPath: "/output/parcels.geojson"
  }
);

console.log(`Exporté: ${result.filePath} (${result.size} octets)`);
```

---

## Bridge QGIS

**Fichier**: `src/lib/qgis.ts`

### Fonctions principales

> **Sécurité** — toute requête `/api/**` exige le jeton du bridge
> (`X-QGISIA-Token`), une origine locale et `Content-Type: application/json`.
> Voir [../security/BRIDGE_SECURITY.md](../security/BRIDGE_SECURITY.md).

#### `runScriptDetailed(script: string): Promise<ScriptExecutionResult | null>`
- Exécute un script dans le **bac à sable hors-processus** (ni fichier, ni
  réseau, ni accès au projet QGIS), après confirmation de l'utilisateur
- Retourne un résultat détaillé avec succès/échec
- L'option `requireConfirmation` a été **supprimée** : la confirmation est
  inconditionnelle et le bridge répond `400` si le champ est envoyé

#### `pickQgisFile(fileFilter?: string, title?: string): Promise<string | null>`
- Ouvre un dialogue de sélection de fichier QGIS
- Retourne le chemin du fichier sélectionné

#### `isQgisAvailable(): boolean`
- Vérifie si le bridge QGIS est disponible

#### `runScript(script: string): Promise<string | null>`
- Exécute un script dans le bac à sable (version simplifiée)

#### Modifier le projet QGIS — `POST /api/qgis/runCommands`
- Un script en bac à sable **ne peut pas** muter la session QGIS
- Les mutations passent par l'API de commandes autorisées, typée et validée
- `GET /api/qgis/listCommands` énumère les commandes disponibles

#### Routes supprimées
- `POST /api/qgis/runScriptDirect` — **supprimée** (exécutait sans
  confirmation utilisateur ; voir le modèle de menace)

### Exemple d'utilisation

```typescript
import { runScriptDetailed, pickQgisFile, isQgisAvailable } from "./lib/qgis";

if (isQgisAvailable()) {
  // Sélectionner un fichier
  const filePath = await pickQgisFile("*.shp", "Sélectionner un Shapefile");
  
  // Exécuter un script
  const script = `
from qgis.core import QgsProject
project = QgsProject.instance()
print(f"Layers: {len(project.mapLayers())}")
`;
  
  const result = await runScriptDetailed(script);
  if (result?.ok) {
    console.log(result.message);
  }
}
```

---

## Intégration React

### Exemple d'intégration dans un composant React

```typescript
import { useState } from "react";
import { FileManager, CacheManager, SessionManager } from "./lib";

export function GeoSylvaComponent() {
  const [fileManager] = useState(() => new FileManager());
  const [cache] = useState(() => new CacheManager());
  const [sessionManager] = useState(() => new SessionManager());
  
  const handleFileSelect = async () => {
    const filePath = await fileManager.selectFile("*.csv", "Sélectionner un CSV");
    if (filePath) {
      const content = await fileManager.readFile(filePath);
      // Traiter le contenu
    }
  };
  
  const handleCache = () => {
    cache.set("key", { data: "value" });
    const value = cache.get("key");
  };
  
  return (
    <div>
      <button onClick={handleFileSelect}>Sélectionner un fichier</button>
      <button onClick={handleCache}>Utiliser le cache</button>
    </div>
  );
}
```

---

## Bonnes pratiques

1. **Toujours vérifier la disponibilité du bridge QGIS**
   ```typescript
   if (isQgisAvailable()) {
     // Utiliser les fonctions QGIS
   }
   ```

2. **Gérer les erreurs correctement**
   ```typescript
   try {
     const result = await fileManager.readFile(path);
   } catch (error) {
     console.error("Erreur de lecture:", error);
   }
   ```

3. **Utiliser le cache pour les opérations coûteuses**
   ```typescript
   const cached = cache.get("expensive_operation");
   if (!cached) {
     const result = await expensiveOperation();
     cache.set("expensive_operation", result, 3600000);
   }
   ```

4. **Sauvegarder les sessions régulièrement**
   ```typescript
   sessionManager.autoSave(currentSessionId);
   ```

---

## Conclusion

Tous les systèmes sont implémentés avec des appels réels au bridge QGIS, localStorage ou des algorithmes JavaScript purs. Aucune simulation n'est utilisée dans les systèmes critiques.

Pour plus d'informations, consultez les fichiers source dans `src/lib/`.
