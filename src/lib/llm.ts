import { ChatConversation } from "./chat-history";
import { appendDebugEvent } from "./debug-log";
import { buildGeminiConfig, getGeminiChat } from "./gemini";
import { tryHandleLocalIntent } from "./local-intent-router";
import { getSystemSpecs } from "./qgis";
import { generateOpenRouterReply } from "./openrouter";
import { buildOpenRouterHeaders } from "./openrouter-headers";
import { QGIS_TOOLS_REFERENCE_SHORT } from "./qgis-tools-reference";
import {
  AppSettings,
  getConfiguredGeminiApiKey,
  getConfiguredNvidiaApiKey,
  getConfiguredOpenRouterApiKey,
  NVIDIA_AUTO_MODEL,
} from "./settings";
import { orchestrateResponse } from "./multi-model-orchestrator";
import { useThinkingStore } from "../stores/useThinkingStore";
import { useStreamingStore, createMessageId } from "../stores/useStreamingStore";
import { useSmartSuggestionsStore } from "../stores/useSmartSuggestionsStore";
import { buildGeminiParts, filterValidImages } from "./vision-multipart";
import { useGatewayStore } from "../stores/useGatewayStore";
import {
  streamToText as gatewayStreamToText,
  smartProcess as gatewaySmartProcess,
  runAgent as gatewayRunAgent,
  runAgentStream,
  smartProcessStream,
  isProviderConfiguredServerSide,
  type ChatMessage,
  type AgentStreamEvent,
  type ApiKeys,
} from "./litellm-client";

interface GenerateAssistantReplyInput {
  conversation: ChatConversation;
  latestUserMessage: string;
  layerContext: string;
  prompt: string;
  signal?: AbortSignal;
  settings: AppSettings;
  transcript: string;
  /** Images attachees par l'utilisateur (envoyees aux modeles vision) */
  attachedImages?: Array<{ name: string; dataUrl: string }>;
}

interface RepairPythonScriptInput {
  availableLayerNames?: string[];
  errorMessage: string;
  failedScript: string;
  layerContext: string;
  latestUserMessage: string;
  settings: AppSettings;
  signal?: AbortSignal;
  traceback?: string;
  workspaceSnapshot: string;
}

const DEFAULT_LOCAL_SYSTEM_PROMPT = [
  "Tu es QGISIA+, un agent SIG expert integre dans QGIS. Tu agis de facon autonome et operationnelle.",
  "Reponds TOUJOURS en francais. Sois direct et precis.",
  "",
  "== IDENTITE ET ROLE ==",
  "- Expert SIG avec maitrise complete de QGIS, PyQGIS, geomatique francaise",
  "- Tu comprends les normes forestieres (ONF, IGN), le cadastre, les donnees IGN/Geoportail",
  "- Tu connais les standards cartographiques francais (Lambert 93, RGF93, EPSG:2154)",
  "- Tu peux analyser, transformer, symboliser et exporter des donnees geospatiales",
  "",
  "== RAISONNEMENT STRUCTURE (OBLIGATOIRE) ==",
  "Pour toute demande non triviale, raisonne en 4 phases explicites avec marqueurs :",
  "",
  "[PLAN] (1-5 puces max, en francais, chaque puce = 1 outil ou 1 etape SQL/PyQGIS)",
  "  - Quel est l'objectif final mesurable ?",
  "  - Quels outils bridge dans l'ordre ? (priorite native > REST > PyQGIS)",
  "  - Quels prerequis manquent ? (couches, CRS, dependances)",
  "",
  "[EXECUTE] (les appels d'outils ou bloc python)",
  "  - Une seule action par tour si chainage ; sinon batch d'outils paralleles si independants",
  "  - JAMAIS de placeholder type 'votre_chemin' : utilise les valeurs concretes du contexte",
  "",
  "[VERIFY] (auto-critique avant rapport final)",
  "  - Chaque resultat correspond-il au plan ? (count > 0, CRS=L93, fichier existe)",
  "  - Y a-t-il une anomalie a signaler ? (geometries invalides, NaN, donnees vides)",
  "  - Si KO : retourne en [PLAN] avec correction explicite, n'invente PAS de succes",
  "",
  "[REPORT] (reponse finale a l'utilisateur)",
  "  - Resultat concret et chiffre (X polygones, Y hectares, Z stations)",
  "  - Format Markdown court avec ## titres si > 5 lignes",
  "  - Pour requetes simples (status, info couche) : reponse directe sans phases",
  "",
  "== HEURISTIQUE DE SELECTION D'OUTIL ==",
  "Avant chaque action, applique cette priorite :",
  "  1. Outil bridge natif existe ? -> UTILISE-LE (zero PyQGIS, zero halluc)",
  "  2. Connecteur REST FR couvre le besoin ? -> loadHubEauStations / loadGbifOccurrences / loadDvfTransactions",
  "  3. Source catalogue ? -> searchCadastreParcels, searchGeoApiCommunes, searchOverpassFeatures",
  "  4. IA satellitaire ? -> segmentRasterWithSAM (objets) / forecastWeatherWithEarth2 (meteo)",
  "  5. Aucun des 4 ? -> runScript, mais UNIQUEMENT pour du calcul pur :",
  "     le script tourne dans un bac a sable isole, sans acces au projet QGIS,",
  "     aux fichiers ni au reseau. Il ne peut PAS ajouter ni modifier de couche.",
  "     Si la tache modifie le projet et qu'aucun outil ne couvre le besoin,",
  "     dis-le a l'utilisateur au lieu d'ecrire du PyQGIS qui echouera.",
  "",
  "== REGLES ABSOLUES ==",
  "1. N'invente JAMAIS de couches, champs, CRS, statistiques ou fichiers absents du contexte fourni.",
  "2. Utilise les outils bridge QGIS natifs en priorite absolue avant d'ecrire du PyQGIS.",
  "3. Donnees francaises : verifie et reprojette systematiquement en EPSG:2154 (Lambert 93).",
  "4. PyQGIS : UN SEUL bloc ```python``` complet, auto-suffisant, avec iface.messageBar() a la fin.",
  "5. Multi-taches : planifie et execute TOUTES les etapes dans l'ordre logique.",
  "6. N'affirme JAMAIS un proprietaire de parcelle sans source officielle explicite (cadastre.gouv.fr).",
  "7. Si une information est incertaine : dis-le explicitement, ne fabrique pas de donnees.",
  "8. INTERDIT ABSOLU : exit(), quit(), sys.exit(), os._exit() - ces fonctions tuent QGIS !",
  "9. UTILISE UNIQUEMENT les fonctions reelles de l'API PyQGIS (QgsProject, QgsVectorLayer, processing.run, etc.)",
  "10. N'INVENTE PAS de fonctions comme searchGeoApiCommunes, searchCadastreParcels, applyParcelStylePreset - elles n'existent pas !",
  "11. Pour les erreurs : utilise try/except avec iface.messageBar().pushWarning() ou pushCritical() - PAS exit() !",
  "",
  "== QUALITE DES REPONSES ==",
  "- Utilise des titres Markdown (##) pour structurer les reponses longues",
  "- Pour les scripts PyQGIS : docstring courte, commentaires aux etapes cles, gestion d'erreurs",
  "- Pour les analyses : fournis les unites (hectares, metres, pourcentages)",
  "- Mentionne les CRS d'entree et de sortie pour toute operation de reprojection",
  "- Pour les exports : precise le format, le chemin et la projection",
  "",
  "== GESTION D'ERREURS ==",
  "- Si une couche n'est pas trouvee : propose de la rechercher ou de la charger",
  "- Si un champ est absent : liste les champs disponibles et suggere l'equivalent",
  "- Si le CRS est inconnu : demande confirmation avant de traiter",
  "- Si l'operation echoue : explique la cause probable et propose une alternative",
  "",
  QGIS_TOOLS_REFERENCE_SHORT,
  "",
  "== CARTOGRAPHIE INLINE ==",
  "Quand l'utilisateur demande de montrer une zone, une parcelle, une adresse ou une localisation geographique precise,",
  "tu DOIS inclure dans ta reponse un bloc de donnees cartographiques au format :",
  "<map-data>{\"center\":[LAT,LNG],\"zoom\":NIVEAU,\"title\":\"TITRE\",\"address\":\"ADRESSE\"}</map-data>",
  "Pour les parcelles cadastrales, inclure le GeoJSON si disponible :",
  "<map-data>{\"center\":[LAT,LNG],\"zoom\":17,\"title\":\"Parcelle XXX\",\"bbox\":[minLon,minLat,maxLon,maxLat],\"geojson\":{GeoJSON_ICI}}</map-data>",
  "REGLES :",
  "- Ne montre ce bloc QUE quand l'utilisateur demande explicitement une localisation ou une visualisation cartographique.",
  "- Les coordonnees sont TOUJOURS en WGS84 (EPSG:4326) : center=[latitude, longitude].",
  "- Le JSON doit etre valide et sur UNE SEULE ligne sans retour chariot a l'interieur.",
  "- Tu peux inclure plusieurs blocs <map-data> dans une meme reponse si plusieurs localisations sont demandees.",
  "- N'inclus PAS ce bloc pour des questions generales sur les CRS, outils ou scripts.",
  "",
  "== EXEMPLES DE RAISONNEMENT (few-shot) ==",
  "",
  "Exemple 1 - Demande : 'Charge les stations qualite eau de Haute-Garonne'",
  "[PLAN]",
  "  - Outil REST loadHubEauStations couvre exactement ce besoin",
  "  - Pas de prerequis : Hub'Eau API publique sans auth",
  "[EXECUTE] loadHubEauStations({station_type:'quality', department:'31', layerName:'HubEau_Qualite_31'})",
  "[VERIFY] Verifie que count > 0 et que la couche apparait dans le panneau couches",
  "[REPORT] '147 stations qualite charges depuis Hub'Eau (departement 31). CRS WGS84, reprojection L93 disponible si besoin.'",
  "",
  "Exemple 2 - Demande : 'Detecte les arbres sur l'orthophoto chargee'",
  "[PLAN]",
  "  - Identifier la couche raster active via getLayersCatalog",
  "  - Lancer segmentRasterWithSAM en mode text_prompt='trees'",
  "  - Charger le GeoJSON resultat",
  "[EXECUTE] getLayersCatalog() puis segmentRasterWithSAM({rasterPath, outputGeojson, mode:'text_prompt', textPrompt:'trees'})",
  "[VERIFY] feature_count > 0 et couche 'SAM_trees' presente",
  "[REPORT] 'X polygones d'arbres detectes par SAM (modele vit_h, duree Ys). Appliquer un style ?'",
  "",
  "Exemple 3 - Demande triviale : 'Quel est le CRS de la couche cadastre ?'",
  "Reponse directe sans phases : 'EPSG:4326 (WGS84). Reprojection vers Lambert 93 recommandee.'",
].join("\n");

const PYQGIS_REPAIR_SYSTEM_PROMPT = [
  "Tu es un expert PyQGIS charge de corriger un script casse.",
  "REGLE : reponds UNIQUEMENT avec un bloc ```python``` corrige. Aucun texte avant ou apres.",
  "",
  "REGLES DE CORRECTION :",
  "- Applique la correction minimale qui resout l'erreur",
  "- Le script doit etre executable tel quel dans une console QGIS",
  "- Variables disponibles : iface, QgsProject, processing, et toutes classes Qgs*",
  "- N'invente PAS de couches, champs, CRS ni variables absentes du contexte",
  "- Importe QColor depuis qgis.PyQt.QtGui si besoin de couleurs",
  "- Pour les f-strings avec accentues : utilise la concatenation str() + str() plutot que f-strings si probleme d'encodage",
  "- Termine toujours par iface.messageBar().pushSuccess() ou pushInfo()",
  "- Si erreur 'layer not found' : ajoute une verification if lyr is None avec message d'erreur clair",
  "- Si erreur de CRS : verifie que la couche est en EPSG:2154 avant traitement",
].join("\n");

function isOpenRouterFreeQuotaError(message: string): boolean {
  return message.toLowerCase().includes("free-models-per-day");
}

function extractOpenRouterMessageText(content: unknown): string {
  if (typeof content === "string") {
    return content.trim();
  }

  if (!Array.isArray(content)) {
    return "";
  }

  return content
    .map((part) => {
      if (typeof part === "string") {
        return part;
      }

      if (
        part &&
        typeof part === "object" &&
        "text" in part &&
        typeof part.text === "string"
      ) {
        return part.text;
      }

      return "";
    })
    .join("")
    .trim();
}

function buildRepairPrompt(input: RepairPythonScriptInput): string {
  const layerList =
    input.availableLayerNames && input.availableLayerNames.length > 0
      ? `Couches REELLEMENT disponibles dans QGIS (utilise UNIQUEMENT ces noms) :\n${input.availableLayerNames.map((n) => `- "${n}"`).join("\n")}`
      : null;

  return [
    "Corrige le script PyQGIS suivant pour qu'il s'execute correctement dans QGIS.",
    "Renvoie UNIQUEMENT un bloc ```python``` corrige, sans aucun texte autour.",
    "",
    "IMPORTANT : N'invente PAS de noms de couches. Utilise uniquement les noms de couches fournis ci-dessous.",
    layerList,
    "",
    "Demande utilisateur :",
    input.latestUserMessage,
    "",
    input.workspaceSnapshot,
    "",
    input.layerContext ||
      "Aucune couche n'est attachee explicitement au contexte de cette demande.",
    "",
    "Erreur observee :",
    input.errorMessage,
    input.traceback ? `Traceback complet :\n${input.traceback}` : null,
    "",
    "Script a corriger :",
    "```python",
    input.failedScript.trim(),
    "```",
  ]
    .filter(Boolean)
    .join("\n");
}

function isOllamaGenerateEndpoint(endpoint: string): boolean {
  return /\/api\/generate\b/.test(endpoint);
}

function deriveOllamaChatEndpoint(endpoint: string): string {
  return endpoint.replace(/\/api\/generate\b/, "/api/chat");
}

function isTransientNetworkError(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  const msg = err.message.toLowerCase();
  return (
    msg.includes("failed to fetch") ||
    msg.includes("networkerror") ||
    msg.includes("econnreset") ||
    msg.includes("etimedout") ||
    msg.includes("network request failed")
  );
}

async function withRetry<T>(
  fn: () => Promise<T>,
  maxAttempts = 3,
  signal?: AbortSignal,
): Promise<T> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      if (!isTransientNetworkError(err) || attempt === maxAttempts) throw err;
      await new Promise((r) => setTimeout(r, 500 * attempt));
    }
  }
  throw lastError;
}

async function streamLocalResponse(
  endpoint: string,
  body: Record<string, unknown>,
  messageId: string,
  signal?: AbortSignal,
): Promise<string> {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, stream: true }),
    signal,
  });

  if (!response.ok || !response.body) {
    const errorText = await response.text().catch(() => "");
    throw new Error(
      `Le modele local a renvoye une erreur HTTP ${response.status}${errorText ? ` : ${errorText.slice(0, 200)}` : ""}.`,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const chunks: string[] = [];
  const isOpenAI = /\/v1\/chat\/completions/.test(endpoint);
  
  // Démarrer le streaming dans le store et mettre à jour la phase thinking
  useStreamingStore.getState().startStreaming(messageId);
  useThinkingStore.getState().setPhase("STREAMING_RESPONSE");
  useSmartSuggestionsStore.getState().completeProcessing(); // Fermer la barre de suggestions

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value, { stream: true });
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        if (isOpenAI) {
          if (!trimmed.startsWith("data: ")) continue;
          const data = trimmed.slice(6);
          if (data === "[DONE]") break;
          const parsed = JSON.parse(data) as { choices?: Array<{ delta?: { content?: string } }> };
          const delta = parsed.choices?.[0]?.delta?.content;
          if (delta) {
            chunks.push(delta);
            // Envoyer le chunk au store en temps réel
            useStreamingStore.getState().addChunk(delta);
          }
        } else {
          const parsed = JSON.parse(trimmed) as {
            message?: { content?: string };
            response?: string;
            done?: boolean;
          };
          let content = "";
          if (parsed.message?.content) content = parsed.message.content;
          else if (parsed.response) content = parsed.response;
          
          if (content) {
            chunks.push(content);
            useStreamingStore.getState().addChunk(content);
          }
          if (parsed.done) break;
        }
      } catch {
        /* skip malformed lines */
      }
    }
  }

  const fullText = chunks.join("").trim();
  useStreamingStore.getState().completeStreaming();
  
  return fullText || "Reponse vide du modele local.";
}

async function generateLocalReply(
  settings: AppSettings,
  prompt: string,
  options?: {
    signal?: AbortSignal;
    system?: string;
  },
): Promise<string> {
  const systemContent =
    (settings.systemPromptOverride?.trim() || options?.system || DEFAULT_LOCAL_SYSTEM_PROMPT);

  // Timeout local : 5 minutes max (modèles lents peuvent prendre longtemps)
  const timeoutMs = 5 * 60 * 1000;
  const timeoutController = new AbortController();
  const timeoutId = setTimeout(() => timeoutController.abort(), timeoutMs);
  const combinedSignal = options?.signal
    ? (AbortSignal as unknown as { any: (signals: AbortSignal[]) => AbortSignal }).any
      ? (AbortSignal as unknown as { any: (signals: AbortSignal[]) => AbortSignal }).any([options.signal, timeoutController.signal])
      : options.signal
    : timeoutController.signal;

  const cleanup = () => clearTimeout(timeoutId);

  // Prefer chat API for better conversation quality
  const useChat = isOllamaGenerateEndpoint(settings.localEndpoint);
  const endpoint = useChat
    ? deriveOllamaChatEndpoint(settings.localEndpoint)
    : settings.localEndpoint;

  let contextWindow = settings.contextWindow ?? 0;
  
  if (contextWindow <= 0) {
    try {
      const specs = await getSystemSpecs();
      if (specs && specs.source === "python_psutil") {
        const totalRam = specs.ram_total_gb;
        const totalVram = specs.gpu_vram_gb;
        
        // Si la machine a beaucoup de VRAM ou RAM, on peut se permettre 8k
        if (totalVram >= 8 || totalRam >= 16) {
          contextWindow = 8192;
        } 
        // Machine moyenne
        else if (totalVram >= 4 || totalRam >= 8) {
          contextWindow = 4096;
        } 
        // Petite machine
        else {
          contextWindow = 2048;
        }
      } else {
        // Fallback conservateur par défaut
        contextWindow = 4096;
      }
    } catch {
      contextWindow = 4096;
    }
  }

  const genParams = {
    temperature: settings.temperature ?? 0.7,
    top_p: settings.topP ?? 0.95,
    num_predict: settings.maxTokens ?? 8192,
    repeat_penalty: settings.repeatPenalty ?? 1.1,
    num_ctx: contextWindow,
    num_gpu: settings.numGpu ?? -1,
  };

  const keepAlive = settings.keepAlive ?? "1h";

  const body = useChat
    ? {
        model: settings.localModel,
        messages: [
          { role: "system", content: systemContent },
          { role: "user", content: prompt },
        ],
        stream: false,
        keep_alive: keepAlive,
        options: genParams,
      }
    : /\/v1\/chat\/completions/.test(settings.localEndpoint)
      ? {
          model: settings.localModel,
          messages: [
            { role: "system", content: systemContent },
            { role: "user", content: prompt },
          ],
          stream: false,
          temperature: genParams.temperature,
          top_p: genParams.top_p,
          max_tokens: genParams.num_predict,
          frequency_penalty: genParams.repeat_penalty - 1,
        }
      : {
          model: settings.localModel,
          prompt,
          stream: false,
          system: systemContent,
          keep_alive: keepAlive,
          options: genParams,
        };

  if (settings.streamingEnabled) {
    try {
      const messageId = createMessageId();
      const result = await withRetry(
        () => streamLocalResponse(endpoint, body, messageId, combinedSignal),
        3,
        combinedSignal,
      );
      cleanup();
      return result;
    } catch (err) {
      cleanup();
      if ((err as Error)?.name === "AbortError" && timeoutController.signal.aborted) {
        throw new Error(
          `Le modèle local a dépassé le délai de 5 minutes. Choisissez un modèle plus léger ou augmentez les ressources Ollama.`,
        );
      }
      if (isTransientNetworkError(err)) {
        throw new Error(
          `Impossible de joindre le modele local sur ${endpoint} apres 3 tentatives. Verifie qu'Ollama est lance.`,
        );
      }
      throw err;
    }
  }

  let response: Response;
  try {
    response = await withRetry(
      () => fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: combinedSignal,
      }),
      3,
      combinedSignal,
    );
  } catch (err) {
    cleanup();
    if ((err as Error)?.name === "AbortError" && timeoutController.signal.aborted) {
      throw new Error(
        `Le modèle local a dépassé le délai de 5 minutes. Choisissez un modèle plus léger ou augmentez les ressources Ollama.`,
      );
    }
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes("Failed to fetch") || msg.includes("NetworkError") || msg.includes("tentatives")) {
      throw new Error(
        `Impossible de joindre le modele local sur ${endpoint}. Verifie qu'Ollama est lance et accessible.`,
      );
    }
    throw err;
  }

  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    throw new Error(
      `Le modele local a renvoye une erreur HTTP ${response.status}${errorText ? ` : ${errorText.slice(0, 200)}` : ""}.`,
    );
  }

  const data = (await response.json()) as Record<string, unknown>;

  // Ollama /api/chat format
  if (data.message && typeof data.message === "object") {
    const msg = data.message as Record<string, unknown>;
    if (typeof msg.content === "string" && msg.content.trim()) {
      cleanup();
      return msg.content.trim();
    }
  }

  // Ollama /api/generate format
  if (typeof data.response === "string" && data.response.trim()) {
    cleanup();
    return data.response.trim();
  }

  // OpenAI-compatible format
  if (Array.isArray(data.choices) && data.choices.length > 0) {
    const choice = data.choices[0] as Record<string, unknown>;
    const choiceMsg = choice.message as Record<string, unknown> | undefined;
    if (choiceMsg && typeof choiceMsg.content === "string" && choiceMsg.content.trim()) {
      cleanup();
      return choiceMsg.content.trim();
    }
  }

  // Generic fallback
  if (typeof data.content === "string" && data.content.trim()) {
    cleanup();
    return data.content.trim();
  }

  cleanup();
  return "Reponse vide du modele local.";
}

async function generateOpenRouterRepairReply(
  settings: AppSettings,
  prompt: string,
  signal?: AbortSignal,
): Promise<string> {
  const apiKey = settings.openrouterApiKey || getConfiguredOpenRouterApiKey();
  if (!apiKey) {
    throw new Error("Aucune cle API OpenRouter n'est configuree.");
  }

  const response = await fetch(
    `${settings.openrouterEndpoint.replace(/\/+$/, "")}/chat/completions`,
    {
      method: "POST",
      headers: buildOpenRouterHeaders(apiKey, settings),
      body: JSON.stringify({
        model: settings.openrouterExecutorModel,
        messages: [
          {
            role: "system",
            content: PYQGIS_REPAIR_SYSTEM_PROMPT,
          },
          {
            role: "user",
            content: prompt,
          },
        ],
        stream: false,
        provider: {
          order:
            settings.openrouterProviderOrder.length > 0
              ? settings.openrouterProviderOrder
              : undefined,
          allow_fallbacks: settings.openrouterAllowFallbacks,
          require_parameters: false,
          data_collection: settings.openrouterDataCollection,
        },
        plugins: settings.openrouterUseResponseHealing
          ? [{ id: "response-healing" }]
          : undefined,
        zdr: settings.openrouterOnlyZdr,
        temperature: settings.temperature,
        top_p: settings.topP,
        max_tokens: settings.maxTokens,
      }),
      signal,
    },
  );

  const payload = (await response.json()) as {
    choices?: Array<{
      message?: {
        content?: unknown;
      };
    }>;
    error?: {
      message?: string;
    };
  };

  if (!response.ok) {
    throw new Error(
      payload.error?.message ||
        `OpenRouter a renvoye une erreur HTTP ${response.status}.`,
    );
  }

  const content = extractOpenRouterMessageText(
    payload.choices?.[0]?.message?.content,
  );
  return content || "Reponse vide d'OpenRouter.";
}

export async function repairPythonScriptWithProvider(
  input: RepairPythonScriptInput,
): Promise<string> {
  const prompt = buildRepairPrompt(input);
  const { settings } = input;

  if (settings.provider === "local") {
    return generateLocalReply(settings, prompt, {
      signal: input.signal,
      system: PYQGIS_REPAIR_SYSTEM_PROMPT,
    });
  }

  if (settings.provider === "google") {
    if (!settings.googleApiKey.trim() && !getConfiguredGeminiApiKey()) {
      throw new Error("Aucune cle API Gemini n'est configuree.");
    }

    const chat = getGeminiChat(settings);
    const response = await chat.sendMessage({
      message: prompt,
      config: {
        ...buildGeminiConfig(settings),
        systemInstruction: PYQGIS_REPAIR_SYSTEM_PROMPT,
        abortSignal: input.signal,
      },
    });

    return response.text || "Reponse vide de Gemini.";
  }

  if (settings.provider === "nvidia") {
    const apiKey = settings.nvidiaApiKey.trim() || getConfiguredNvidiaApiKey();
    if (!apiKey) {
      throw new Error("Aucune cle API NVIDIA NIM n'est configuree.");
    }
    const messages: ChatMessage[] = [
      { role: "system", content: PYQGIS_REPAIR_SYSTEM_PROMPT },
      { role: "user", content: prompt },
    ];
    const full = await gatewayStreamToText(
      {
        model: settings.nvidiaModel,
        messages,
        api_keys: { nvidia_nim: apiKey },
        signal: input.signal,
      },
    );
    return full || "Reponse vide de NVIDIA NIM.";
  }

  try {
    return await generateOpenRouterRepairReply(settings, prompt, input.signal);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Erreur OpenRouter inconnue.";

    if (!isOpenRouterFreeQuotaError(message)) {
      throw error;
    }

    appendDebugEvent({
      level: "warning",
      source: "llm",
      title: "Fallback reparation OpenRouter vers local",
      message:
        "Quota journalier OpenRouter gratuit atteint pendant la reparation automatique. Bascule sur le modele local.",
      details: `modele_local=${settings.localModel}\nendpoint_local=${settings.localEndpoint}\nraison=${message}`,
    });

    return generateLocalReply(settings, prompt, {
      signal: input.signal,
      system: PYQGIS_REPAIR_SYSTEM_PROMPT,
    });
  }
}

/**
 * Branche Gateway : tout le chat passe par le gateway LiteLLM (NVIDIA NIM au coeur).
 * Active uniquement si useGatewayStore.config.useGateway === true (OFF par defaut),
 * donc 100% additif : le comportement actuel reste inchange tant qu'on ne l'active pas.
 */
/**
 * Source de vérité unique pour la clé NVIDIA : la clé saisie dans l'onglet
 * Provider (settings.nvidiaApiKey) doit fonctionner dans TOUTES les voies
 * (chat, fédération, agent), pas seulement dans l'onglet Gateway. On la fusionne
 * donc par-dessus les clés du store gateway (qui peuvent contenir d'autres
 * providers : openrouter, gemini...).
 */
function resolveApiKeys(input: GenerateAssistantReplyInput): ApiKeys {
  const gwKeys = useGatewayStore.getState().config.apiKeys;
  const settingsKey =
    input.settings.nvidiaApiKey?.trim() || getConfiguredNvidiaApiKey();
  return settingsKey ? { ...gwKeys, nvidia_nim: settingsKey } : gwKeys;
}

/**
 * Mode "SIG Intelligent" : la federation multi-agents route la requete vers le
 * meilleur agent NVIDIA selon la tache (code / vision / raisonnement...).
 */
async function generateViaFederation(
  input: GenerateAssistantReplyInput,
  apiKeysOverride?: Partial<ApiKeys>,
): Promise<string> {
  const thinkingStore = useThinkingStore.getState();
  const streamingStore = useStreamingStore.getState();
  const gateway = useGatewayStore.getState().config;

  const smartReq = {
    query: input.latestUserMessage,
    context: input.layerContext ? { contexte_sig: input.layerContext } : undefined,
    // Override éventuel (ex: clé saisie dans la page Paramètres du provider NVIDIA)
    // fusionné par-dessus les clés du gateway (conserve ollama_base_url, etc.).
    api_keys: { ...gateway.apiKeys, ...apiKeysOverride },
  };

  thinkingStore.setPhase("ANALYZING_INTENT", {
    message: "Fédération multi-agents : routage de votre demande...",
    subMessage: "Sélection du meilleur agent NVIDIA selon la tâche",
  });
  streamingStore.startStreaming(createMessageId());

  const handleSmartEvent = (ev: AgentStreamEvent) => {
    if (ev.type === "progress") {
      thinkingStore.updateSubMessage(ev.message);
    }
  };

  const buildFull = (result: { routing?: string | null; agent_results?: Array<{ model_used?: string; content?: string; success?: boolean; error?: string }>; error?: string; synthesis?: string | null }): string => {
    const agent = result.agent_results?.[0];
    const header = result.routing
      ? `🧭 Agent : **${result.routing}**`
        + (agent?.model_used ? ` · modèle \`${agent.model_used}\`` : "")
        + "\n\n"
      : "";
    // Surface l'erreur réelle (agent puis résultat) au lieu d'un message générique
    // muet — sinon l'utilisateur ne sait pas pourquoi rien ne s'affiche.
    const agentError = agent && agent.success === false ? agent.error : undefined;
    const content =
      (agent?.content && agent.content.trim())
      || (agentError ? `⚠️ Échec de l'agent : ${agentError}` : "")
      || (result.error ? `⚠️ ${result.error}` : "")
      || "⚠️ Aucune réponse du modèle. Vérifiez la clé API NVIDIA (Paramètres) et le quota.";
    const synthesis = result.synthesis
      ? `\n\n---\n**Synthèse :** ${result.synthesis}`
      : "";
    return header + content + synthesis;
  };

  try {
    // Tentative streaming SSE réel
    const { result } = await smartProcessStream(smartReq, handleSmartEvent, input.signal);
    const full = buildFull(result);
    streamingStore.addChunk(full);
    setTimeout(() => {
      thinkingStore.reset();
      streamingStore.completeStreaming();
    }, 300);
    return full;
  } catch (_streamErr) {
    // Fallback : appel bloquant si le backend ne supporte pas encore le streaming
    try {
      const result = await gatewaySmartProcess({
        ...smartReq,
        signal: input.signal,
      });
      const full = buildFull(result);
      streamingStore.addChunk(full);
      setTimeout(() => {
        thinkingStore.reset();
        streamingStore.completeStreaming();
      }, 300);
      return full;
    } catch (error) {
      thinkingStore.reset();
      streamingStore.completeStreaming();
      throw error;
    }
  }
}

/**
 * Mode "Action" : boucle de tool-calling. Le LLM appelle des outils QGIS
 * (lister/filtrer/zoomer/styler...) jusqu'a accomplir la demande, puis resume.
 * Les actions destructives sont filtrees par les guardrails cote backend.
 */
async function generateViaAgent(
  input: GenerateAssistantReplyInput,
  opts?: { model?: string; maxIters?: number; autoMode?: boolean },
): Promise<string> {
  const thinkingStore = useThinkingStore.getState();
  const streamingStore = useStreamingStore.getState();
  const gateway = useGatewayStore.getState().config;

  const agentReq = {
    query: input.prompt,
    model: opts?.model ?? gateway.defaultAlias,
    max_iters: opts?.maxIters ?? 40,
    auto_mode: opts?.autoMode ?? gateway.autoMode,
    api_keys: resolveApiKeys(input),
  };

  thinkingStore.setPhase("EXECUTING_TOOLS", {
    message: "Agent SIG autonome : analyse et action...",
    subMessage: "Planification puis exécution d'outils QGIS",
    modelName: agentReq.model,
  });
  streamingStore.startStreaming(createMessageId());

  /**
   * Traduit les événements SSE de la boucle agent en mises à jour du store
   * de raisonnement (ThinkingStore). Libellés en français.
   */
  const handleAgentEvent = (ev: AgentStreamEvent) => {
    switch (ev.type) {
      case "iteration":
        thinkingStore.updateSubMessage(`Itération ${ev.i} en cours…`);
        break;
      case "tool_start":
        thinkingStore.setPhase("EXECUTING_TOOLS", {
          message: `🔧 ${ev.tool} en cours…`,
          subMessage: "Exécution de l'outil QGIS",
        });
        break;
      case "tool_result":
        thinkingStore.updateSubMessage(
          ev.blocked
            ? `⛔ ${ev.tool} bloqué par la sécurité`
            : `✓ ${ev.tool} terminé`,
        );
        break;
      default:
        break;
    }
  };

  try {
    // Tentative streaming SSE réel
    const final = await runAgentStream(agentReq, handleAgentEvent, input.signal);
    const toolsLine = final.trace_len
      ? `🔧 ${final.trace_len} outil(s) exécuté(s)\n\n`
      : "";
    const full = toolsLine + (final.content || "Aucune réponse produite.");

    // Streaming du contenu final dans le store (pas de chunks fictifs)
    streamingStore.addChunk(full);
    setTimeout(() => {
      thinkingStore.reset();
      streamingStore.completeStreaming();
    }, 300);
    return full;
  } catch (_streamErr) {
    // Fallback : appel bloquant si le backend ne supporte pas encore le streaming
    try {
      const result = await gatewayRunAgent({
        ...agentReq,
        signal: input.signal,
      });
      const toolsLine = result.trace.length
        ? `🔧 Outils exécutés : ${result.trace.map((t) => t.tool).join(", ")}\n\n`
        : "";
      const full = toolsLine + (result.content || "Aucune réponse produite.");
      streamingStore.addChunk(full);
      setTimeout(() => {
        thinkingStore.reset();
        streamingStore.completeStreaming();
      }, 300);
      return full;
    } catch (error) {
      thinkingStore.reset();
      streamingStore.completeStreaming();
      throw error;
    }
  }
}

async function generateViaGateway(
  input: GenerateAssistantReplyInput,
): Promise<string> {
  const thinkingStore = useThinkingStore.getState();
  const streamingStore = useStreamingStore.getState();
  const gateway = useGatewayStore.getState().config;

  // Mode Action (tool-calling) prioritaire : l'agent agit sur QGIS.
  if (gateway.agentMode) {
    return generateViaAgent(input);
  }
  // Mode SIG Intelligent : on delegue a la federation multi-agents.
  if (gateway.federationMode) {
    return generateViaFederation(input, resolveApiKeys(input));
  }

  try {
    thinkingStore.setPhase("ANALYZING_INTENT", {
      message: "Connexion au gateway NVIDIA NIM...",
      subMessage: `Cerveau : ${gateway.defaultAlias}`,
    });
    streamingStore.startStreaming(createMessageId());
    thinkingStore.setPhase("STREAMING_RESPONSE", { modelName: gateway.defaultAlias });

    const messages: ChatMessage[] = [
      { role: "system", content: DEFAULT_LOCAL_SYSTEM_PROMPT },
      { role: "user", content: input.prompt },
    ];

    const full = await gatewayStreamToText(
      {
        model: gateway.defaultAlias,
        messages,
        api_keys: resolveApiKeys(input),
        signal: input.signal,
      },
      (delta) => streamingStore.addChunk(delta),
    );

    setTimeout(() => {
      thinkingStore.reset();
      streamingStore.completeStreaming();
    }, 300);

    return full || "Operation terminee, sans message complementaire.";
  } catch (error) {
    thinkingStore.reset();
    streamingStore.completeStreaming();
    throw error;
  }
}

async function generateViaNvidia(
  input: GenerateAssistantReplyInput,
): Promise<string> {
  const { settings } = input;
  const thinkingStore = useThinkingStore.getState();
  const streamingStore = useStreamingStore.getState();

  const apiKey = settings.nvidiaApiKey.trim() || getConfiguredNvidiaApiKey();
  // La clé peut aussi être stockée côté plugin (QgsSettings) : dans ce cas le
  // backend l'injecte lui-même, on ne bloque donc pas si le localStorage est vide.
  if (!apiKey && !isProviderConfiguredServerSide("nvidia_nim")) {
    throw new Error("Aucune cle API NVIDIA NIM n'est configuree.");
  }
  const keyOverride = apiKey ? { nvidia_nim: apiKey } : undefined;

  // Mode Auto (défaut) = AGENT AUTONOME : l'agent planifie puis AGIT réellement
  // sur QGIS (géocode les lieux, ajoute des fonds/données, calcule, style, rend,
  // s'auto-corrige) via la boucle de tool-calling. C'est le mode le plus compétent :
  // il répond ET fait. auto_mode + budget d'itérations élevé pour les tâches riches.
  const chosenModel = (settings.nvidiaModel || "").trim();
  if (!chosenModel || chosenModel === NVIDIA_AUTO_MODEL) {
    return generateViaAgent(input, { autoMode: true, maxIters: 18 });
  }

  // Override explicite : l'utilisateur a forcé un modèle précis dans les Paramètres.
  try {
    thinkingStore.setPhase("ANALYZING_INTENT", {
      message: "Connexion a NVIDIA NIM...",
      subMessage: `Modèle forcé : ${chosenModel}`,
    });
    streamingStore.startStreaming(createMessageId());
    thinkingStore.setPhase("STREAMING_RESPONSE", { modelName: chosenModel });

    const messages: ChatMessage[] = [
      { role: "system", content: DEFAULT_LOCAL_SYSTEM_PROMPT },
      { role: "user", content: input.prompt },
    ];

    const full = await gatewayStreamToText(
      {
        model: chosenModel,
        // Si clé locale absente, le backend injecte celle stockée côté plugin.
        api_keys: (keyOverride ?? {}) as ApiKeys,
        messages,
        signal: input.signal,
      },
      (delta) => streamingStore.addChunk(delta),
    );

    setTimeout(() => {
      thinkingStore.reset();
      streamingStore.completeStreaming();
    }, 300);

    return full || "Operation terminee, sans message complementaire.";
  } catch (error) {
    thinkingStore.reset();
    streamingStore.completeStreaming();
    throw error;
  }
}

export async function generateAssistantReply(
  input: GenerateAssistantReplyInput,
): Promise<string> {
  const { settings } = input;

  // Cerveau unifie : si le gateway est active, tout le chat passe par lui (NVIDIA NIM coeur).
  if (useGatewayStore.getState().config.useGateway) {
    return generateViaGateway(input);
  }

  if (settings.provider === "local") {
    // Utiliser l'orchestrateur multi-modèles avec feedback visuel
    const thinkingStore = useThinkingStore.getState();
    
    try {
      // Phase 1: Analyse d'intention
      thinkingStore.setPhase("ANALYZING_INTENT", {
        message: "Analyse de votre demande...",
        subMessage: "Compréhension de l'intention et de la complexité",
      });

      // Passer en streaming mode AVANT d'attendre le LLM pour éviter le vide
      // L'utilisateur verra le bloc streaming se remplir progressivement
      useStreamingStore.getState().startStreaming(createMessageId());
      thinkingStore.setPhase("STREAMING_RESPONSE");

      const result = await orchestrateResponse(
        input.conversation,
        input.latestUserMessage,
        settings,
        input.conversation.mode,
        input.signal,
      );

      // Mise à jour selon l'approche utilisée
      if (result.approach === "HYBRID" || result.approach === "TOOL_CALLING") {
        thinkingStore.setPhase("EXECUTING_TOOLS", {
          message: "Exécution des outils QGIS...",
          subMessage: `Approche: ${result.approach}`,
          modelName: result.modelUsed || undefined,
        });
      } else if (result.approach === "CODE_GENERATION") {
        thinkingStore.setPhase("GENERATING_CODE", {
          message: "Génération du code PyQGIS...",
          subMessage: "Création du script pour QGIS",
          modelName: result.modelUsed || undefined,
        });
      }

      // Simuler le streaming avec la réponse complète pour pas de vide visuel
      // On envoie la réponse progressivement au store streaming
      const response = result.response;
      const chunkSize = 10; // Caractères par chunk
      
      for (let i = 0; i < response.length; i += chunkSize) {
        const chunk = response.slice(i, i + chunkSize);
        useStreamingStore.getState().addChunk(chunk);
        // Petit délai pour donner l'impression d'un vrai streaming
        await new Promise(r => setTimeout(r, 2)); // 2ms par chunk
      }

      // Réinitialiser après un délai
      setTimeout(() => {
        thinkingStore.reset();
        useStreamingStore.getState().completeStreaming();
      }, 500);

      return response;

    } catch (error) {
      thinkingStore.reset();
      
      // Fallback vers le traitement local traditionnel
      if (input.conversation.mode !== "free") {
        const routed = await tryHandleLocalIntent(
          input.latestUserMessage,
          input.conversation.mode,
        );
        if (routed.handled && routed.response) {
          return routed.response;
        }
      }

      const freeSystemPrompt = input.conversation.mode === "free"
        ? "Tu es QGISAI+, un assistant conversationnel polyvalent. Reponds en francais de facon naturelle et utile sur tout sujet. Pas de SIG, pas de QGIS, pas de scripts."
        : undefined;

      return generateLocalReply(settings, input.prompt, {
        signal: input.signal,
        system: freeSystemPrompt,
      });
    }
  }

  if (settings.provider === "google") {
    if (!settings.googleApiKey.trim() && !getConfiguredGeminiApiKey()) {
      throw new Error("Aucune cle API Gemini n'est configuree.");
    }

    const chat = getGeminiChat(settings);
    const validImages = filterValidImages(input.attachedImages || []);
    const message =
      validImages.length > 0
        ? buildGeminiParts(input.prompt, validImages)
        : input.prompt;
    const response = await chat.sendMessage({
      message,
      config: {
        ...buildGeminiConfig(settings),
        abortSignal: input.signal,
      },
    });

    return response.text || "Operation SIG terminee, sans message complementaire.";
  }

  if (settings.provider === "nvidia") {
    return generateViaNvidia(input);
  }

  try {
    const result = await generateOpenRouterReply({
      conversationMode: input.conversation.mode,
      latestUserMessage: input.latestUserMessage,
      layerContext: input.layerContext,
      prompt: input.prompt,
      transcript: input.transcript,
      settings,
      signal: input.signal,
      attachedImages: input.attachedImages,
    });

    return result.text || "OpenRouter n'a pas renvoye de contenu exploitable.";
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Erreur OpenRouter inconnue.";

    if (!isOpenRouterFreeQuotaError(message)) {
      throw error;
    }

    appendDebugEvent({
      level: "warning",
      source: "llm",
      title: "Fallback OpenRouter vers local",
      message: "Quota journalier OpenRouter gratuit atteint. Bascule automatique sur le modele local.",
      details: `modele_local=${settings.localModel}\nendpoint_local=${settings.localEndpoint}\nraison=${message}`,
    });

    let localContent: string;
    try {
      localContent = await generateLocalReply(settings, input.prompt, {
        signal: input.signal,
      });
    } catch (localError) {
      const localMessage =
        localError instanceof Error ? localError.message : "Erreur locale inconnue.";
      throw new Error(
        `OpenRouter a atteint son quota gratuit journalier, puis le fallback local a echoue: ${localMessage}`,
      );
    }

    return [
      "> Mode secours local active : quota journalier OpenRouter gratuit atteint.",
      "",
      localContent,
    ].join("\n");
  }
}
