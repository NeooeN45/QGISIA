import { useCallback, useEffect, useRef, useState } from "react";
import { Plus, Layers, Settings as SettingsIcon, Code2, Sparkles, RefreshCw, FileText } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

import { Toaster, toast } from "sonner";

import Chat from "./components/Chat";
import AgentStatusBar from "./components/AgentStatusBar";
import ServerStatusIndicator from "./components/ServerStatusIndicator";
import TaskStatusPanel from "./components/TaskStatusPanel";
import { InstallationWizard } from "./components/InstallationWizard";
import OllamaSetupWizard from "./components/OllamaSetupWizard";
import CommandPalette from "./components/CommandPalette";
import IntroAnimation from "./components/IntroAnimation";
import { useKeyboardShortcuts } from "./hooks/useKeyboardShortcuts";
import {
  ChatConversation,
  ConversationMode,
  createMessage,
} from "./lib/chat-history";
import {
  captureMapSnapshot,
  getLayerDiagnostics,
  getLayerFields,
  getLayersList,
  getLayersCatalog,
  isQgisAvailable,
  LayerSummary,
  runScriptDetailed,
} from "./lib/qgis";
import {
  generateAssistantReply,
  repairPythonScriptWithProvider,
} from "./lib/llm";
import { AppSettings } from "./lib/settings";
import { appendDebugEvent } from "./lib/debug-log";
import { QGIS_TOOLS_REFERENCE } from "./lib/qgis-tools-reference";
import { useSettingsStore } from "./stores/useSettingsStore";
import { useConversationStore } from "./stores/useConversationStore";
import { useLayerStore } from "./stores/useLayerStore";
import { useDocumentStore } from "./stores/useDocumentStore";
import { useUIStore } from "./stores/useUIStore";
import { exportConversationToMarkdown, downloadFile } from "./lib/conversation-export";

type ResetMode = "welcome" | "reset";

async function buildAssistantMessage(mode: ResetMode) {
  if (isQgisAvailable()) {
    const layers = await getLayersList();

    if (layers.length > 0) {
      return createMessage(
        "assistant",
        mode === "welcome"
          ? `Bonjour ! Je suis prêt à vous aider. J'ai détecté les couches suivantes dans votre projet : **${layers.join(", ")}**. Que souhaitez-vous faire ?`
          : `Nouvelle discussion prête. Couches détectées : **${layers.join(", ")}**. Quelle analyse voulez-vous lancer ?`,
      );
    }

    return createMessage(
      "assistant",
      mode === "welcome"
        ? "Bonjour ! Je suis GeoAI QGIS. Votre projet est actuellement vide. Souhaitez-vous que je vous aide à ajouter des données ou à créer une nouvelle couche ?"
        : "Nouvelle discussion prête. Votre projet est vide. Souhaitez-vous de l'aide pour ajouter des données ?",
    );
  }

  return createMessage(
    "assistant",
    mode === "welcome"
      ? "Bonjour ! Je suis votre assistant **GeoAI QGIS**.\n\nJe peux vous aider à générer des scripts PyQGIS, analyser vos couches, filtrer vos données et préparer des opérations SIG dans QGIS."
      : "Nouvelle discussion prête. Comment puis-je vous aider ?",
  );
}

async function buildLayerContext(
  selectedLayerIds: string[],
  layerContextById: Record<string, "layer" | "selection">,
  layers: LayerSummary[],
): Promise<string> {
  if (selectedLayerIds.length === 0) {
    return "";
  }

  const selectedLayers = selectedLayerIds
    .map((layerId) => layers.find((layer) => layer.id === layerId))
    .filter((layer): layer is LayerSummary => Boolean(layer));

  if (selectedLayers.length === 0) {
    return "";
  }

  const layerBlocks = await Promise.all(
    selectedLayers.map(async (layer) => {
      const fields = await getLayerFields(layer.id);
      const diagnostics = await getLayerDiagnostics(layer.id);
      const previewFields = fields.slice(0, 12).join(", ");
      const featureCount =
        typeof layer.featureCount === "number" ? `${layer.featureCount}` : "inconnu";
      const scope = layerContextById[layer.id] === "selection" ? "selection" : "layer";
      const scopeLabel =
        scope === "selection"
          ? layer.selectedFeatureCount > 0
            ? `sélection active (${layer.selectedFeatureCount} entité(s))`
            : "sélection active demandée mais aucune entité n'est sélectionnée"
          : "couche entière";
      const warnings =
        diagnostics && diagnostics.warnings.length > 0
          ? `  alertes: ${diagnostics.warnings.join(" | ")}`
          : null;

      return [
        `- ${layer.name}`,
        `  id: ${layer.id}`,
        `  portée demandée: ${scopeLabel}`,
        `  type: ${[layer.type, layer.geometryType].filter(Boolean).join(" / ") || "inconnu"}`,
        `  crs: ${layer.crs || "inconnu"}`,
        `  entités: ${featureCount}`,
        `  visibilité: ${layer.visible ? "visible" : "masquée"}`,
        `  opacité: ${Math.round(layer.opacity * 100)}%`,
        layer.subsetString ? `  filtre actif: ${layer.subsetString}` : null,
        warnings,
        previewFields
          ? `  champs: ${previewFields}${fields.length > 12 ? ", ..." : ""}`
          : null,
      ]
        .filter(Boolean)
        .join("\n");
    }),
  );

  return [
    "Contexte QGIS explicitement attaché par l'utilisateur.",
    "Priorise ces couches dans ton analyse et dis clairement quand tu sors de ce périmètre.",
    layerBlocks.join("\n\n"),
  ].join("\n\n");
}

function buildWorkspaceSnapshot(layers: LayerSummary[]): string {
  if (layers.length === 0) {
    return [
      "Snapshot automatique du projet QGIS courant : aucune couche chargee.",
      "REGLE ABSOLUE : n'invente aucune couche, aucun champ, aucune valeur. Le projet est vide.",
    ].join("\n");
  }

  const exactNames = layers.map((l) => `"${l.name}"`).join(", ");

  const layerLines = layers.slice(0, 12).map((layer) => {
    const typeLabel =
      [layer.type, layer.geometryType].filter(Boolean).join(" / ") || "inconnu";
    const featureCount =
      typeof layer.featureCount === "number"
        ? `${layer.featureCount} entite(s)`
        : "nombre d'entites inconnu";
    const crsWarning =
      layer.crs && layer.crs !== "EPSG:2154" && layer.type === "vector"
        ? `  ⚠ CRS non Lambert 93 : ${layer.crs} → reprojectLayer recommande`
        : null;

    return [
      `- ${layer.name}`,
      `  id: ${layer.id}`,
      `  type: ${typeLabel}`,
      `  crs: ${layer.crs || "inconnu"}`,
      `  contenu: ${featureCount}`,
      `  visibilite: ${layer.visible ? "visible" : "masquee"}`,
      `  opacite: ${Math.round(layer.opacity * 100)}%`,
      layer.subsetString ? `  filtre actif: ${layer.subsetString}` : null,
      crsWarning,
    ]
      .filter(Boolean)
      .join("\n");
  });

  const remainingCount = layers.length - layerLines.length;

  return [
    "Snapshot automatique du projet QGIS courant.",
    `Nombre de couches chargees: ${layers.length}.`,
    `NOMS EXACTS DES COUCHES (utilise UNIQUEMENT ces noms dans mapLayersByName) : ${exactNames}`,
    layerLines.join("\n\n"),
    remainingCount > 0
      ? `... ${remainingCount} couche(s) supplementaire(s) non listee(s).`
      : null,
  ]
    .filter(Boolean)
    .join("\n\n");
}

function buildAttachmentsContext(): string {
  // Recupere les documents attaches par l'utilisateur (PDF, DOCX, texte, images)
  // depuis le store global. Les images sont injectees separement via vision.
  const documents = useDocumentStore.getState().documents;
  if (documents.length === 0) return "";

  const textuals = documents.filter((d) => d.kind !== "image" && d.content.trim().length > 0);
  const images = documents.filter((d) => d.kind === "image");

  const blocks: string[] = ["## Pieces jointes fournies par l'utilisateur"];

  if (images.length > 0) {
    blocks.push(
      `\n${images.length} image(s) jointe(s) (visibles uniquement par les modeles vision) : ${images
        .map((i) => i.name)
        .join(", ")}`,
    );
  }

  // Limite pour eviter de saturer le contexte (~150 Ko total max).
  const MAX_TOTAL = 150_000;
  let used = 0;
  for (const doc of textuals) {
    const remaining = MAX_TOTAL - used;
    if (remaining < 500) {
      blocks.push(`\n[... ${textuals.length - blocks.length + 1} document(s) tronques ...]`);
      break;
    }
    const content =
      doc.content.length > remaining
        ? `${doc.content.slice(0, remaining - 200)}\n[... tronque ...]`
        : doc.content;
    used += content.length;
    blocks.push(
      `\n### ${doc.name} (${(doc.size / 1024).toFixed(1)} Ko)\n` +
        "```\n" +
        content +
        "\n```",
    );
  }

  return blocks.join("\n");
}

function buildModelPrompt(
  conversation: ChatConversation,
  layerContext: string,
  workspaceSnapshot: string,
): string {
  const transcript = buildRecentTranscript(conversation);
  const attachmentsContext = buildAttachmentsContext();

  const modeInstruction =
    conversation.mode === "free"
      ? [
          "Tu es QGISAI+, un assistant conversationnel polyvalent. Reponds en francais.",
          "MODE : Discussion libre — pas de QGIS, pas de SIG, pas de scripts. Contenu general uniquement.",
          "ROLE : assistant intelligent, curieux et utile sur tout sujet : sciences, histoire, programmation, nature, foresterie, ecologie, mathematiques, culture, etc.",
          "REGLES :",
          "- Reponds de facon naturelle et conversationnelle, sans jargon technique SIG.",
          "- Sois precis, factuel et nuance. Admets l'incertitude si necessaire.",
          "- Tu peux partager des opinions argumentees si demande.",
          "- Pas de blocs de code PyQGIS, pas d'outils bridge, pas de references QGIS.",
          "- Longueur adaptee : courte pour les questions simples, detaillee pour les sujets complexes.",
        ].join("\n")
      : [
          "Tu es l'agent operateur de QGISIA+. Reponds en francais.",
          "ROLE : executer les taches SIG de maniere autonome, complete et sans hesitation.",
          "PHILOSOPHIE D'AGENT :",
          "- EXECUTE sans demander permission pour chaque etape logique",
          "- ANTICIPE : donnees francaises = Lambert 93 (EPSG:2154) automatiquement si CRS != EPSG:2154",
          "- ENCHAINE : plusieurs taches = les executer toutes dans l'ordre logique",
          "- RAPPORTE : confirme avec resultats concrets (noms couches, comptes, surfaces)",
          "REGLES ABSOLUES :",
          "- N'invente JAMAIS de couches, champs, CRS ou resultats absents du contexte.",
          "- Utilise TOUJOURS les outils bridge natifs en priorite avant PyQGIS libre.",
          "- PyQGIS : UN SEUL bloc complet et executable avec iface.messageBar() a la fin.",
          "- N'affirme jamais un proprietaire de parcelle sans source publique explicite.",
          "FORMATS : outil bridge → liste les appels dans l'ordre | PyQGIS → un seul bloc complet.",
        ].join("\n");

  if (conversation.mode === "free") {
    return [
      modeInstruction,
      attachmentsContext,
      "",
      "Historique récent de la conversation :",
      transcript,
    ]
      .filter((s) => s !== "" && s !== undefined)
      .join("\n\n");
  }

  return [
    modeInstruction,
    "",
    QGIS_TOOLS_REFERENCE,
    "",
    workspaceSnapshot,
    "",
    layerContext || "Aucune couche n'est attachée explicitement au contexte de cette discussion.",
    attachmentsContext,
    "",
    "Historique récent de la conversation :",
    transcript,
    "",
    "Donne une réponse opérationnelle, concise et exploitable dans QGIS.",
  ]
    .filter((s) => s !== "" && s !== undefined)
    .join("\n\n");
}

function buildRecentTranscript(conversation: ChatConversation): string {
  const recentMessages = conversation.messages.slice(-12);
  return recentMessages
    .map((message) =>
      `${message.role === "user" ? "Utilisateur" : "Assistant"}:\n${message.content}`,
    )
    .join("\n\n");
}

interface AutoExecutionAttempt {
  attempt: number;
  repaired: boolean;
  resultMessage: string;
  script: string;
  success: boolean;
}

function looksLikePythonScript(value: string): boolean {
  const normalized = value.trim();
  if (!normalized) {
    return false;
  }

  return /(iface|Qgs|processing\b|import\s+\w+|from\s+\w+\s+import)/.test(
    normalized,
  );
}

function extractFirstPythonBlock(content: string): string | null {
  const explicitMatch = content.match(/```(?:python|py)\s*\r?\n([\s\S]*?)```/i);
  if (explicitMatch?.[1]) {
    return explicitMatch[1].trim();
  }

  const genericMatch = content.match(/```\s*\r?\n([\s\S]*?)```/);
  if (genericMatch?.[1] && looksLikePythonScript(genericMatch[1])) {
    return genericMatch[1].trim();
  }

  return null;
}

function replaceFirstPythonBlock(content: string, script: string): string {
  const replacement = ["```python", script.trim(), "```"].join("\n");
  const explicitPattern = /```(?:python|py)\s*\r?\n[\s\S]*?```/i;
  if (explicitPattern.test(content)) {
    return content.replace(explicitPattern, replacement);
  }

  const genericPattern = /```\s*\r?\n([\s\S]*?)```/;
  const genericMatch = content.match(genericPattern);
  if (genericMatch?.[1] && looksLikePythonScript(genericMatch[1])) {
    return content.replace(genericPattern, replacement);
  }

  return [content, replacement].filter(Boolean).join("\n\n");
}

/**
 * Wraps a PyQGIS script with try/except guard rails for better error messages.
 * Skips wrapping if the script already has a top-level try block.
 */
function wrapScriptWithGuardRails(script: string): string {
  if (/^try\s*:/m.test(script.trim())) {
    return script;
  }
  const indented = script
    .split("\n")
    .map((line) => `    ${line}`)
    .join("\n");
  return [
    "import traceback as _tb",
    "try:",
    indented,
    "except Exception as _e:",
    '    iface.messageBar().pushCritical("Erreur PyQGIS", str(_e))',
    '    print("=== TRACEBACK ===\\n" + _tb.format_exc())',
    "    raise",
  ].join("\n");
}

/**
 * Extracts layer names referenced via mapLayersByName() in a PyQGIS script.
 */
function extractLayerNamesFromScript(script: string): string[] {
  const pattern = /mapLayersByName\(\s*["']([^"']+)["']\s*\)/g;
  const names: string[] = [];
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(script)) !== null) {
    names.push(match[1]);
  }
  return [...new Set(names)];
}

/**
 * Returns layer names from the script that do NOT exist in the QGIS catalog.
 * Used to detect LLM hallucinations before script execution.
 */
function detectHallucinatedLayers(
  scriptLayerNames: string[],
  catalog: LayerSummary[],
): string[] {
  const realNames = new Set(catalog.map((l) => l.name.toLowerCase()));
  return scriptLayerNames.filter((name) => !realNames.has(name.toLowerCase()));
}

function summarizeExecutionMessage(value: string): string {
  const firstLine = value.split(/\r?\n/).find((line) => line.trim().length > 0) || value;
  return firstLine.trim() || "Erreur non detaillee.";
}

function buildAutoExecutionReport(
  attempts: AutoExecutionAttempt[],
  finalState: "success" | "failed" | "unavailable",
): string {
  const headline =
    finalState === "success"
      ? `> Exécution automatique PyQGIS réussie en ${attempts.length} tentative(s).`
      : finalState === "unavailable"
        ? "> Exécution automatique PyQGIS indisponible : QGIS n'est pas connecté."
        : `> Exécution automatique PyQGIS en échec après ${attempts.length} tentative(s).`;

  const details =
    attempts.length > 0
      ? attempts
          .map((attempt) => {
            const state = attempt.success ? "succès" : "échec";
            const source = attempt.repaired ? "script corrigé" : "script initial";
            return `- tentative ${attempt.attempt} (${source}) : ${state} - ${summarizeExecutionMessage(attempt.resultMessage)}`;
          })
          .join("\n")
      : "- aucun script n'a pu être lancé.";

  const footer =
    finalState === "failed"
      ? "Consulte le Journal diagnostic pour le traceback complet."
      : null;

  return [headline, "", details, footer].filter(Boolean).join("\n");
}

async function maybeAutoExecuteAssistantPythonScript(input: {
  assistantContent: string;
  conversation: ChatConversation;
  latestUserMessage: string;
  layerContext: string;
  refreshLayers: () => Promise<void>;
  settings: AppSettings;
  signal?: AbortSignal;
  workspaceSnapshot: string;
}): Promise<string> {
  const {
    assistantContent,
    conversation,
    latestUserMessage,
    layerContext,
    refreshLayers,
    settings,
    signal,
    workspaceSnapshot,
  } = input;

  if (!settings.autoExecutePythonScripts || conversation.mode === "free") {
    return assistantContent;
  }

  const initialScript = extractFirstPythonBlock(assistantContent);
  if (!initialScript) {
    return assistantContent;
  }

  if (!isQgisAvailable()) {
    appendDebugEvent({
      level: "warning",
      source: "assistant",
      title: "Execution automatique PyQGIS indisponible",
      message:
        "Un script Python a ete genere, mais QGIS n'est pas connecte dans cette session.",
    });

    return [assistantContent, "", buildAutoExecutionReport([], "unavailable")].join(
      "\n\n",
    );
  }

  // ── Guard rail 1: Hallucination detection ────────────────────────────────
  const catalog = await getLayersCatalog().catch(() => [] as LayerSummary[]);
  const scriptLayerNames = extractLayerNamesFromScript(initialScript);
  const hallucinated = detectHallucinatedLayers(scriptLayerNames, catalog);
  const availableLayerNames = catalog.map((l) => l.name);

  if (hallucinated.length > 0) {
    appendDebugEvent({
      level: "warning",
      source: "assistant",
      title: "Couches introuvables dans le script PyQGIS",
      message: `Le script reference des couches qui n'existent pas dans le projet QGIS : ${hallucinated.join(", ")}`,
      details: `Couches disponibles : ${availableLayerNames.join(", ") || "aucune"}`,
    });
    toast.warning(
      `Attention : couche(s) introuvable(s) : ${hallucinated.join(", ")}`,
    );
  }

  const attempts: AutoExecutionAttempt[] = [];
  const maxRepairs = settings.autoRepairPythonScripts
    ? settings.autoRepairMaxAttempts
    : 0;

  let currentScript = initialScript;
  let currentContent = assistantContent;

  for (let repairAttempt = 0; repairAttempt <= maxRepairs; repairAttempt += 1) {
    // ── Guard rail 2: Wrap script with try/except before execution ─────────
    const scriptToRun = wrapScriptWithGuardRails(currentScript);
    // La confirmation utilisateur est inconditionnelle : la boucle de
    // réparation automatique ne peut plus l'escamoter.
    const result = await runScriptDetailed(scriptToRun);

    if (!result) {
      appendDebugEvent({
        level: "warning",
        source: "assistant",
        title: "Execution automatique PyQGIS indisponible",
        message:
          "Le bridge QGIS n'a pas renvoye de resultat detaille pendant l'execution automatique.",
      });

      return [currentContent, "", buildAutoExecutionReport(attempts, "unavailable")].join(
        "\n\n",
      );
    }

    attempts.push({
      attempt: repairAttempt + 1,
      repaired: repairAttempt > 0,
      resultMessage: result.message,
      script: currentScript,
      success: result.ok,
    });

    appendDebugEvent({
      level: result.ok ? "success" : "warning",
      source: "assistant",
      title: result.ok
        ? "Execution automatique PyQGIS reussie"
        : "Execution automatique PyQGIS echouee",
      message: result.message,
      details: [currentScript, result.traceback || ""].filter(Boolean).join("\n\n"),
    });

    if (result.ok) {
      await refreshLayers();
      toast.success(
        repairAttempt > 0
          ? "Script PyQGIS corrigé puis exécuté automatiquement."
          : "Script PyQGIS exécuté automatiquement.",
      );

      // Capturer la carte après exécution réussie
      const capture = await captureMapSnapshot();
      const report = buildAutoExecutionReport(attempts, "success");

      if (capture) {
        // Ajouter la capture comme image markdown à la fin du message
        return [currentContent, "", report, "", `![capture](${capture})`].join(
          "\n\n",
        );
      }

      return [currentContent, "", report].join("\n\n");
    }

    if (repairAttempt >= maxRepairs) {
      break;
    }

    try {
      const repairedContent = await repairPythonScriptWithProvider({
        availableLayerNames,
        errorMessage: result.message,
        failedScript: currentScript,
        layerContext,
        latestUserMessage,
        settings,
        signal,
        traceback: result.traceback,
        workspaceSnapshot,
      });
      const repairedScript = extractFirstPythonBlock(repairedContent);

      if (!repairedScript) {
        appendDebugEvent({
          level: "warning",
          source: "assistant",
          title: "Reparation automatique PyQGIS sans script",
          message:
            "Le modele a tente une reparation, mais n'a pas renvoye de bloc Python exploitable.",
          details: repairedContent,
        });
        break;
      }

      if (repairedScript.trim() === currentScript.trim()) {
        appendDebugEvent({
          level: "warning",
          source: "assistant",
          title: "Reparation automatique PyQGIS inchangee",
          message:
            "Le modele a renvoye un script identique apres echec. La boucle de relance est interrompue.",
        });
        break;
      }

      currentScript = repairedScript;
      currentContent = replaceFirstPythonBlock(currentContent, repairedScript);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "La reparation automatique a echoue.";
      appendDebugEvent({
        level: "error",
        source: "assistant",
        title: "Reparation automatique PyQGIS echouee",
        message,
        details: error instanceof Error ? error.stack : undefined,
      });
      break;
    }
  }

  toast.error("Le script PyQGIS a échoué et n'a pas pu être corrigé automatiquement.");

  return [currentContent, "", buildAutoExecutionReport(attempts, "failed")].join(
    "\n\n",
  );
}

export default function App() {
  const settings = useSettingsStore((s) => s.settings);
  const setSettings = useSettingsStore((s) => s.setSettings);

  const conversations = useConversationStore((s) => s.conversations);
  const activeConversationId = useConversationStore((s) => s.activeConversationId);
  const convStore = useConversationStore;

  const layers = useLayerStore((s) => s.layers);
  const isRefreshingLayers = useLayerStore((s) => s.isRefreshing);
  const refreshLayers = useLayerStore((s) => s.refresh);

  const isLoading = useUIStore((s) => s.isLoading);
  const setIsLoading = useUIStore((s) => s.setIsLoading);
  const setIsQgisConnected = useUIStore((s) => s.setIsQgisConnected);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);

  const abortControllerRef = useRef<AbortController | null>(null);

  const activeConversation = convStore.getState().activeConversation();

  // Dark mode permanent — l'interface est dark-only
  useEffect(() => {
    document.documentElement.classList.add("dark");
    document.documentElement.classList.remove("light");
  }, []);

  const createNewConversation = useCallback(async () => {
    const nextMessage = await buildAssistantMessage(
      conversations.length === 0 ? "welcome" : "reset",
    );
    convStore.getState().createNew(nextMessage);
  }, [conversations.length]);

  const handleExportConversation = useCallback(() => {
    const conv = convStore.getState().activeConversation();
    if (conv) {
      const markdown = exportConversationToMarkdown(conv);
      downloadFile(markdown, `${conv.title || "conversation"}.md`, "text/markdown");
      toast.success("Conversation exportée en Markdown");
    }
  }, []);

  // Keyboard shortcuts
  useKeyboardShortcuts([
    {
      key: "n",
      ctrlKey: true,
      action: () => void createNewConversation(),
      description: "Nouvelle conversation",
    },
    {
      key: "/",
      ctrlKey: true,
      action: () => {
        document.dispatchEvent(new CustomEvent("focusChatInput"));
      },
      description: "Focus sur la zone de chat",
    },
    {
      key: "s",
      ctrlKey: true,
      action: () => handleExportConversation(),
      description: "Sauvegarder la conversation",
    },
    {
      key: "l",
      ctrlKey: true,
      action: () => toggleSidebar(),
      description: "Ouvrir/fermer la sidebar",
    },
  ]);

  const handleUpdateSettings = useCallback(
    (newSettings: typeof settings) => {
      setSettings(newSettings);
      toast.success("Paramètres mis à jour");
    },
    [setSettings],
  );

  const handleSendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      const currentConversation = convStore.getState().activeConversation();

      if (!trimmed || !currentConversation) {
        return;
      }

      const userMessage = createMessage("user", trimmed);
      const conversationSnapshot = {
        ...currentConversation,
        messages: [...currentConversation.messages, userMessage],
      };

      convStore.getState().addUserMessage(userMessage);
      setIsLoading(true);

      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      const currentLayers = useLayerStore.getState().layers;
      const currentSettings = useSettingsStore.getState().settings;
      const doRefresh = useLayerStore.getState().refresh;

      try {
        const layerContext = await buildLayerContext(
          conversationSnapshot.selectedLayerIds,
          conversationSnapshot.layerContextById,
          currentLayers,
        );
        const workspaceSnapshot = buildWorkspaceSnapshot(currentLayers);
        const prompt = buildModelPrompt(
          conversationSnapshot,
          layerContext,
          workspaceSnapshot,
        );
        const attachedImages = useDocumentStore
          .getState()
          .documents.filter((d) => d.kind === "image" && typeof d.dataUrl === "string")
          .map((d) => ({ name: d.name, dataUrl: d.dataUrl as string }));
        const assistantContent = await generateAssistantReply({
          conversation: conversationSnapshot,
          latestUserMessage: trimmed,
          layerContext,
          prompt,
          settings: currentSettings,
          signal: abortController.signal,
          attachedImages,
          transcript: buildRecentTranscript(conversationSnapshot),
        });
        const assistantContentWithAutoExecution =
          await maybeAutoExecuteAssistantPythonScript({
            assistantContent,
            conversation: conversationSnapshot,
            latestUserMessage: trimmed,
            layerContext,
            refreshLayers: doRefresh,
            settings: currentSettings,
            signal: abortController.signal,
            workspaceSnapshot,
          });

        const assistantMessage = createMessage(
          "assistant",
          assistantContentWithAutoExecution,
        );
        convStore
          .getState()
          .addAssistantMessage(currentConversation.id, assistantMessage);
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : typeof error === "string"
              ? error
              : (error as Record<string, unknown>)?.error
                  ? String((error as Record<string, unknown>).error)
                  : "Erreur inattendue lors de la génération.";

        if (
          message === "signal is aborted without reason" ||
          message === "This operation was aborted"
        ) {
          toast.info("Génération arrêtée.");
        } else if (error instanceof DOMException && error.name === "AbortError") {
          toast.info("Génération arrêtée.");
        } else {
          appendDebugEvent({
            level: "error",
            source: "assistant",
            title: "Generation assistant echouee",
            message,
            details:
              error instanceof Error && error.stack
                ? error.stack
                : JSON.stringify(error, null, 2),
          });

          // Message d'erreur enrichi selon le type
          const isNetworkError = message.includes("404") || message.includes("503") || message.includes("502") || message.includes("fetch") || message.includes("Failed to fetch") || message.includes("network");
          const isAuthError    = message.includes("401") || message.includes("403") || message.includes("API key") || message.includes("Unauthorized");
          const isTimeoutError = message.includes("timeout") || message.includes("408") || message.includes("aborted");

          const errorTitle = isNetworkError
            ? "Connexion au serveur impossible"
            : isAuthError
            ? "Clé API invalide ou manquante"
            : isTimeoutError
            ? "Délai d'attente dépassé"
            : "Erreur de génération";

          const errorDescription = isNetworkError
            ? `Le backend QGIS n'est pas joignable. Vérifiez que le plugin est bien lancé dans QGIS et que le serveur HTTP tourne sur le bon port.

Détail : ${message}`
            : isAuthError
            ? `Votre clé API est introuvable ou incorrecte. Rendez-vous dans Paramètres → Clé API pour la mettre à jour.

Détail : ${message}`
            : isTimeoutError
            ? `Le modèle n'a pas répondu dans le délai imparti. Réessayez ou sélectionnez un modèle plus rapide.

Détail : ${message}`
            : `Une erreur inattendue s'est produite lors de la génération de la réponse.

Détail : ${message}`;

          toast.error(errorTitle, {
            description: errorDescription,
            duration: 9000,
          });
        }
      } finally {
        setIsLoading(false);
        abortControllerRef.current = null;
      }
    },
    [setIsLoading],
  );

  const handleToggleLayerSelection = useCallback((layerId: string) => {
    convStore.getState().toggleLayerSelection(layerId);
  }, []);

  const handleSetConversationMode = useCallback(
    (mode: ConversationMode) => {
      convStore.getState().setMode(mode);
    },
    [],
  );

  const handleSetLayerContextScope = useCallback(
    (layerId: string, scope: "layer" | "selection") => {
      convStore.getState().setLayerContextScope(layerId, scope);
    },
    [],
  );

  const handleDeleteConversation = useCallback(
    async (conversationId: string) => {
      const fallback = await buildAssistantMessage("reset");
      convStore.getState().remove(conversationId, fallback);
    },
    [],
  );

  const handleSetLayerVisibility = useCallback(
    async (layerId: string, visible: boolean) => {
      const status = await useLayerStore.getState().setVisibility(layerId, visible);
      if (status) {
        toast.success(status);
      }
    },
    [],
  );

  const handleSetLayerOpacity = useCallback(
    async (layerId: string, opacity: number) => {
      const status = await useLayerStore.getState().setOpacity(layerId, opacity);
      if (status) {
        toast.success(status);
      }
    },
    [],
  );

  const handleZoomToLayer = useCallback(async (layerId: string) => {
    const status = await useLayerStore.getState().zoom(layerId);
    if (status) {
      toast.success(status);
    }
  }, []);

  const stopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setIsLoading(false);
    }
  }, [setIsLoading]);

  // Initialize conversations — marks app as ready once the first message is built
  useEffect(() => {
    let cancelled = false;

    const initialize = async () => {
      const welcomeMsg = await buildAssistantMessage("welcome");
      if (!cancelled) {
        convStore.getState().initialize(welcomeMsg);
        setIsAppReady(true);
      }
    };

    void initialize();
    return () => {
      cancelled = true;
    };
  }, []);

  // Persist conversations on change
  useEffect(() => {
    convStore.getState().persist();
  }, [conversations, activeConversationId]);

  // Auto-select first conversation when active is missing
  useEffect(() => {
    const { activeConversationId: id, conversations: convs } =
      convStore.getState();

    if (!id && convs.length > 0) {
      convStore.getState().select(convs[0].id);
      return;
    }

    if (id && convs.length > 0 && !convs.some((c) => c.id === id)) {
      convStore.getState().select(convs[0].id);
    }
  }, [activeConversationId, conversations]);

  // Refresh layers periodically & check QGIS connection
  // Polling pauses when the tab is hidden to avoid unnecessary background work
  useEffect(() => {
    void refreshLayers();
    setIsQgisConnected(isQgisAvailable());

    const layerInterval = window.setInterval(() => {
      if (!document.hidden) void refreshLayers();
    }, 10000);

    const qgisInterval = window.setInterval(() => {
      if (!document.hidden) setIsQgisConnected(isQgisAvailable());
    }, 3000);

    return () => {
      window.clearInterval(layerInterval);
      window.clearInterval(qgisInterval);
    };
  }, [refreshLayers, setIsQgisConnected]);

  // True once the initial welcome message has been built — drives the loading screen
  const [isAppReady, setIsAppReady] = useState(false);

  // State pour le wizard d'installation Ollama
  const [showInstallationWizard, setShowInstallationWizard] = useState(false);
  const [showOllamaWizard, setShowOllamaWizard] = useState(false);
  const [showCommandPalette, setShowCommandPalette] = useState(false);
  const [showIntroAnimation, setShowIntroAnimation] = useState(
    !localStorage.getItem("qgisia-intro-seen"),
  );
  // Flag: trigger Ollama scan once intro is done
  const [pendingOllamaScan, setPendingOllamaScan] = useState(false);

  const setShowSettings = useUIStore((s) => s.setShowSettings);
  const setShowPluginSetup = useUIStore((s) => s.setShowPluginSetup);

  // Decide whether an Ollama scan is needed on first load
  useEffect(() => {
    const shouldScan = settings.provider === "local" && !settings.localModel;
    if (shouldScan) {
      setPendingOllamaScan(true);
    }
  }, []);

  // Open the Ollama wizard as soon as the intro animation is finished
  useEffect(() => {
    if (!showIntroAnimation && pendingOllamaScan) {
      setPendingOllamaScan(false);
      setShowOllamaWizard(true);
    }
  }, [showIntroAnimation, pendingOllamaScan]);

  const handleOllamaWizardComplete = (model: string) => {
    handleUpdateSettings({
      ...settings,
      localModel: model,
    });
    setShowOllamaWizard(false);
    toast.success(`Modèle ${model} configuré avec succès`);
  };

  // Keyboard shortcuts
  useKeyboardShortcuts([
    {
      key: "k",
      ctrlKey: true,
      action: () => setShowCommandPalette(true),
      description: "Ouvrir la palette de commandes",
    },
  ]);

  // Command palette commands
  const commands = [
    {
      id: "new-conversation",
      label: "Nouvelle discussion",
      description: "Créer une nouvelle conversation",
      icon: <Plus size={18} />,
      action: () => createNewConversation(),
      category: "Conversations",
    },
    {
      id: "refresh-layers",
      label: "Rafraîchir les couches",
      description: "Recharger la liste des couches QGIS",
      icon: <RefreshCw size={18} />,
      action: () => refreshLayers(),
      category: "QGIS",
    },
    {
      id: "open-settings",
      label: "Paramètres IA",
      description: "Ouvrir les paramètres du provider IA",
      icon: <SettingsIcon size={18} />,
      action: () => setShowSettings(true),
      category: "Paramètres",
    },
    {
      id: "open-plugin",
      label: "Installation Plugin",
      description: "Voir les instructions d'installation du plugin QGIS",
      icon: <Code2 size={18} />,
      action: () => setShowPluginSetup(true),
      category: "Paramètres",
    },
    {
      id: "toggle-mode",
      label: "Changer de mode",
      description: "Basculer entre mode Action (QGIS) et mode Libre",
      icon: <Sparkles size={18} />,
      action: () => {
        const currentMode = activeConversation?.mode || "chat";
        handleSetConversationMode(currentMode === "chat" ? "free" : "chat");
      },
      category: "Conversations",
    },
  ];

  return (
    <>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:rounded-xl focus:border-2 focus:border-blue-500 focus:bg-blue-500/10 focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white focus:outline-none"
      >
        Aller au contenu principal
      </a>
      <div id="main-content" className="flex h-screen w-full overflow-hidden">
        <Toaster
          position="bottom-right"
          theme={settings.theme === "light" ? "light" : "dark"}
          richColors
          closeButton
        />

        {/* TODO: intégrer GeoParticlesBackground */}
        {/* {showParticles && <GeoParticlesBackground isDark={settings.theme !== "light"} />} */}

        {/* Elegant loading screen — visible until conversations are initialized */}
        <AnimatePresence>
          {!isAppReady && (
            <motion.div
              key="app-loading"
              className="fixed inset-0 z-[90] flex flex-col items-center justify-center bg-[#131314]"
              initial={{ opacity: 1 }}
              exit={{ opacity: 0, scale: 1.02 }}
              transition={{ duration: 0.4, ease: [0.4, 0, 0.2, 1] }}
              aria-label="Chargement de l'application"
            >
              <motion.div
                className="flex flex-col items-center gap-7"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1, duration: 0.4 }}
              >
                {/* Logo + anneau de progression rotatif (net, sans clignotement) */}
                <div className="relative flex h-16 w-16 items-center justify-center">
                  <motion.span
                    className="absolute inset-0 rounded-full border-2 border-transparent border-t-emerald-400 border-r-emerald-400/40"
                    animate={{ rotate: 360 }}
                    transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                  />
                  <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-500/12 border border-emerald-500/20">
                    <Sparkles size={24} className="text-emerald-400" />
                  </div>
                </div>

                {/* Barre de progression indéterminée (glisse, ne clignote pas) */}
                <div className="h-0.5 w-40 overflow-hidden rounded-full bg-white/[0.06]">
                  <motion.div
                    className="h-full w-1/3 rounded-full bg-gradient-to-r from-transparent via-emerald-400 to-transparent"
                    animate={{ x: ["-140%", "440%"] }}
                    transition={{ duration: 1.3, repeat: Infinity, ease: "easeInOut" }}
                  />
                </div>

                <p className="text-xs text-white/30 font-mono tracking-widest uppercase">
                  Initialisation…
                </p>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>

        <TaskStatusPanel />

        {showIntroAnimation && (
          <IntroAnimation
            onComplete={() => setShowIntroAnimation(false)}
            isFirstTime={!localStorage.getItem("qgisia-intro-seen")}
          />
        )}

        {showInstallationWizard && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
            <div className="w-full max-w-md rounded-3xl border border-white/10 bg-[#131314] p-6 shadow-2xl">
              <InstallationWizard
                onComplete={(selectedModel) => {
                  setShowInstallationWizard(false);
                  toast.success(`Modèle ${selectedModel} installé avec succès`);
                }}
                onCancel={() => setShowInstallationWizard(false)}
              />
            </div>
          </div>
        )}

        {showOllamaWizard && (
          <OllamaSetupWizard
            onComplete={(model) => {
              handleOllamaWizardComplete(model);
              setShowOllamaWizard(false);
            }}
            onClose={() => setShowOllamaWizard(false)}
          />
        )}

        {showCommandPalette && (
          <CommandPalette
            commands={commands}
            onClose={() => setShowCommandPalette(false)}
          />
        )}

        {/* Chat animates in once app is ready; transitions between welcome and active conversation */}
        <AnimatePresence mode="wait">
          {isAppReady && (
            <motion.div
              key="chat-shell"
              className="flex h-full w-full flex-col"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, ease: [0.4, 0, 0.2, 1] }}
            >
              <Chat
                activeConversation={activeConversation}
                activeConversationId={activeConversationId}
                conversations={conversations}
                isLoading={isLoading}
                isRefreshingLayers={isRefreshingLayers}
                layers={layers}
                messages={activeConversation?.messages || []}
                onCreateConversation={createNewConversation}
                onDeleteConversation={handleDeleteConversation}
                onRefreshLayers={refreshLayers}
                onSelectConversation={(id: string) => convStore.getState().select(id)}
                onSendMessage={handleSendMessage}
                onSetLayerOpacity={handleSetLayerOpacity}
                onSetLayerContextScope={handleSetLayerContextScope}
                onSetLayerVisibility={handleSetLayerVisibility}
                onStopGeneration={stopGeneration}
                onToggleLayerSelection={handleToggleLayerSelection}
                onUpdateConversationMode={handleSetConversationMode}
                onUpdateSettings={handleUpdateSettings}
                onZoomToLayer={handleZoomToLayer}
                conversationMode={activeConversation?.mode || "chat"}
                layerContextById={activeConversation?.layerContextById || {}}
                selectedLayerIds={activeConversation?.selectedLayerIds || []}
                settings={settings}
              />
              <div className="flex items-center gap-2 px-3 py-2 border-t border-border">
                <ServerStatusIndicator compact showUrl={false} />
                <AgentStatusBar />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      </>
  );
}
