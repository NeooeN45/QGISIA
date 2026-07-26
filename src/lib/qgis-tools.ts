import {
  addGeoJsonLayer,
  addCatalogService,
  addRasterFile,
  addRemoteService,
  applyParcelStylePreset,
  calculateMnh,
  calculateRasterFormula,
  createInventoryGrid,
  filterLayer,
  getLayerDiagnostics,
  getServiceCatalog,
  getSupportedRemoteServiceTypes,
  getLayerFields,
  getLayersCatalog,
  getLayerStatistics,
  getLayersList,
  isQgisAvailable,
  mergeRasterBands,
  reprojectLayer,
  runScript,
  segmentRasterWithSAM,
  forecastWeatherWithEarth2,
  exportProjectReport,
  setLayerLabels,
  setLayerOpacity,
  setLayerVisibility,
  splitSelectedLayerByLine,
  zoomToLayer,
} from "./qgis";
import type { RemoteServiceConfig } from "./catalog";
import {
  createBufferAnalysis,
  createCentroids,
  createDissolve,
  createForestInventoryGrid,
  createIntersection,
  exportLayer,
} from "./qgis-advanced-tools";
import {
  loadOfficialSource,
  OVERPASS_ENDPOINTS,
  searchCadastreParcels,
  searchCopernicusProducts,
  searchGeoApiCommunes,
  searchNasaCatalog,
  searchOfficialSources,
  searchOverpassFeatures,
} from "./official-sources";
import {
  fetchHubEauStations,
  type HubEauEndpoint,
  fetchGbifOccurrences,
  fetchDvfTransactions,
} from "./rest-connectors";

export interface OpenAiToolDefinition {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  };
}

const OPENAI_QGIS_TOOLS: OpenAiToolDefinition[] = [
  {
    type: "function",
    function: {
      name: "getSupportedRemoteServiceTypes",
      description:
        "Retourner les types de flux et services distants geres par GeoAI pour QGIS.",
      parameters: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "getServiceCatalog",
      description:
        "Retourner le catalogue integre de services cartographiques distants directement ajoutables dans QGIS.",
      parameters: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "addCatalogService",
      description:
        "Ajouter dans QGIS un service distant du catalogue integre GeoAI.",
      parameters: {
        type: "object",
        properties: {
          itemId: {
            type: "string",
            description: "Identifiant du service dans le catalogue integre.",
          },
        },
        required: ["itemId"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "searchOfficialSources",
      description:
        "Rechercher les sources officielles connectees a GeoAI: cartes.gouv.fr, IGN API Carto, geo.api.gouv.fr, Overpass, NASA, Copernicus.",
      parameters: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description:
              "Mots-cles de recherche, par exemple cadastre, copernicus, overpass, ortho, plan ign.",
          },
        },
        required: ["query"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "loadOfficialSource",
      description:
        "Charger dans QGIS une source officielle deja connue ou retourner sa documentation si c'est une API de recherche.",
      parameters: {
        type: "object",
        properties: {
          sourceId: {
            type: "string",
            description: "Identifiant de la source officielle.",
          },
        },
        required: ["sourceId"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "addRemoteService",
      description:
        "Ajouter un service distant personnalise dans QGIS: WMS, WMTS, WFS, WCS, XYZ, TMS ou ArcGIS REST.",
      parameters: {
        type: "object",
        properties: {
          name: { type: "string", description: "Nom de la couche a creer." },
          serviceType: {
            type: "string",
            description:
              "Type de service parmi WMS, WMTS, WFS, WCS, XYZ, TMS, ArcGISMapServer, ArcGISFeatureServer.",
          },
          url: { type: "string", description: "URL du service." },
          layerName: {
            type: "string",
            description: "Nom de couche, typename ou coverage si necessaire.",
          },
          style: {
            type: "string",
            description: "Style optionnel WMS ou WMTS.",
          },
          format: {
            type: "string",
            description: "Format image ou coverage optionnel.",
          },
          crs: {
            type: "string",
            description: "CRS cible, par exemple EPSG:3857.",
          },
          tileMatrixSet: {
            type: "string",
            description: "Tile matrix set pour WMTS.",
          },
          version: {
            type: "string",
            description: "Version WFS ou WCS si necessaire.",
          },
          zMin: { type: "number", description: "Zoom mini XYZ/TMS." },
          zMax: { type: "number", description: "Zoom maxi XYZ/TMS." },
        },
        required: ["name", "serviceType", "url"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "searchCadastreParcels",
      description:
        "Interroger l'API Carto Cadastre officielle de l'IGN pour retrouver des parcelles et, si demande, les ajouter a QGIS.",
      parameters: {
        type: "object",
        properties: {
          codeInsee: {
            type: "string",
            description: "Code INSEE de la commune sur 5 caracteres.",
          },
          section: {
            type: "string",
            description: "Section cadastrale optionnelle.",
          },
          numero: {
            type: "string",
            description: "Numero de parcelle optionnel, sur 4 caracteres si disponible.",
          },
          codeArr: {
            type: "string",
            description: "Code arrondissement optionnel pour Paris, Lyon, Marseille.",
          },
          comAbs: {
            type: "string",
            description: "Code commune absorbee optionnel.",
          },
          sourceIgn: {
            type: "string",
            description: "PCI ou BDP.",
          },
          limit: {
            type: "number",
            description: "Nombre maximal de parcelles a retourner.",
          },
          addToMap: {
            type: "boolean",
            description: "Si vrai, la couche GeoJSON est ajoutee dans QGIS.",
          },
          layerName: {
            type: "string",
            description: "Nom de couche optionnel dans QGIS.",
          },
        },
        required: ["codeInsee"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "searchGeoApiCommunes",
      description:
        "Interroger geo.api.gouv.fr pour retrouver des communes et, si possible, ajouter leurs contours dans QGIS.",
      parameters: {
        type: "object",
        properties: {
          name: {
            type: "string",
            description: "Nom de commune ou fragment du nom.",
          },
          limit: {
            type: "number",
            description: "Nombre maximal de communes a retourner.",
          },
          addToMap: {
            type: "boolean",
            description: "Si vrai, les contours trouves sont ajoutes a QGIS.",
          },
          layerName: {
            type: "string",
            description: "Nom de couche optionnel dans QGIS.",
          },
        },
        required: ["name"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "searchOverpassFeatures",
      description:
        "Executer une requete Overpass QL sur un endpoint Overpass et, si demande, ajouter le resultat converti en GeoJSON a QGIS.",
      parameters: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description:
              "Requete Overpass QL complete, idealement avec out geom pour les ways et polygones.",
          },
          endpoint: {
            type: "string",
            description: `Endpoint Overpass optionnel. Recommande: ${OVERPASS_ENDPOINTS.join(", ")}`,
          },
          addToMap: {
            type: "boolean",
            description: "Si vrai, le resultat converti est ajoute dans QGIS.",
          },
          layerName: {
            type: "string",
            description: "Nom de couche QGIS optionnel.",
          },
        },
        required: ["query"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "searchCopernicusProducts",
      description:
        "Rechercher des produits dans le catalogue officiel Copernicus Data Space via OData.",
      parameters: {
        type: "object",
        properties: {
          collection: {
            type: "string",
            description: "Collection Copernicus, par exemple SENTINEL-2.",
          },
          nameContains: {
            type: "string",
            description: "Filtre textuel sur le nom du produit.",
          },
          limit: {
            type: "number",
            description: "Nombre maximal de produits a retourner.",
          },
        },
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "searchNasaCatalog",
      description:
        "Rechercher des scenes dans le catalogue STAC officiel NASA/CMR Earthdata.",
      parameters: {
        type: "object",
        properties: {
          collection: {
            type: "string",
            description: "Nom de collection STAC, par exemple sentinel-s2-l2a-cogs.",
          },
          bbox: {
            type: "string",
            description: "BBox optionnelle au format minLon,minLat,maxLon,maxLat.",
          },
          limit: {
            type: "number",
            description: "Nombre maximal de scenes a retourner.",
          },
        },
        required: ["collection"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "addRasterFile",
      description:
        "Charger un raster local, par exemple un GeoTIFF .tif, et l'ajouter a la carte QGIS.",
      parameters: {
        type: "object",
        properties: {
          filePath: {
            type: "string",
            description: "Chemin absolu vers le fichier raster local.",
          },
          layerName: {
            type: "string",
            description: "Nom optionnel de la couche dans QGIS.",
          },
        },
        required: ["filePath"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "addGeoJsonLayer",
      description:
        "Ajouter a QGIS une FeatureCollection GeoJSON deja obtenue depuis une API ou un traitement.",
      parameters: {
        type: "object",
        properties: {
          geojson: {
            type: "string",
            description: "FeatureCollection GeoJSON serialisee.",
          },
          layerName: {
            type: "string",
            description: "Nom de couche optionnel.",
          },
        },
        required: ["geojson"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "calculateRasterFormula",
      description:
        "Executer un calcul raster GDAL sur 1 a 6 rasters deja charges et ajouter le resultat a la carte.",
      parameters: {
        type: "object",
        properties: {
          layerIds: {
            type: "array",
            items: { type: "string" },
            description:
              "Liste ordonnee des rasters. Le premier devient A, le second B, etc.",
          },
          formula: {
            type: "string",
            description:
              "Formule GDAL raster calculator utilisant A, B, C..., par exemple A-B.",
          },
          outputName: {
            type: "string",
            description: "Nom de la couche de sortie.",
          },
          outputPath: {
            type: "string",
            description:
              "Chemin absolu optionnel vers un GeoTIFF de sortie. Laisser vide pour temporaire.",
          },
        },
        required: ["layerIds", "formula", "outputName"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "mergeRasterBands",
      description:
        "Fusionner plusieurs rasters deja charges en un raster multi-bandes, utile pour construire des composites bi-annuels NDVI ou CRswir.",
      parameters: {
        type: "object",
        properties: {
          layerIds: {
            type: "array",
            items: { type: "string" },
            description:
              "Liste ordonnee des rasters a empiler en bandes separees.",
          },
          outputName: {
            type: "string",
            description: "Nom de la couche de sortie multi-bandes.",
          },
          outputPath: {
            type: "string",
            description:
              "Chemin absolu optionnel vers un GeoTIFF de sortie. Laisser vide pour temporaire.",
          },
        },
        required: ["layerIds", "outputName"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "createInventoryGrid",
      description:
        "Creer une grille d'inventaire sur l'emprise d'une couche et generer aussi les centroides des mailles.",
      parameters: {
        type: "object",
        properties: {
          layerId: {
            type: "string",
            description: "Nom ou identifiant de la couche source servant d'emprise.",
          },
          cellWidth: {
            type: "number",
            description: "Largeur d'une maille dans l'unite du CRS de la couche.",
          },
          cellHeight: {
            type: "number",
            description: "Hauteur d'une maille dans l'unite du CRS de la couche.",
          },
          gridName: {
            type: "string",
            description: "Nom de la couche grille de sortie.",
          },
          centroidsName: {
            type: "string",
            description: "Nom de la couche centroides de sortie.",
          },
          clipToSource: {
            type: "boolean",
            description:
              "Si vrai et si la couche source est polygonale, la grille est clippee a la zone d'etude.",
          },
        },
        required: ["layerId", "cellWidth", "cellHeight", "gridName", "centroidsName"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "applyParcelStylePreset",
      description:
        "Appliquer un style cadastral lisible a une couche vectorielle, utile pour les parcelles.",
      parameters: {
        type: "object",
        properties: {
          layerId: {
            type: "string",
            description: "Nom ou identifiant de la couche.",
          },
          presetId: {
            type: "string",
            description: "Preset de style. Valeurs conseillees: cadastre, focus.",
          },
        },
        required: ["layerId"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "setLayerLabels",
      description:
        "Activer ou desactiver de belles etiquettes pour une couche, avec un champ choisi ou deduit automatiquement.",
      parameters: {
        type: "object",
        properties: {
          layerId: {
            type: "string",
            description: "Nom ou identifiant de la couche.",
          },
          fieldName: {
            type: "string",
            description: "Champ d'etiquetage optionnel.",
          },
          enabled: {
            type: "boolean",
            description: "true pour activer, false pour desactiver.",
          },
        },
        required: ["layerId"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "splitSelectedLayerByLine",
      description:
        "Decouper les entites selectionnees d'une couche polygonale avec une ligne WKT et ajouter le resultat dans QGIS.",
      parameters: {
        type: "object",
        properties: {
          layerId: {
            type: "string",
            description: "Nom ou identifiant de la couche polygonale source.",
          },
          lineWkt: {
            type: "string",
            description: "Geometrie WKT de type LineString servant a la decoupe.",
          },
          outputName: {
            type: "string",
            description: "Nom de la couche de sortie.",
          },
        },
        required: ["layerId", "lineWkt", "outputName"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "calculateMnh",
      description:
        "Calculer un MNH raster a partir d'un MNS et d'un MNT, puis ajouter la sortie dans QGIS.",
      parameters: {
        type: "object",
        properties: {
          mnsLayerId: {
            type: "string",
            description: "Nom ou identifiant du MNS raster.",
          },
          mntLayerId: {
            type: "string",
            description: "Nom ou identifiant du MNT raster.",
          },
          outputName: {
            type: "string",
            description: "Nom de la couche MNH de sortie.",
          },
          outputPath: {
            type: "string",
            description:
              "Chemin absolu optionnel vers un GeoTIFF de sortie.",
          },
          clampNegative: {
            type: "boolean",
            description:
              "Si vrai, les valeurs negatives sont ramenees a zero.",
          },
        },
        required: ["mnsLayerId", "mntLayerId", "outputName"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "getLayersList",
      description: "Retourner la liste des couches actuellement chargees dans le projet QGIS.",
      parameters: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "getLayersCatalog",
      description:
        "Retourner le catalogue detaille des couches QGIS avec visibilite, opacite, CRS et nombre d'entites.",
      parameters: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "getLayerFields",
      description: "Retourner les champs attributaires d'une couche vectorielle.",
      parameters: {
        type: "object",
        properties: {
          layerId: {
            type: "string",
            description: "Nom ou identifiant de la couche.",
          },
        },
        required: ["layerId"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "getLayerDiagnostics",
      description:
        "Retourner un diagnostic synthetique d'une couche avec alertes, emprise et qualite des champs.",
      parameters: {
        type: "object",
        properties: {
          layerId: {
            type: "string",
            description: "Nom ou identifiant de la couche.",
          },
        },
        required: ["layerId"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "filterLayer",
      description: "Appliquer un filtre QGIS a une couche.",
      parameters: {
        type: "object",
        properties: {
          layerId: {
            type: "string",
            description: "Nom ou identifiant de la couche.",
          },
          subsetString: {
            type: "string",
            description: "Expression de filtre QGIS ou SQL.",
          },
        },
        required: ["layerId", "subsetString"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "setLayerVisibility",
      description: "Afficher ou masquer une couche dans le panneau des couches QGIS.",
      parameters: {
        type: "object",
        properties: {
          layerId: {
            type: "string",
            description: "Nom ou identifiant de la couche.",
          },
          visible: {
            type: "boolean",
            description: "true pour afficher la couche, false pour la masquer.",
          },
        },
        required: ["layerId", "visible"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "setLayerOpacity",
      description: "Modifier l'opacite d'une couche entre 0 et 1.",
      parameters: {
        type: "object",
        properties: {
          layerId: {
            type: "string",
            description: "Nom ou identifiant de la couche.",
          },
          opacity: {
            type: "number",
            description: "Opacite cible entre 0 et 1.",
          },
        },
        required: ["layerId", "opacity"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "zoomToLayer",
      description: "Cadrer la vue QGIS sur une couche.",
      parameters: {
        type: "object",
        properties: {
          layerId: {
            type: "string",
            description: "Nom ou identifiant de la couche.",
          },
        },
        required: ["layerId"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "getLayerStatistics",
      description: "Calculer des statistiques descriptives sur un champ numerique d'une couche.",
      parameters: {
        type: "object",
        properties: {
          layerId: {
            type: "string",
            description: "Nom ou identifiant de la couche.",
          },
          field: {
            type: "string",
            description: "Nom du champ numerique.",
          },
        },
        required: ["layerId", "field"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "reprojectLayer",
      description: "Reprojeter une couche vectorielle vers un autre CRS et ajouter la sortie au projet.",
      parameters: {
        type: "object",
        properties: {
          layerId: {
            type: "string",
            description: "Nom ou identifiant de la couche source.",
          },
          targetCrs: {
            type: "string",
            description: "Code CRS cible, par exemple EPSG:4326.",
          },
        },
        required: ["layerId", "targetCrs"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "runScript",
      description:
        "Executer un script Python de CALCUL dans un bac a sable isole, apres " +
        "confirmation de l'utilisateur. Le script n'a PAS acces au projet QGIS, " +
        "ni aux fichiers, ni au reseau. Il ne peut donc PAS ajouter, modifier ou " +
        "styliser une couche : pour cela, utiliser les outils bridge dedies.",
      parameters: {
        type: "object",
        properties: {
          script: {
            type: "string",
            description:
              "Code Python de calcul pur (math, statistics, json, datetime, " +
              "collections...). Les imports os/sys/pathlib/requests sont refuses.",
          },
        },
        required: ["script"],
        additionalProperties: false,
      },
    },
  },
  // Outils avancés d'analyse spatiale
  {
    type: "function",
    function: {
      name: "createBufferAnalysis",
      description: "Créer une zone tampon (buffer) autour d'une couche vectorielle avec options avancées: segments, dissolve, styles de jointure.",
      parameters: {
        type: "object",
        properties: {
          layerId: { type: "string", description: "Nom de la couche source" },
          distance: { type: "number", description: "Distance du buffer en unités de la couche" },
          outputName: { type: "string", description: "Nom de la couche de sortie" },
          segments: { type: "number", description: "Nombre de segments pour les arcs (défaut: 5)" },
          dissolve: { type: "boolean", description: "Fusionner les buffers qui se chevauchent" },
          endCapStyle: { type: "string", enum: ["Round", "Flat", "Square"], description: "Style des extrémités" },
          joinStyle: { type: "string", enum: ["Round", "Miter", "Bevel"], description: "Style des jointures" },
        },
        required: ["layerId", "distance", "outputName"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "createIntersection",
      description: "Créer une intersection spatiale entre deux couches vectorielles avec sélection de champs à conserver.",
      parameters: {
        type: "object",
        properties: {
          layerId1: { type: "string", description: "Première couche" },
          layerId2: { type: "string", description: "Deuxième couche" },
          outputName: { type: "string", description: "Nom de sortie" },
          inputFields: { type: "array", items: { type: "string" }, description: "Champs à garder de la couche 1" },
          intersectFields: { type: "array", items: { type: "string" }, description: "Champs à garder de la couche 2" },
          prefix2: { type: "string", description: "Préfixe pour les champs de la couche 2" },
        },
        required: ["layerId1", "layerId2", "outputName"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "createDissolve",
      description: "Dissoudre une couche vectorielle par un champ avec agrégation d'attributs et conservation du type de géométrie.",
      parameters: {
        type: "object",
        properties: {
          layerId: { type: "string", description: "Couche source" },
          outputName: { type: "string", description: "Nom de sortie" },
          field: { type: "string", description: "Champ de dissolve (optionnel, sinon tout fusionne)" },
          keepGeomType: { type: "boolean", description: "Conserver le type de géométrie (défaut: true)" },
        },
        required: ["layerId", "outputName"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "createCentroids",
      description: "Créer les centroïdes d'une couche vectorielle polygonale.",
      parameters: {
        type: "object",
        properties: {
          layerId: { type: "string", description: "Couche source" },
          outputName: { type: "string", description: "Nom de sortie" },
          inside: { type: "boolean", description: "Forcer le centroïde à l'intérieur du polygone" },
          allParts: { type: "boolean", description: "Un centroïde par partie de multipart" },
        },
        required: ["layerId", "outputName"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "exportLayer",
      description: "Exporter une couche vers différents formats avec options de CRS et sélection.",
      parameters: {
        type: "object",
        properties: {
          layerId: { type: "string", description: "Couche à exporter" },
          filePath: { type: "string", description: "Chemin de sortie" },
          format: { type: "string", enum: ["GeoJSON", "Shapefile", "GeoPackage", "KML", "CSV", "DXF"], description: "Format d'export" },
          crs: { type: "string", description: "CRS de sortie, ex: EPSG:4326 (défaut: EPSG:2154)" },
          selectedOnly: { type: "boolean", description: "Exporter sélection uniquement" },
        },
        required: ["layerId", "filePath", "format"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "createForestInventoryGrid",
      description: "Créer une grille d'inventaire forestier systématique avec placettes.",
      parameters: {
        type: "object",
        properties: {
          zoneLayerId: { type: "string", description: "Couche de la zone d'étude" },
          cellSize: { type: "number", description: "Taille des mailles en mètres" },
          outputName: { type: "string", description: "Nom de la grille" },
          buffer: { type: "number", description: "Buffer depuis la limite en mètres" },
          systematic: { type: "boolean", description: "Placement systématique (défaut: true)" },
        },
        required: ["zoneLayerId", "cellSize", "outputName"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "loadHubEauStations",
      description:
        "Charger des stations Hub'Eau (qualité rivières, hydrométrie, piézométrie) en couche QGIS, filtrées par commune, département ou bbox.",
      parameters: {
        type: "object",
        properties: {
          endpoint: {
            type: "string",
            enum: ["qualite_rivieres", "hydrometrie", "piezometrie"],
            description: "Type de stations à récupérer",
          },
          codeCommune: { type: "string", description: "Code INSEE commune (ex: 35238)" },
          codeDepartement: { type: "string", description: "Code département (ex: 35)" },
          bbox: {
            type: "array",
            items: { type: "number" },
            minItems: 4,
            maxItems: 4,
            description: "Bbox WGS84 [minLon, minLat, maxLon, maxLat]",
          },
          size: { type: "number", description: "Limite résultats (défaut 200, max 20000)" },
          layerName: { type: "string", description: "Nom de couche QGIS" },
        },
        required: ["endpoint"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "loadGbifOccurrences",
      description:
        "Charger des occurrences d'espèces GBIF (biodiversité mondiale) géoréférencées en couche QGIS.",
      parameters: {
        type: "object",
        properties: {
          scientificName: { type: "string", description: "Nom scientifique (ex: Quercus robur)" },
          taxonKey: { type: "number", description: "Clé taxon GBIF" },
          country: { type: "string", description: "Code pays ISO (ex: FR)" },
          bbox: {
            type: "array",
            items: { type: "number" },
            minItems: 4,
            maxItems: 4,
            description: "Bbox WGS84 [minLon, minLat, maxLon, maxLat]",
          },
          yearStart: { type: "number" },
          yearEnd: { type: "number" },
          limit: { type: "number", description: "Max résultats (défaut 100, max 300)" },
          layerName: { type: "string" },
        },
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "exportProjectReport",
      description:
        "Exporter un rapport SIG du projet QGIS courant en PDF ou DOCX, incluant snapshot carte, tableau des couches (nom, CRS, n features) et sections personnalisees (texte, listes, tableaux). Utilise reportlab (PDF) ou python-docx.",
      parameters: {
        type: "object",
        properties: {
          title: { type: "string", description: "Titre du rapport (obligatoire)" },
          outputPath: { type: "string", description: "Chemin de sortie (.pdf ou .docx)" },
          format: {
            type: "string",
            enum: ["pdf", "docx"],
            description: "Format (defaut pdf)",
          },
          author: { type: "string" },
          subtitle: { type: "string" },
          includeLayers: { type: "boolean", description: "Inclure tableau couches (defaut true)" },
          includeMap: { type: "boolean", description: "Inclure snapshot carte (defaut true)" },
          sections: {
            type: "array",
            description: "Sections personnalisees",
            items: {
              type: "object",
              properties: {
                title: { type: "string" },
                body: { type: "string" },
                bullets: { type: "array", items: { type: "string" } },
                tableHeaders: { type: "array", items: { type: "string" } },
                tableRows: {
                  type: "array",
                  items: { type: "array", items: { type: "string" } },
                },
              },
              required: ["title"],
            },
          },
        },
        required: ["title", "outputPath"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "forecastWeatherWithEarth2",
      description:
        "Lancer une prevision meteo globale via NVIDIA Earth-2 Studio (FourCastNet, Pangu, AIFS, GraphCast). Genere des GeoTIFF par variable (temperature, vent, pression, precipitations) chargees comme couches raster QGIS. Necessite earth2studio + torch cote backend.",
      parameters: {
        type: "object",
        properties: {
          outputDir: {
            type: "string",
            description: "Dossier de sortie pour les GeoTIFF",
          },
          model: {
            type: "string",
            enum: ["fcn", "pangu", "aifs", "graphcast"],
            description: "Modele IA : fcn (defaut, rapide) | pangu | aifs | graphcast",
          },
          initTime: {
            type: "string",
            description: "Heure init ISO 8601 UTC (ex: 2026-04-26T00:00:00Z, defaut: dernier pivot 6h)",
          },
          leadHours: {
            type: "number",
            description: "Horizon de prevision en heures (1-240, defaut 24)",
          },
          variables: {
            type: "array",
            items: { type: "string" },
            description: "Variables a prevoir (t2m, msl, u10, v10, tp, tcwv, z500, t850...)",
          },
          layerPrefix: {
            type: "string",
            description: "Prefixe des couches QGIS (defaut Earth2)",
          },
        },
        required: ["outputDir"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "segmentRasterWithSAM",
      description:
        "Segmenter un raster (image satellite, orthophoto) avec Segment Anything (SAM). Génère des polygones GeoJSON soit automatiquement (tous masques), soit guidés par prompt texte (ex: 'trees', 'buildings', 'water'). Nécessite samgeo + torch côté backend.",
      parameters: {
        type: "object",
        properties: {
          rasterPath: {
            type: "string",
            description: "Chemin local du raster GeoTIFF géoréférencé",
          },
          outputGeojson: {
            type: "string",
            description: "Chemin de sortie pour le GeoJSON polygons",
          },
          mode: {
            type: "string",
            enum: ["automatic", "text_prompt"],
            description: "automatic = tous masques, text_prompt = guidé par prompt",
          },
          textPrompt: {
            type: "string",
            description: "Prompt texte si mode=text_prompt (ex: 'trees', 'buildings')",
          },
          model: {
            type: "string",
            enum: ["vit_h", "vit_l", "vit_b"],
            description: "vit_h = qualité (lent), vit_b = rapide",
          },
          minAreaPx: {
            type: "number",
            description: "Filtre polygones plus petits que N pixels (défaut 200)",
          },
          layerName: { type: "string", description: "Nom de couche QGIS" },
        },
        required: ["rasterPath", "outputGeojson"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "loadDvfTransactions",
      description:
        "Charger les transactions immobilières DVF (data.gouv.fr) géoréférencées sur une commune ou code postal en couche QGIS.",
      parameters: {
        type: "object",
        properties: {
          codeCommune: { type: "string", description: "Code INSEE commune" },
          codePostal: { type: "string", description: "Code postal" },
          section: { type: "string", description: "Section cadastrale" },
          natureMutation: {
            type: "string",
            description: "Nature mutation (Vente, VEFA, Echange...)",
          },
          typeLocal: {
            type: "string",
            description: "Maison | Appartement | Local | Dépendance",
          },
          limit: { type: "number", description: "Max transactions (défaut 500)" },
          layerName: { type: "string" },
        },
        additionalProperties: false,
      },
    },
  },
];

function requireString(
  args: Record<string, unknown>,
  key: string,
  label: string,
): string {
  const value = args[key];
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${label} est requis.`);
  }

  return value.trim();
}

function requireBoolean(
  args: Record<string, unknown>,
  key: string,
  label: string,
): boolean {
  const value = args[key];
  if (typeof value !== "boolean") {
    throw new Error(`${label} est requis.`);
  }

  return value;
}

function requireNumber(
  args: Record<string, unknown>,
  key: string,
  label: string,
): number {
  const value = args[key];
  if (typeof value !== "number" || Number.isNaN(value)) {
    throw new Error(`${label} est requis.`);
  }

  return value;
}

function requireStringArray(
  args: Record<string, unknown>,
  key: string,
  label: string,
): string[] {
  const value = args[key];
  if (!Array.isArray(value)) {
    throw new Error(`${label} est requis.`);
  }

  const normalized = value.filter(
    (entry): entry is string => typeof entry === "string" && entry.trim().length > 0,
  );

  if (normalized.length === 0) {
    throw new Error(`${label} est requis.`);
  }

  return normalized.map((entry) => entry.trim());
}

function ensureQgisAvailable(): void {
  if (!isQgisAvailable()) {
    throw new Error("Le pont QGIS n'est pas disponible dans cette session.");
  }
}

export function getOpenAiQgisToolDefinitions(): OpenAiToolDefinition[] {
  return OPENAI_QGIS_TOOLS;
}

export async function executeQgisToolCall(
  name: string,
  args: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  ensureQgisAvailable();

  switch (name) {
    case "getSupportedRemoteServiceTypes": {
      const types = getSupportedRemoteServiceTypes();
      return {
        ok: true,
        count: types.length,
        types,
      };
    }
    case "getServiceCatalog": {
      const catalog = getServiceCatalog();
      return {
        ok: true,
        count: catalog.length,
        catalog,
      };
    }
    case "searchOfficialSources": {
      const query = requireString(args, "query", "La recherche de source");
      const sources = searchOfficialSources(query);
      return {
        ok: true,
        count: sources.length,
        sources,
      };
    }
    case "loadOfficialSource": {
      const sourceId = requireString(args, "sourceId", "L'identifiant de source");
      const result = await loadOfficialSource(sourceId);
      return {
        ok: result.ok,
        ...result,
      };
    }
    case "addCatalogService": {
      const itemId = requireString(args, "itemId", "L'identifiant de service");
      const status = await addCatalogService(itemId);
      if (!status) {
        throw new Error("Impossible d'ajouter ce service du catalogue.");
      }

      return {
        ok: true,
        itemId,
        status,
      };
    }
    case "addRemoteService": {
      const nameValue = requireString(args, "name", "Le nom de couche");
      const serviceType = requireString(args, "serviceType", "Le type de service");
      const url = requireString(args, "url", "L'URL du service");
      const status = await addRemoteService({
        name: nameValue,
        serviceType: serviceType as RemoteServiceConfig["serviceType"],
        url,
        layerName:
          typeof args.layerName === "string" ? args.layerName.trim() : undefined,
        style: typeof args.style === "string" ? args.style.trim() : undefined,
        format: typeof args.format === "string" ? args.format.trim() : undefined,
        crs: typeof args.crs === "string" ? args.crs.trim() : undefined,
        tileMatrixSet:
          typeof args.tileMatrixSet === "string"
            ? args.tileMatrixSet.trim()
            : undefined,
        version:
          typeof args.version === "string" ? args.version.trim() : undefined,
        zMin: typeof args.zMin === "number" ? args.zMin : undefined,
        zMax: typeof args.zMax === "number" ? args.zMax : undefined,
      });
      if (!status) {
        throw new Error("Le service distant n'a pas pu être ajouté dans QGIS.");
      }

      return {
        ok: true,
        status,
      };
    }
    case "searchCadastreParcels": {
      const codeInsee = requireString(args, "codeInsee", "Le code INSEE");
      const result = await searchCadastreParcels({
        codeInsee,
        section:
          typeof args.section === "string" ? args.section.trim() : undefined,
        numero:
          typeof args.numero === "string" ? args.numero.trim() : undefined,
        codeArr:
          typeof args.codeArr === "string" ? args.codeArr.trim() : undefined,
        comAbs:
          typeof args.comAbs === "string" ? args.comAbs.trim() : undefined,
        sourceIgn:
          args.sourceIgn === "BDP" ? "BDP" : "PCI",
        limit: typeof args.limit === "number" ? args.limit : undefined,
        addToMap:
          typeof args.addToMap === "boolean" ? args.addToMap : false,
        layerName:
          typeof args.layerName === "string" ? args.layerName.trim() : undefined,
      });
      return {
        ok: true,
        ...result,
      };
    }
    case "searchGeoApiCommunes": {
      const nameValue = requireString(args, "name", "Le nom de commune");
      const result = await searchGeoApiCommunes({
        name: nameValue,
        limit: typeof args.limit === "number" ? args.limit : undefined,
        addToMap:
          typeof args.addToMap === "boolean" ? args.addToMap : false,
        layerName:
          typeof args.layerName === "string" ? args.layerName.trim() : undefined,
      });
      return {
        ok: true,
        ...result,
      };
    }
    case "searchOverpassFeatures": {
      const query = requireString(args, "query", "La requete Overpass");
      const result = await searchOverpassFeatures({
        query,
        endpoint:
          typeof args.endpoint === "string" ? args.endpoint.trim() : undefined,
        addToMap:
          typeof args.addToMap === "boolean" ? args.addToMap : false,
        layerName:
          typeof args.layerName === "string" ? args.layerName.trim() : undefined,
      });
      return {
        ok: true,
        ...result,
      };
    }
    case "searchCopernicusProducts": {
      const result = await searchCopernicusProducts({
        collection:
          typeof args.collection === "string" ? args.collection.trim() : undefined,
        nameContains:
          typeof args.nameContains === "string"
            ? args.nameContains.trim()
            : undefined,
        limit: typeof args.limit === "number" ? args.limit : undefined,
      });
      return {
        ok: true,
        ...result,
      };
    }
    case "searchNasaCatalog": {
      const collection = requireString(args, "collection", "La collection NASA");
      const result = await searchNasaCatalog({
        collection,
        bbox: typeof args.bbox === "string" ? args.bbox.trim() : undefined,
        limit: typeof args.limit === "number" ? args.limit : undefined,
      });
      return {
        ok: true,
        ...result,
      };
    }
    case "addRasterFile": {
      const filePath = requireString(args, "filePath", "Le chemin raster");
      const layerName =
        typeof args.layerName === "string" ? args.layerName.trim() : "";
      const status = await addRasterFile(filePath, layerName);
      if (!status) {
        throw new Error("Impossible de charger ce raster dans QGIS.");
      }

      return {
        ok: true,
        filePath,
        layerName,
        status,
      };
    }
    case "addGeoJsonLayer": {
      const geojson = requireString(args, "geojson", "Le GeoJSON");
      const layerName =
        typeof args.layerName === "string" ? args.layerName.trim() : "";
      const status = await addGeoJsonLayer(geojson, layerName);
      if (!status) {
        throw new Error("Impossible d'ajouter ce GeoJSON dans QGIS.");
      }
      return {
        ok: true,
        layerName,
        status,
      };
    }
    case "calculateRasterFormula": {
      const layerIds = requireStringArray(args, "layerIds", "La liste de rasters");
      const formula = requireString(args, "formula", "La formule raster");
      const outputName = requireString(args, "outputName", "Le nom de sortie");
      const outputPath =
        typeof args.outputPath === "string" ? args.outputPath.trim() : "";
      const result = await calculateRasterFormula(
        layerIds,
        formula,
        outputName,
        outputPath,
      );
      if (!result) {
        throw new Error("Le calcul raster a échoué.");
      }

      return {
        ok: true,
        ...result,
      };
    }
    case "mergeRasterBands": {
      const layerIds = requireStringArray(args, "layerIds", "La liste de rasters");
      const outputName = requireString(args, "outputName", "Le nom de sortie");
      const outputPath =
        typeof args.outputPath === "string" ? args.outputPath.trim() : "";
      const result = await mergeRasterBands(layerIds, outputName, outputPath);
      if (!result) {
        throw new Error("La fusion multi-bandes a échoué.");
      }

      return {
        ok: true,
        ...result,
      };
    }
    case "createInventoryGrid": {
      const layerId = requireString(args, "layerId", "La couche source");
      const cellWidth = requireNumber(args, "cellWidth", "La largeur de maille");
      const cellHeight = requireNumber(args, "cellHeight", "La hauteur de maille");
      const gridName = requireString(args, "gridName", "Le nom de grille");
      const centroidsName = requireString(
        args,
        "centroidsName",
        "Le nom de la couche centroides",
      );
      const clipToSource =
        typeof args.clipToSource === "boolean" ? args.clipToSource : true;
      const result = await createInventoryGrid(
        layerId,
        cellWidth,
        cellHeight,
        gridName,
        centroidsName,
        clipToSource,
      );
      if (!result) {
        throw new Error("La grille d'inventaire a échoué.");
      }

      return {
        ok: true,
        ...result,
      };
    }
    case "applyParcelStylePreset": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const presetId =
        typeof args.presetId === "string" ? args.presetId.trim() : "cadastre";
      const status = await applyParcelStylePreset(layerId, presetId);
      if (!status) {
        throw new Error("Impossible d'appliquer le preset de style.");
      }
      return {
        ok: true,
        layerId,
        presetId,
        status,
      };
    }
    case "setLayerLabels": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const fieldName =
        typeof args.fieldName === "string" ? args.fieldName.trim() : "";
      const enabled =
        typeof args.enabled === "boolean" ? args.enabled : true;
      const status = await setLayerLabels(layerId, fieldName, enabled);
      if (!status) {
        throw new Error("Impossible de modifier les etiquettes.");
      }
      return {
        ok: true,
        layerId,
        fieldName,
        enabled,
        status,
      };
    }
    case "splitSelectedLayerByLine": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const lineWkt = requireString(args, "lineWkt", "La ligne WKT");
      const outputName = requireString(args, "outputName", "Le nom de sortie");
      const status = await splitSelectedLayerByLine(layerId, lineWkt, outputName);
      if (!status) {
        throw new Error("Impossible de decouper la couche selectionnee.");
      }
      return {
        ok: true,
        layerId,
        outputName,
        status,
      };
    }
    case "calculateMnh": {
      const mnsLayerId = requireString(args, "mnsLayerId", "Le MNS");
      const mntLayerId = requireString(args, "mntLayerId", "Le MNT");
      const outputName = requireString(args, "outputName", "Le nom de sortie");
      const outputPath =
        typeof args.outputPath === "string" ? args.outputPath.trim() : "";
      const clampNegative =
        typeof args.clampNegative === "boolean" ? args.clampNegative : true;
      const result = await calculateMnh(
        mnsLayerId,
        mntLayerId,
        outputName,
        outputPath,
        clampNegative,
      );
      if (!result) {
        throw new Error("Le calcul MNH a échoué.");
      }

      return {
        ok: true,
        ...result,
      };
    }
    case "getLayersList": {
      const layers = await getLayersList();
      return {
        ok: true,
        count: layers.length,
        layers,
      };
    }
    case "getLayersCatalog": {
      const layers = await getLayersCatalog();
      return {
        ok: true,
        count: layers.length,
        layers,
      };
    }
    case "getLayerFields": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const fields = await getLayerFields(layerId);
      return {
        ok: true,
        layerId,
        count: fields.length,
        fields,
      };
    }
    case "getLayerDiagnostics": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const diagnostics = await getLayerDiagnostics(layerId);
      if (!diagnostics) {
        throw new Error("Impossible de diagnostiquer cette couche.");
      }

      return {
        ok: true,
        ...diagnostics,
      };
    }
    case "filterLayer": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const subsetString = requireString(
        args,
        "subsetString",
        "L'expression de filtre",
      );
      const status = await filterLayer(layerId, subsetString);

      return {
        ok: true,
        layerId,
        subsetString,
        status: status || "Filtre transmis a QGIS.",
      };
    }
    case "setLayerVisibility": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const visible = requireBoolean(args, "visible", "Le booleen de visibilite");
      const status = await setLayerVisibility(layerId, visible);

      return {
        ok: true,
        layerId,
        visible,
        status: status || "Visibilite transmise a QGIS.",
      };
    }
    case "setLayerOpacity": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const opacity = requireNumber(args, "opacity", "L'opacite");
      const status = await setLayerOpacity(layerId, opacity);

      return {
        ok: true,
        layerId,
        opacity,
        status: status || "Opacite transmise a QGIS.",
      };
    }
    case "zoomToLayer": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const status = await zoomToLayer(layerId);

      return {
        ok: true,
        layerId,
        status: status || "Zoom transmis a QGIS.",
      };
    }
    case "getLayerStatistics": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const field = requireString(args, "field", "Le champ");
      const stats = await getLayerStatistics(layerId, field);
      if (!stats) {
        throw new Error("Impossible de calculer les statistiques demandees.");
      }

      return {
        ok: true,
        layerId,
        field,
        ...stats,
      };
    }
    case "reprojectLayer": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const targetCrs = requireString(args, "targetCrs", "Le CRS cible");
      const outputLayerName = await reprojectLayer(layerId, targetCrs);
      if (!outputLayerName) {
        throw new Error("La reprojection a echoue cote QGIS.");
      }

      return {
        ok: true,
        layerId,
        targetCrs,
        outputLayerName,
      };
    }
    case "runScript": {
      const script = requireString(args, "script", "Le script Python");
      const status = await runScript(script);

      return {
        ok: true,
        status: status || "Script transmis a QGIS.",
      };
    }
    case "createBufferAnalysis": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const distance = requireNumber(args, "distance", "La distance");
      const outputName = requireString(args, "outputName", "Le nom de sortie");
      const validEndCapStyles = ["Round", "Flat", "Square"] as const;
      const validJoinStyles = ["Round", "Miter", "Bevel"] as const;
      const endCapStyle = validEndCapStyles.includes(args.endCapStyle as typeof validEndCapStyles[number]) 
        ? args.endCapStyle as typeof validEndCapStyles[number] 
        : "Round";
      const joinStyle = validJoinStyles.includes(args.joinStyle as typeof validJoinStyles[number]) 
        ? args.joinStyle as typeof validJoinStyles[number] 
        : "Round";
      const result = await createBufferAnalysis(layerId, distance, outputName, {
        segments: typeof args.segments === "number" ? args.segments : 5,
        dissolve: typeof args.dissolve === "boolean" ? args.dissolve : false,
        endCapStyle,
        joinStyle,
      });
      return { ...result } as Record<string, unknown>;
    }
    case "createIntersection": {
      const layerId1 = requireString(args, "layerId1", "La première couche");
      const layerId2 = requireString(args, "layerId2", "La deuxième couche");
      const outputName = requireString(args, "outputName", "Le nom de sortie");
      const result = await createIntersection(layerId1, layerId2, outputName, {
        inputFields: Array.isArray(args.inputFields) ? args.inputFields : undefined,
        intersectFields: Array.isArray(args.intersectFields) ? args.intersectFields : undefined,
        prefix2: typeof args.prefix2 === "string" ? args.prefix2 : undefined,
      });
      return { ...result } as Record<string, unknown>;
    }
    case "createDissolve": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const outputName = requireString(args, "outputName", "Le nom de sortie");
      const result = await createDissolve(layerId, outputName, {
        field: typeof args.field === "string" ? args.field : undefined,
        keepGeomType: typeof args.keepGeomType === "boolean" ? args.keepGeomType : true,
      });
      return { ...result } as Record<string, unknown>;
    }
    case "createCentroids": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const outputName = requireString(args, "outputName", "Le nom de sortie");
      const result = await createCentroids(layerId, outputName, {
        inside: typeof args.inside === "boolean" ? args.inside : false,
        allParts: typeof args.allParts === "boolean" ? args.allParts : false,
      });
      return { ...result } as Record<string, unknown>;
    }
    case "exportLayer": {
      const layerId = requireString(args, "layerId", "Le nom de couche");
      const filePath = requireString(args, "filePath", "Le chemin de fichier");
      const format = requireString(args, "format", "Le format") as Parameters<typeof exportLayer>[2];
      const result = await exportLayer(layerId, filePath, format, {
        crs: typeof args.crs === "string" ? args.crs : undefined,
        selectedOnly: typeof args.selectedOnly === "boolean" ? args.selectedOnly : false,
      });
      return { ...result } as Record<string, unknown>;
    }
    case "createForestInventoryGrid": {
      const zoneLayerId = requireString(args, "zoneLayerId", "La zone d'étude");
      const cellSize = requireNumber(args, "cellSize", "La taille des mailles");
      const outputName = requireString(args, "outputName", "Le nom de sortie");
      const result = await createForestInventoryGrid(zoneLayerId, cellSize, outputName, {
        buffer: typeof args.buffer === "number" ? args.buffer : 0,
        systematic: typeof args.systematic === "boolean" ? args.systematic : true,
      });
      return { ...result } as Record<string, unknown>;
    }
    case "loadHubEauStations": {
      const endpoint = requireString(args, "endpoint", "L'endpoint Hub'Eau") as HubEauEndpoint;
      const result = await fetchHubEauStations({
        endpoint,
        codeCommune: typeof args.codeCommune === "string" ? args.codeCommune : undefined,
        codeDepartement: typeof args.codeDepartement === "string" ? args.codeDepartement : undefined,
        bbox: Array.isArray(args.bbox) && args.bbox.length === 4
          ? (args.bbox as [number, number, number, number])
          : undefined,
        size: typeof args.size === "number" ? args.size : undefined,
      });
      const layerName =
        typeof args.layerName === "string" && args.layerName.trim()
          ? args.layerName.trim()
          : `HubEau_${endpoint}`;
      const status = await addGeoJsonLayer(JSON.stringify(result.geojson), layerName);
      return {
        ok: result.ok,
        count: result.count,
        message: result.message,
        layer: status ?? layerName,
      };
    }
    case "loadGbifOccurrences": {
      const result = await fetchGbifOccurrences({
        scientificName: typeof args.scientificName === "string" ? args.scientificName : undefined,
        taxonKey: typeof args.taxonKey === "number" ? args.taxonKey : undefined,
        country: typeof args.country === "string" ? args.country : undefined,
        bbox: Array.isArray(args.bbox) && args.bbox.length === 4
          ? (args.bbox as [number, number, number, number])
          : undefined,
        yearStart: typeof args.yearStart === "number" ? args.yearStart : undefined,
        yearEnd: typeof args.yearEnd === "number" ? args.yearEnd : undefined,
        limit: typeof args.limit === "number" ? args.limit : undefined,
      });
      const layerName =
        typeof args.layerName === "string" && args.layerName.trim()
          ? args.layerName.trim()
          : `GBIF_${typeof args.scientificName === "string" ? args.scientificName.replace(/\s+/g, "_") : "occurrences"}`;
      const status = await addGeoJsonLayer(JSON.stringify(result.geojson), layerName);
      return {
        ok: result.ok,
        count: result.count,
        message: result.message,
        layer: status ?? layerName,
      };
    }
    case "exportProjectReport": {
      const title = requireString(args, "title", "Le titre du rapport");
      const outputPath = requireString(args, "outputPath", "Le chemin de sortie");
      const format =
        args.format === "pdf" || args.format === "docx" ? args.format : undefined;
      const sections = Array.isArray(args.sections)
        ? (args.sections as unknown[]).map((s) => {
            const obj = (s ?? {}) as Record<string, unknown>;
            return {
              title: typeof obj.title === "string" ? obj.title : "Section",
              body: typeof obj.body === "string" ? obj.body : undefined,
              bullets: Array.isArray(obj.bullets)
                ? (obj.bullets as unknown[]).map((b) => String(b))
                : undefined,
              tableHeaders: Array.isArray(obj.tableHeaders)
                ? (obj.tableHeaders as unknown[]).map((h) => String(h))
                : undefined,
              tableRows: Array.isArray(obj.tableRows)
                ? (obj.tableRows as unknown[]).map((row) =>
                    Array.isArray(row) ? row.map((c) => String(c)) : [],
                  )
                : undefined,
            };
          })
        : undefined;
      const status = await exportProjectReport({
        title,
        outputPath,
        format,
        author: typeof args.author === "string" ? args.author : undefined,
        subtitle: typeof args.subtitle === "string" ? args.subtitle : undefined,
        includeLayers:
          typeof args.includeLayers === "boolean" ? args.includeLayers : undefined,
        includeMap:
          typeof args.includeMap === "boolean" ? args.includeMap : undefined,
        sections,
      });
      if (!status) {
        throw new Error(
          "Export rapport indisponible (reportlab/python-docx absent ou erreur backend).",
        );
      }
      return { ok: true, tool: "exportProjectReport", status };
    }
    case "forecastWeatherWithEarth2": {
      const outputDir = requireString(args, "outputDir", "Le dossier de sortie");
      const model =
        args.model === "fcn" ||
        args.model === "pangu" ||
        args.model === "aifs" ||
        args.model === "graphcast"
          ? args.model
          : undefined;
      const variables =
        Array.isArray(args.variables) && args.variables.every((v) => typeof v === "string")
          ? (args.variables as string[])
          : undefined;
      const status = await forecastWeatherWithEarth2({
        outputDir,
        model,
        initTime: typeof args.initTime === "string" ? args.initTime : undefined,
        leadHours: typeof args.leadHours === "number" ? args.leadHours : undefined,
        variables,
        layerPrefix: typeof args.layerPrefix === "string" ? args.layerPrefix : undefined,
      });
      if (!status) {
        throw new Error(
          "Earth-2 indisponible (earth2studio/torch absent ou erreur backend).",
        );
      }
      return {
        ok: true,
        tool: "forecastWeatherWithEarth2",
        status,
      };
    }
    case "segmentRasterWithSAM": {
      const rasterPath = requireString(args, "rasterPath", "Le chemin raster");
      const outputGeojson = requireString(args, "outputGeojson", "Le chemin de sortie GeoJSON");
      const mode = (typeof args.mode === "string" ? args.mode : "automatic") as
        | "automatic"
        | "text_prompt";
      if (mode === "text_prompt" && (!args.textPrompt || typeof args.textPrompt !== "string")) {
        throw new Error("mode='text_prompt' exige textPrompt non vide.");
      }
      const status = await segmentRasterWithSAM({
        rasterPath,
        outputGeojson,
        mode,
        textPrompt: typeof args.textPrompt === "string" ? args.textPrompt : undefined,
        model:
          args.model === "vit_h" || args.model === "vit_l" || args.model === "vit_b"
            ? args.model
            : undefined,
        minAreaPx: typeof args.minAreaPx === "number" ? args.minAreaPx : undefined,
        layerName: typeof args.layerName === "string" ? args.layerName : undefined,
      });
      if (!status) {
        throw new Error(
          "Segmentation SAM indisponible (samgeo/torch absent côté QGIS ou erreur backend).",
        );
      }
      return {
        ok: true,
        tool: "segmentRasterWithSAM",
        status,
      };
    }
    case "loadDvfTransactions": {
      const result = await fetchDvfTransactions({
        codeCommune: typeof args.codeCommune === "string" ? args.codeCommune : undefined,
        codePostal: typeof args.codePostal === "string" ? args.codePostal : undefined,
        section: typeof args.section === "string" ? args.section : undefined,
        natureMutation: typeof args.natureMutation === "string" ? args.natureMutation : undefined,
        typeLocal: typeof args.typeLocal === "string" ? args.typeLocal : undefined,
        limit: typeof args.limit === "number" ? args.limit : undefined,
      });
      const layerName =
        typeof args.layerName === "string" && args.layerName.trim()
          ? args.layerName.trim()
          : `DVF_${args.codeCommune ?? args.codePostal ?? "transactions"}`;
      const status = await addGeoJsonLayer(JSON.stringify(result.geojson), layerName);
      return {
        ok: result.ok,
        count: result.count,
        message: result.message,
        layer: status ?? layerName,
      };
    }
    default:
      throw new Error(`Outil QGIS inconnu: ${name}`);
  }
}
