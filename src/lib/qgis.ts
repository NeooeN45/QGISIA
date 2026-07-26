import {
  CARTOGRAPHIC_CATALOG,
  getCatalogItemById,
  RemoteServiceConfig,
  SUPPORTED_REMOTE_SERVICE_TYPES,
} from "./catalog";

const QGIS_RESULT_TIMEOUT_MS = 5000;
const QGIS_SCRIPT_TIMEOUT_MS = 120_000;

/** Timeout pour les routes de script/processing lourdes (runScript, render…) */
const HTTP_SCRIPT_TIMEOUT_MS = 60_000;
/** Timeout pour les routes de lecture rapide (listLayers, getProjectInfo…) */
const HTTP_FAST_TIMEOUT_MS = 10_000;

type QgisCallback<T> = (value: T) => void;

export interface LayerStatistics {
  count: number;
  sum: number;
  mean: number;
  min: number;
  max: number;
  range: number;
  sampleStandardDeviation: number;
  populationStandardDeviation: number;
}

export interface LayerSummary {
  id: string;
  name: string;
  type: string;
  geometryType: string;
  crs: string;
  featureCount: number | null;
  selectedFeatureCount: number;
  visible: boolean;
  opacity: number;
  subsetString: string;
  provider: string;
  editable: boolean;
}

export interface LayerExtent {
  xmin: number;
  ymin: number;
  xmax: number;
  ymax: number;
}

export interface LayerFieldDiagnostic {
  name: string;
  type: string;
  nullCount: number;
  fillRate: number;
}

export interface LayerDiagnostics {
  layerId: string;
  layerName: string;
  layerType: string;
  geometryType: string;
  crs: string;
  featureCount: number | null;
  selectedFeatureCount: number;
  sampledFeatureCount: number;
  isSampled: boolean;
  invalidGeometryCount: number;
  emptyGeometryCount: number;
  subsetString: string;
  extent: LayerExtent | null;
  warnings: string[];
  fieldDiagnostics: LayerFieldDiagnostic[];
}

export interface RasterCalculationResult {
  outputLayerName: string;
  outputPath: string;
  formula: string;
}

export interface RasterBandMergeResult {
  outputLayerName: string;
  outputPath: string;
  inputLayers: string[];
  separateBands: boolean;
}

export interface InventoryGridResult {
  gridLayerName: string;
  centroidLayerName: string;
  sourceLayerName: string;
  cellWidth: number;
  cellHeight: number;
  clipped: boolean;
}

export interface ScriptExecutionResult {
  ok: boolean;
  message: string;
  traceback?: string;
}

interface RawQgisBridge {
  openLayers?: () => void;
  openSettings?: () => void;
  pickFile?: (
    fileFilter: string,
    title: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  getLayersCatalog?: (callback?: QgisCallback<string>) => string | void;
  getLayerDiagnostics?: (
    layerId: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  runScript?: (script: string, callback?: QgisCallback<string>) => string | void;
  // `runScriptDirect` a été retiré du bridge : c'était le seul chemin
  // d'exécution sans confirmation utilisateur.
  runScriptDetailed?: (
    script: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  getLayerFields?: (
    layerId: string,
    callback?: QgisCallback<string[]>,
  ) => string[] | void;
  filterLayer?: (
    layerId: string,
    subsetString: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  getLayersList?: (callback?: QgisCallback<string[]>) => string[] | void;
  setLayerVisibility?: (
    layerId: string,
    visible: boolean,
    callback?: QgisCallback<string>,
  ) => string | void;
  setLayerOpacity?: (
    layerId: string,
    opacity: number,
    callback?: QgisCallback<string>,
  ) => string | void;
  zoomToLayer?: (
    layerId: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  getLayerStatistics?: (
    layerId: string,
    field: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  reprojectLayer?: (
    layerId: string,
    targetCrs: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  addServiceLayer?: (
    configJson: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  addRasterFile?: (
    filePath: string,
    layerName: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  addGeoJsonLayer?: (
    geojson: string,
    layerName: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  segmentRasterWithSAM?: (
    optionsJson: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  forecastWeatherWithEarth2?: (
    optionsJson: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  exportProjectReport?: (
    optionsJson: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  calculateRasterFormula?: (
    layerIdsJson: string,
    formula: string,
    outputName: string,
    outputPath: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  mergeRasterBands?: (
    layerIdsJson: string,
    outputName: string,
    outputPath: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  createInventoryGrid?: (
    layerRef: string,
    cellWidth: number,
    cellHeight: number,
    gridName: string,
    centroidsName: string,
    clipToSource: boolean,
    callback?: QgisCallback<string>,
  ) => string | void;
  calculateMnh?: (
    mnsLayerId: string,
    mntLayerId: string,
    outputName: string,
    outputPath: string,
    clampNegative: boolean,
    callback?: QgisCallback<string>,
  ) => string | void;
  applyParcelStylePreset?: (
    layerId: string,
    presetId: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  setLayerLabels?: (
    layerId: string,
    fieldName: string,
    enabled: boolean,
    callback?: QgisCallback<string>,
  ) => string | void;
  splitSelectedLayerByLine?: (
    layerId: string,
    lineWkt: string,
    outputName: string,
    callback?: QgisCallback<string>,
  ) => string | void;
  /** Capture la carte courante et retourne une data-URL base64 PNG */
  captureMapSnapshot?: (callback?: QgisCallback<string>) => string | void;
  /** Status des dépendances NVIDIA (torch CUDA + earth2studio) */
  getNvidiaDepsStatus?: (callback?: QgisCallback<string>) => string | void;
  /** Installation des dépendances NVIDIA */
  installNvidiaDeps?: (
    force: boolean,
    callback?: QgisCallback<string>,
  ) => string | void;
}

declare global {
  interface Window {
    qgis?: RawQgisBridge;
  }
}

let httpBridge: RawQgisBridge | null = null;

/**
 * Nom de la balise <meta> par laquelle le plugin transmet le jeton du bridge.
 * Doit rester aligné sur `bridge_http.TOKEN_META_NAME` côté Python.
 */
const BRIDGE_TOKEN_META = "qgisia-bridge-token";

/** En-tête portant le jeton. Doit rester aligné sur `bridge_http.TOKEN_HEADER`. */
const BRIDGE_TOKEN_HEADER = "X-QGISIA-Token";

/**
 * Lit le jeton injecté dans la page servie depuis 127.0.0.1.
 *
 * Le jeton ne transite jamais par l'URL : il n'apparaît donc ni dans
 * l'historique, ni dans un en-tête `Referer`. Une page tierce ne peut pas le
 * lire (politique d'origine), et un rebinding DNS est arrêté côté serveur par
 * le contrôle de l'en-tête `Host`.
 */
function getBridgeToken(): string {
  try {
    const meta = document.querySelector<HTMLMetaElement>(
      `meta[name="${BRIDGE_TOKEN_META}"]`,
    );
    return meta?.content ?? "";
  } catch {
    return "";
  }
}

function isHttpBridgeEnabled(): boolean {
  try {
    return new URLSearchParams(window.location.search).get("bridge") === "http";
  } catch {
    return false;
  }
}

async function readHttpBridgeResult<T>(
  input: RequestInfo | URL,
  init?: RequestInit,
  timeoutMs: number = HTTP_FAST_TIMEOUT_MS,
): Promise<T | undefined> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(input, {
      ...init,
      headers: {
        ...(init?.headers as Record<string, string> | undefined),
        [BRIDGE_TOKEN_HEADER]: getBridgeToken(),
      },
      signal: controller.signal,
    });
    if (!response.ok) {
      return undefined;
    }

    const payload = (await response.json()) as { ok?: boolean; result?: T };
    return payload.ok ? payload.result : undefined;
  } catch {
    return undefined;
  } finally {
    clearTimeout(timeoutId);
  }
}

function getHttpBridge(): RawQgisBridge | undefined {
  if (!isHttpBridgeEnabled()) {
    return undefined;
  }

  if (httpBridge) {
    return httpBridge;
  }

  const baseUrl = window.location.origin;
  const makeUrl = (path: string, params?: Record<string, string>) => {
    const url = new URL(path, baseUrl);
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        url.searchParams.set(key, value);
      });
    }
    return url;
  };

  const postJson = <T>(
    path: string,
    body?: Record<string, unknown>,
    timeoutMs: number = HTTP_FAST_TIMEOUT_MS,
  ) =>
    readHttpBridgeResult<T>(
      makeUrl(path),
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body ?? {}),
      },
      timeoutMs,
    );

  /** POST avec timeout long pour les routes de script/processing */
  const postJsonSlow = <T>(path: string, body?: Record<string, unknown>) =>
    postJson<T>(path, body, HTTP_SCRIPT_TIMEOUT_MS);

  httpBridge = {
    openLayers: () => {
      void postJson("/api/qgis/openLayers");
    },
    openSettings: () => {
      void postJson("/api/qgis/openSettings");
    },
    pickFile: (fileFilter, title, callback) => {
      void postJson<string>("/api/qgis/pickFile", {
        fileFilter,
        title,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    getLayersCatalog: (callback) => {
      void readHttpBridgeResult<string>(makeUrl("/api/qgis/getLayersCatalog")).then(
        (result) => {
          if (callback) {
            callback(typeof result === "string" ? result : "[]");
          }
        },
      );
    },
    getLayerDiagnostics: (layerId, callback) => {
      void readHttpBridgeResult<string>(
        makeUrl("/api/qgis/getLayerDiagnostics", { layerId }),
      ).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    runScript: (script, callback) => {
      void postJsonSlow<string>("/api/qgis/runScript", { script }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    // runScriptDirect a été supprimé du bridge : il exécutait sans
    // confirmation. La confirmation est désormais inconditionnelle.
    runScriptDetailed: (script, callback) => {
      // `requireConfirmation` ne fait plus partie du contrat réseau : le
      // serveur répond 400 si le champ est présent.
      void postJsonSlow<string>("/api/qgis/runScriptDetailed", {
        script,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    getLayerFields: (layerId, callback) => {
      void readHttpBridgeResult<string[]>(
        makeUrl("/api/qgis/getLayerFields", { layerId }),
      ).then((result) => {
        if (callback) {
          callback(Array.isArray(result) ? result : []);
        }
      });
    },
    filterLayer: (layerId, subsetString, callback) => {
      void postJson<string>("/api/qgis/filterLayer", {
        layerId,
        subsetString,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    getLayersList: (callback) => {
      void readHttpBridgeResult<string[]>(makeUrl("/api/qgis/getLayersList")).then(
        (result) => {
          if (callback) {
            callback(Array.isArray(result) ? result : []);
          }
        },
      );
    },
    setLayerVisibility: (layerId, visible, callback) => {
      void postJson<string>("/api/qgis/setLayerVisibility", {
        layerId,
        visible,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    setLayerOpacity: (layerId, opacity, callback) => {
      void postJson<string>("/api/qgis/setLayerOpacity", {
        layerId,
        opacity,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    zoomToLayer: (layerId, callback) => {
      void postJson<string>("/api/qgis/zoomToLayer", {
        layerId,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    getLayerStatistics: (layerId, field, callback) => {
      void readHttpBridgeResult<string>(
        makeUrl("/api/qgis/getLayerStatistics", { layerId, field }),
      ).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    reprojectLayer: (layerId, targetCrs, callback) => {
      void postJsonSlow<string>("/api/qgis/reprojectLayer", {
        layerId,
        targetCrs,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    addServiceLayer: (configJson, callback) => {
      void postJson<string>("/api/qgis/addServiceLayer", {
        config: configJson,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    addRasterFile: (filePath, layerName, callback) => {
      void postJson<string>("/api/qgis/addRasterFile", {
        filePath,
        layerName,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    segmentRasterWithSAM: (optionsJson, callback) => {
      void postJsonSlow<string>("/api/qgis/segmentRasterWithSAM", {
        options: optionsJson,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    forecastWeatherWithEarth2: (optionsJson, callback) => {
      void postJsonSlow<string>("/api/qgis/forecastWeatherWithEarth2", {
        options: optionsJson,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    exportProjectReport: (optionsJson, callback) => {
      void postJsonSlow<string>("/api/qgis/exportProjectReport", {
        options: optionsJson,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    addGeoJsonLayer: (geojson, layerName, callback) => {
      void postJson<string>("/api/qgis/addGeoJsonLayer", {
        geojson,
        layerName,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    calculateRasterFormula: (
      layerIdsJson,
      formula,
      outputName,
      outputPath,
      callback,
    ) => {
      void postJsonSlow<string>("/api/qgis/calculateRasterFormula", {
        layerIds: layerIdsJson,
        formula,
        outputName,
        outputPath,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    mergeRasterBands: (layerIdsJson, outputName, outputPath, callback) => {
      void postJsonSlow<string>("/api/qgis/mergeRasterBands", {
        layerIds: layerIdsJson,
        outputName,
        outputPath,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    createInventoryGrid: (
      layerRef,
      cellWidth,
      cellHeight,
      gridName,
      centroidsName,
      clipToSource,
      callback,
    ) => {
      void postJsonSlow<string>("/api/qgis/createInventoryGrid", {
        layerRef,
        layerId: layerRef,
        cellWidth,
        cellHeight,
        gridName,
        centroidsName,
        clipToSource,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    calculateMnh: (
      mnsLayerId,
      mntLayerId,
      outputName,
      outputPath,
      clampNegative,
      callback,
    ) => {
      void postJsonSlow<string>("/api/qgis/calculateMnh", {
        mnsLayerId,
        mntLayerId,
        outputName,
        outputPath,
        clampNegative,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    applyParcelStylePreset: (layerId, presetId, callback) => {
      void postJson<string>("/api/qgis/applyParcelStylePreset", {
        layerId,
        presetId,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    setLayerLabels: (layerId, fieldName, enabled, callback) => {
      void postJson<string>("/api/qgis/setLayerLabels", {
        layerId,
        fieldName,
        enabled,
      }).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    splitSelectedLayerByLine: (layerId, lineWkt, outputName, callback) => {
      void postJsonSlow<string>("/api/qgis/splitSelectedLayerByLine", {
        layerId,
        lineWkt,
        outputName,
      }).then((result) => {
        if (callback) {
          callback(result ?? "");
        }
      });
    },
    captureMapSnapshot: (callback) => {
      void readHttpBridgeResult<string>(
        makeUrl("/api/qgis/captureMapSnapshot"),
        undefined,
        HTTP_SCRIPT_TIMEOUT_MS,
      ).then((result) => {
        if (callback) {
          callback(typeof result === "string" ? result : "");
        }
      });
    },
    getNvidiaDepsStatus: (callback) => {
      void postJson<string>("/api/qgis/getNvidiaDepsStatus", {}).then((result) => {
        if (callback) {
          callback(result ?? "{}");
        }
      });
    },
    installNvidiaDeps: (force, callback) => {
      void postJsonSlow<string>("/api/qgis/installNvidiaDeps", { force }).then((result) => {
        if (callback) {
          callback(result ?? "{}");
        }
      });
    },
  };

  return httpBridge;
}

export function getBridge(): RawQgisBridge | undefined {
  return window.qgis ?? getHttpBridge();
}

export function isQgisAvailable(): boolean {
  return Boolean(getBridge());
}

function normalizeStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter((item): item is string => typeof item === "string");
}

function normalizeLayerSummary(value: unknown): LayerSummary | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const candidate = value as Record<string, unknown>;
  const id = typeof candidate.id === "string" ? candidate.id : "";
  const name = typeof candidate.name === "string" ? candidate.name : "";

  if (!id || !name) {
    return null;
  }

  return {
    id,
    name,
    type: typeof candidate.type === "string" ? candidate.type : "",
    geometryType:
      typeof candidate.geometryType === "string" ? candidate.geometryType : "",
    crs: typeof candidate.crs === "string" ? candidate.crs : "",
    featureCount:
      typeof candidate.featureCount === "number" ? candidate.featureCount : null,
    selectedFeatureCount:
      typeof candidate.selectedFeatureCount === "number"
        ? candidate.selectedFeatureCount
        : 0,
    visible: Boolean(candidate.visible),
    opacity:
      typeof candidate.opacity === "number"
        ? Math.min(1, Math.max(0, candidate.opacity))
        : 1,
    subsetString:
      typeof candidate.subsetString === "string" ? candidate.subsetString : "",
    provider: typeof candidate.provider === "string" ? candidate.provider : "",
    editable: Boolean(candidate.editable),
  };
}

function normalizeLayerCatalog(value: unknown): LayerSummary[] {
  if (typeof value === "string") {
    try {
      return normalizeLayerCatalog(JSON.parse(value));
    } catch {
      return [];
    }
  }

  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((entry) => normalizeLayerSummary(entry))
    .filter((entry): entry is LayerSummary => entry !== null);
}

function normalizeLayerDiagnostics(value: unknown): LayerDiagnostics | null {
  if (typeof value === "string") {
    try {
      return normalizeLayerDiagnostics(JSON.parse(value));
    } catch {
      return null;
    }
  }

  if (!value || typeof value !== "object") {
    return null;
  }

  const candidate = value as Record<string, unknown>;
  const layerId = typeof candidate.layerId === "string" ? candidate.layerId : "";
  const layerName = typeof candidate.layerName === "string" ? candidate.layerName : "";

  if (!layerId || !layerName) {
    return null;
  }

  const rawExtent =
    candidate.extent && typeof candidate.extent === "object"
      ? (candidate.extent as Record<string, unknown>)
      : null;

  return {
    layerId,
    layerName,
    layerType: typeof candidate.layerType === "string" ? candidate.layerType : "",
    geometryType:
      typeof candidate.geometryType === "string" ? candidate.geometryType : "",
    crs: typeof candidate.crs === "string" ? candidate.crs : "",
    featureCount:
      typeof candidate.featureCount === "number" ? candidate.featureCount : null,
    selectedFeatureCount:
      typeof candidate.selectedFeatureCount === "number"
        ? candidate.selectedFeatureCount
        : 0,
    sampledFeatureCount:
      typeof candidate.sampledFeatureCount === "number"
        ? candidate.sampledFeatureCount
        : 0,
    isSampled: Boolean(candidate.isSampled),
    invalidGeometryCount:
      typeof candidate.invalidGeometryCount === "number"
        ? candidate.invalidGeometryCount
        : 0,
    emptyGeometryCount:
      typeof candidate.emptyGeometryCount === "number"
        ? candidate.emptyGeometryCount
        : 0,
    subsetString:
      typeof candidate.subsetString === "string" ? candidate.subsetString : "",
    extent:
      rawExtent &&
      typeof rawExtent.xmin === "number" &&
      typeof rawExtent.ymin === "number" &&
      typeof rawExtent.xmax === "number" &&
      typeof rawExtent.ymax === "number"
        ? {
            xmin: rawExtent.xmin,
            ymin: rawExtent.ymin,
            xmax: rawExtent.xmax,
            ymax: rawExtent.ymax,
          }
        : null,
    warnings: Array.isArray(candidate.warnings)
      ? candidate.warnings.filter(
          (warning): warning is string => typeof warning === "string",
        )
      : [],
    fieldDiagnostics: Array.isArray(candidate.fieldDiagnostics)
      ? candidate.fieldDiagnostics
          .map((entry) => {
            if (!entry || typeof entry !== "object") {
              return null;
            }

            const field = entry as Record<string, unknown>;
            if (typeof field.name !== "string") {
              return null;
            }

            return {
              name: field.name,
              type: typeof field.type === "string" ? field.type : "",
              nullCount:
                typeof field.nullCount === "number" ? field.nullCount : 0,
              fillRate:
                typeof field.fillRate === "number"
                  ? Math.min(1, Math.max(0, field.fillRate))
                  : 0,
            };
          })
          .filter((entry): entry is LayerFieldDiagnostic => entry !== null)
      : [],
  };
}

function normalizeRasterCalculationResult(
  value: unknown,
): RasterCalculationResult | null {
  if (typeof value === "string") {
    try {
      return normalizeRasterCalculationResult(JSON.parse(value));
    } catch {
      return null;
    }
  }

  if (!value || typeof value !== "object") {
    return null;
  }

  const candidate = value as Record<string, unknown>;
  const outputLayerName =
    typeof candidate.outputLayerName === "string" ? candidate.outputLayerName : "";
  const outputPath =
    typeof candidate.outputPath === "string" ? candidate.outputPath : "";
  const formula = typeof candidate.formula === "string" ? candidate.formula : "";

  if (!outputLayerName) {
    return null;
  }

  return {
    outputLayerName,
    outputPath,
    formula,
  };
}

function normalizeRasterBandMergeResult(
  value: unknown,
): RasterBandMergeResult | null {
  if (typeof value === "string") {
    try {
      return normalizeRasterBandMergeResult(JSON.parse(value));
    } catch {
      return null;
    }
  }

  if (!value || typeof value !== "object") {
    return null;
  }

  const candidate = value as Record<string, unknown>;
  const outputLayerName =
    typeof candidate.outputLayerName === "string" ? candidate.outputLayerName : "";
  const outputPath =
    typeof candidate.outputPath === "string" ? candidate.outputPath : "";
  const inputLayers = Array.isArray(candidate.inputLayers)
    ? candidate.inputLayers.filter(
        (entry): entry is string => typeof entry === "string" && entry.length > 0,
      )
    : [];
  const separateBands = Boolean(candidate.separateBands);

  if (!outputLayerName) {
    return null;
  }

  return {
    outputLayerName,
    outputPath,
    inputLayers,
    separateBands,
  };
}

function normalizeInventoryGridResult(
  value: unknown,
): InventoryGridResult | null {
  if (typeof value === "string") {
    try {
      return normalizeInventoryGridResult(JSON.parse(value));
    } catch {
      return null;
    }
  }

  if (!value || typeof value !== "object") {
    return null;
  }

  const candidate = value as Record<string, unknown>;
  const gridLayerName =
    typeof candidate.gridLayerName === "string" ? candidate.gridLayerName : "";
  const centroidLayerName =
    typeof candidate.centroidLayerName === "string"
      ? candidate.centroidLayerName
      : "";
  const sourceLayerName =
    typeof candidate.sourceLayerName === "string"
      ? candidate.sourceLayerName
      : "";
  const cellWidth =
    typeof candidate.cellWidth === "number" ? candidate.cellWidth : 0;
  const cellHeight =
    typeof candidate.cellHeight === "number" ? candidate.cellHeight : 0;
  const clipped = Boolean(candidate.clipped);

  if (!gridLayerName || !centroidLayerName || !sourceLayerName) {
    return null;
  }

  return {
    gridLayerName,
    centroidLayerName,
    sourceLayerName,
    cellWidth,
    cellHeight,
    clipped,
  };
}

export async function callQgisWithResult<T>(
  invoker: (callback: QgisCallback<T>) => T | void,
  fallback: T,
  timeoutMs: number = QGIS_RESULT_TIMEOUT_MS,
): Promise<T> {
  return new Promise((resolve) => {
    let settled = false;

    const timeout = window.setTimeout(() => {
      if (!settled) {
        settled = true;
        resolve(fallback);
      }
    }, timeoutMs);

    const callback = (value: T) => {
      if (!settled) {
        settled = true;
        window.clearTimeout(timeout);
        resolve(value);
      }
    };

    try {
      const result = invoker(callback);
      if (result !== undefined && !settled) {
        settled = true;
        window.clearTimeout(timeout);
        resolve(result as T);
      }
    } catch {
      if (!settled) {
        settled = true;
        window.clearTimeout(timeout);
        resolve(fallback);
      }
    }
  });
}

function callQgisCommand(command: () => unknown): boolean {
  try {
    command();
    return true;
  } catch {
    return false;
  }
}

export interface SystemSpecs {
  source: "python_psutil" | "browser_fallback";
  ram_total_gb: number;
  ram_available_gb: number;
  cpu_logical: number;
  cpu_physical: number;
  processor: string;
  platform: string;
  gpu_name: string;
  gpu_vram_gb: number;
  gpu_has_cuda: boolean;
}

export async function getSystemSpecs(): Promise<SystemSpecs | null> {
  // Pas de guard isHttpBridgeEnabled() : on tente toujours le fetch direct.
  // Si QGIS sert la page, le serveur HTTP local répondra quel que soit le flag bridge=http.
  // Si non servi par QGIS, le fetch échoue silencieusement et le fallback navigateur s'applique.
  try {
    const baseUrl = window.location.origin;
    const url = new URL("/api/qgis/getSystemSpecs", baseUrl);
    const response = await fetch(url, { signal: AbortSignal.timeout(4000) });
    if (!response.ok) return null;
    const data = (await response.json()) as SystemSpecs & { ok?: boolean };
    if (!data.ok) return null;
    return data;
  } catch {
    return null;
  }
}

export async function getLayersList(): Promise<string[]> {
  const bridge = getBridge();
  if (!bridge) {
    return [];
  }

  if (!bridge.getLayersList) {
    if (bridge.getLayersCatalog) {
      return (await getLayersCatalog()).map((layer) => layer.name);
    }

    return [];
  }

  const result = await callQgisWithResult<string[]>(
    (callback) => bridge.getLayersList?.(callback),
    [],
  );

  return normalizeStringArray(result);
}

export async function getLayersCatalog(): Promise<LayerSummary[]> {
  const bridge = getBridge();
  if (bridge?.getLayersCatalog) {
    const result = await callQgisWithResult<string>(
      (callback) => bridge.getLayersCatalog?.(callback),
      "[]",
    );

    return normalizeLayerCatalog(result);
  }

  const layerNames = await getLayersList();
  return layerNames.map((name) => ({
    id: name,
    name,
    type: "",
    geometryType: "",
    crs: "",
    featureCount: null,
    selectedFeatureCount: 0,
    visible: true,
    opacity: 1,
    subsetString: "",
    provider: "",
    editable: false,
  }));
}

export async function getLayerFields(layerId: string): Promise<string[]> {
  const bridge = getBridge();
  if (!bridge?.getLayerFields) {
    return [];
  }

  const result = await callQgisWithResult<string[]>(
    (callback) => bridge.getLayerFields?.(layerId, callback),
    [],
  );

  return normalizeStringArray(result);
}

export async function getLayerDiagnostics(
  layerId: string,
): Promise<LayerDiagnostics | null> {
  const bridge = getBridge();
  if (!bridge?.getLayerDiagnostics) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridge.getLayerDiagnostics?.(layerId, callback),
    "",
  );

  if (!result) {
    return null;
  }

  return normalizeLayerDiagnostics(result);
}

export function openQgisLayersPanel(): boolean {
  const bridge = getBridge();
  if (!bridge?.openLayers) {
    return false;
  }

  return callQgisCommand(() => bridge.openLayers?.());
}

export function openQgisSettings(): boolean {
  const bridge = getBridge();
  if (!bridge?.openSettings) {
    return false;
  }

  return callQgisCommand(() => bridge.openSettings?.());
}

export async function pickQgisFile(
  fileFilter = "",
  title = "Choisir un fichier",
): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.pickFile) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridge.pickFile?.(fileFilter, title, callback),
    "",
  );

  return typeof result === "string" && result.length > 0 ? result : null;
}

/**
 * Exécute un script dans le bac à sable du plugin.
 *
 * L'exécution est TOUJOURS soumise à confirmation de l'utilisateur : il
 * n'existe plus d'option pour la désactiver. Le script tourne hors du
 * processus QGIS, sans accès au projet, aux fichiers ni au réseau — pour
 * modifier le projet, utiliser l'API de commandes (`/api/qgis/runCommands`).
 */
export async function runScript(script: string): Promise<string | null> {
  const bridgeMethod = getBridge()?.runScript;

  if (!bridgeMethod) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridgeMethod(script, callback),
    "",
    QGIS_SCRIPT_TIMEOUT_MS,
  );

  return typeof result === "string" && result.length > 0 ? result : null;
}

export async function runScriptDetailed(
  script: string,
): Promise<ScriptExecutionResult | null> {
  const bridge = getBridge();

  if (bridge?.runScriptDetailed) {
    const result = await callQgisWithResult<string>(
      (callback) => bridge.runScriptDetailed?.(script, callback),
      "",
      QGIS_SCRIPT_TIMEOUT_MS,
    );

    if (!result) {
      return null;
    }

    try {
      return JSON.parse(result) as ScriptExecutionResult;
    } catch {
      return {
        ok: !/^Erreur\b/i.test(result),
        message: result,
      };
    }
  }

  const legacyResult = await runScript(script);
  if (!legacyResult) {
    return null;
  }

  return {
    ok: !/^Erreur\b/i.test(legacyResult),
    message: legacyResult,
  };
}

export async function filterLayer(
  layerId: string,
  subsetString: string,
): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.filterLayer) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridge.filterLayer?.(layerId, subsetString, callback),
    "",
  );

  return typeof result === "string" && result.length > 0 ? result : null;
}

export async function setLayerVisibility(
  layerId: string,
  visible: boolean,
): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.setLayerVisibility) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridge.setLayerVisibility?.(layerId, visible, callback),
    "",
  );

  return typeof result === "string" && result.length > 0 ? result : null;
}

export async function setLayerOpacity(
  layerId: string,
  opacity: number,
): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.setLayerOpacity) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridge.setLayerOpacity?.(layerId, opacity, callback),
    "",
  );

  return typeof result === "string" && result.length > 0 ? result : null;
}

export async function zoomToLayer(layerId: string): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.zoomToLayer) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridge.zoomToLayer?.(layerId, callback),
    "",
  );

  return typeof result === "string" && result.length > 0 ? result : null;
}

export async function getLayerStatistics(
  layerId: string,
  field: string,
): Promise<LayerStatistics | null> {
  const bridge = getBridge();
  if (!bridge?.getLayerStatistics) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridge.getLayerStatistics?.(layerId, field, callback),
    "",
  );

  if (!result) {
    return null;
  }

  try {
    return JSON.parse(result) as LayerStatistics;
  } catch {
    return null;
  }
}

export async function reprojectLayer(
  layerId: string,
  targetCrs: string,
): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.reprojectLayer) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridge.reprojectLayer?.(layerId, targetCrs, callback),
    "",
  );

  return typeof result === "string" && result.length > 0 ? result : null;
}

export function getSupportedRemoteServiceTypes() {
  return SUPPORTED_REMOTE_SERVICE_TYPES;
}

export function getServiceCatalog() {
  return CARTOGRAPHIC_CATALOG;
}

export async function addRemoteService(
  config: RemoteServiceConfig,
): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.addServiceLayer) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) =>
      bridge.addServiceLayer?.(JSON.stringify(config), callback),
    "",
  );

  return typeof result === "string" && result.length > 0 ? result : null;
}

export async function addCatalogService(itemId: string): Promise<string | null> {
  const item = getCatalogItemById(itemId);
  if (!item) {
    return null;
  }

  return addRemoteService(item);
}

export async function addRasterFile(
  filePath: string,
  layerName = "",
): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.addRasterFile) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridge.addRasterFile?.(filePath, layerName, callback),
    "",
  );

  return typeof result === "string" && result.length > 0 ? result : null;
}

export async function addGeoJsonLayer(
  geojson: string,
  layerName = "",
): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.addGeoJsonLayer) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridge.addGeoJsonLayer?.(geojson, layerName, callback),
    "",
  );

  return typeof result === "string" && result.length > 0 ? result : null;
}

export interface SamSegmentationOptions {
  /** Chemin local du raster (GeoTIFF georef) */
  rasterPath: string;
  /** Chemin où sauvegarder le GeoJSON résultat */
  outputGeojson: string;
  /** "automatic" (sans prompt) ou "text_prompt" (LangSAM) */
  mode?: "automatic" | "text_prompt";
  /** Texte de prompt si mode="text_prompt" (ex: "trees", "buildings") */
  textPrompt?: string;
  /** Modèle SAM : vit_h (qualité) | vit_l | vit_b (rapide) */
  model?: "vit_h" | "vit_l" | "vit_b";
  /** Filtre polygones < N pixels (défaut 200) */
  minAreaPx?: number;
  /** Nom de la couche QGIS résultante */
  layerName?: string;
}

export async function segmentRasterWithSAM(
  options: SamSegmentationOptions,
): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.segmentRasterWithSAM) {
    return null;
  }
  const result = await callQgisWithResult<string>(
    (callback) =>
      bridge.segmentRasterWithSAM?.(JSON.stringify(options), callback),
    "",
    QGIS_SCRIPT_TIMEOUT_MS, // segmentation is slow → script timeout
  );
  return typeof result === "string" && result.length > 0 ? result : null;
}

export interface Earth2ForecastOptions {
  /** Dossier de sortie pour les GeoTIFF */
  outputDir: string;
  /** Modèle : fcn (défaut) | pangu | aifs | graphcast */
  model?: "fcn" | "pangu" | "aifs" | "graphcast";
  /** Heure d'init ISO 8601 UTC (défaut : dernier pivot 6h) */
  initTime?: string;
  /** Horizon de prévision en heures (1-240, défaut 24) */
  leadHours?: number;
  /** Variables : t2m, msl, u10, v10, tp, etc. */
  variables?: string[];
  /** Préfixe des couches QGIS (défaut "Earth2") */
  layerPrefix?: string;
}

export interface ReportSectionInput {
  title: string;
  body?: string;
  bullets?: string[];
  tableHeaders?: string[];
  tableRows?: string[][];
}

export interface ReportExportOptions {
  /** Titre du rapport (obligatoire) */
  title: string;
  /** Chemin de sortie (.pdf ou .docx) */
  outputPath: string;
  /** Format : pdf (defaut) ou docx */
  format?: "pdf" | "docx";
  /** Auteur (optionnel) */
  author?: string;
  /** Sous-titre */
  subtitle?: string;
  /** Inclure le tableau des couches du projet (defaut true) */
  includeLayers?: boolean;
  /** Inclure un snapshot de la carte (defaut true) */
  includeMap?: boolean;
  /** Sections personnalisees */
  sections?: ReportSectionInput[];
}

export async function exportProjectReport(
  options: ReportExportOptions,
): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.exportProjectReport) {
    return null;
  }
  const result = await callQgisWithResult<string>(
    (callback) =>
      bridge.exportProjectReport?.(JSON.stringify(options), callback),
    "",
    QGIS_SCRIPT_TIMEOUT_MS,
  );
  return typeof result === "string" && result.length > 0 ? result : null;
}

export async function forecastWeatherWithEarth2(
  options: Earth2ForecastOptions,
): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.forecastWeatherWithEarth2) {
    return null;
  }
  const result = await callQgisWithResult<string>(
    (callback) =>
      bridge.forecastWeatherWithEarth2?.(JSON.stringify(options), callback),
    "",
    QGIS_SCRIPT_TIMEOUT_MS, // forecast is slow (model loading + inference)
  );
  return typeof result === "string" && result.length > 0 ? result : null;
}

export async function calculateRasterFormula(
  layerIds: string[],
  formula: string,
  outputName: string,
  outputPath = "",
): Promise<RasterCalculationResult | null> {
  const bridge = getBridge();
  if (!bridge?.calculateRasterFormula) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) =>
      bridge.calculateRasterFormula?.(
        JSON.stringify(layerIds),
        formula,
        outputName,
        outputPath,
        callback,
      ),
    "",
  );

  return normalizeRasterCalculationResult(result);
}

export async function mergeRasterBands(
  layerIds: string[],
  outputName: string,
  outputPath = "",
): Promise<RasterBandMergeResult | null> {
  const bridge = getBridge();
  if (!bridge?.mergeRasterBands) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) =>
      bridge.mergeRasterBands?.(
        JSON.stringify(layerIds),
        outputName,
        outputPath,
        callback,
      ),
    "",
  );

  return normalizeRasterBandMergeResult(result);
}

export async function createInventoryGrid(
  layerRef: string,
  cellWidth: number,
  cellHeight: number,
  gridName: string,
  centroidsName: string,
  clipToSource = true,
): Promise<InventoryGridResult | null> {
  const bridge = getBridge();
  if (!bridge?.createInventoryGrid) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) =>
      bridge.createInventoryGrid?.(
        layerRef,
        cellWidth,
        cellHeight,
        gridName,
        centroidsName,
        clipToSource,
        callback,
      ),
    "",
  );

  return normalizeInventoryGridResult(result);
}

export async function calculateMnh(
  mnsLayerId: string,
  mntLayerId: string,
  outputName: string,
  outputPath = "",
  clampNegative = true,
): Promise<RasterCalculationResult | null> {
  const bridge = getBridge();
  if (!bridge?.calculateMnh) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) =>
      bridge.calculateMnh?.(
        mnsLayerId,
        mntLayerId,
        outputName,
        outputPath,
        clampNegative,
        callback,
      ),
    "",
  );

  return normalizeRasterCalculationResult(result);
}

export async function applyParcelStylePreset(
  layerId: string,
  presetId = "cadastre",
): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.applyParcelStylePreset) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridge.applyParcelStylePreset?.(layerId, presetId, callback),
    "",
  );

  return typeof result === "string" && result.length > 0 ? result : null;
}

export async function setLayerLabels(
  layerId: string,
  fieldName = "",
  enabled = true,
): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.setLayerLabels) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridge.setLayerLabels?.(layerId, fieldName, enabled, callback),
    "",
  );

  return typeof result === "string" && result.length > 0 ? result : null;
}

export async function setProjectCrs(crsCode: string): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.runScript) {
    return null;
  }

  const script = [
    "from qgis.core import QgsCoordinateReferenceSystem, QgsProject",
    `crs = QgsCoordinateReferenceSystem("${crsCode}")`,
    "if crs.isValid():",
    "    QgsProject.instance().setCrs(crs)",
    `    print(f"Projection du projet changée en ${crsCode}")`,
    "else:",
    `    print(f"CRS invalide : ${crsCode}")`,
  ].join("\n");

  const result = await callQgisWithResult<string>(
    (callback) => bridge.runScript?.(script, callback),
    "",
  );

  return typeof result === "string" && result.length > 0 ? result : null;
}

export async function splitSelectedLayerByLine(
  layerId: string,
  lineWkt: string,
  outputName: string,
): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.splitSelectedLayerByLine) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) =>
      bridge.splitSelectedLayerByLine?.(layerId, lineWkt, outputName, callback),
    "",
  );

  return typeof result === "string" && result.length > 0 ? result : null;
}

export interface NvidiaDepsStatus {
  available: boolean;
  reason?: string;
  torch?: {
    version: string;
    cuda_available: boolean;
    cuda_version?: string;
  };
}

export async function getNvidiaDepsStatus(): Promise<NvidiaDepsStatus | null> {
  const bridge = getBridge();
  if (!bridge?.getNvidiaDepsStatus) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridge.getNvidiaDepsStatus?.(callback),
    "{}",
  );

  if (typeof result !== "string" || result.length === 0) {
    return null;
  }

  try {
    return JSON.parse(result) as NvidiaDepsStatus;
  } catch {
    return null;
  }
}

export async function installNvidiaDeps(force = false): Promise<{
  success: boolean;
  error?: string;
  already_installed?: boolean;
} | null> {
  const bridge = getBridge();
  if (!bridge?.installNvidiaDeps) {
    return null;
  }

  const result = await callQgisWithResult<string>(
    (callback) => bridge.installNvidiaDeps?.(force, callback),
    "{}",
  );

  if (typeof result !== "string" || result.length === 0) {
    return null;
  }

  try {
    return JSON.parse(result) as {
      success: boolean;
      error?: string;
      already_installed?: boolean;
    };
  } catch {
    return null;
  }
}

const CAPTURE_TIMEOUT_MS = 8000;

export async function captureMapSnapshot(): Promise<string | null> {
  const bridge = getBridge();
  if (!bridge?.captureMapSnapshot) {
    return null;
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), CAPTURE_TIMEOUT_MS);

  try {
    const result = await callQgisWithResult<string>(
      (callback) => bridge.captureMapSnapshot?.(callback),
      "",
    );
    clearTimeout(timeoutId);

    if (typeof result !== "string" || result.length === 0) {
      return null;
    }

    return result;
  } catch {
    clearTimeout(timeoutId);
    return null;
  }
}
