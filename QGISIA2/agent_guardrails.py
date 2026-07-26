# -*- coding: utf-8 -*-
"""
QGISIA+ — Guardrails de l'agent (Sprint 2).

Inspiré de NVIDIA NeMo Guardrails mais Python pur, sans dépendance externe.
Compatible QGIS 3.9+.

Rôles :
1. INPUT RAILS  — Valider/bloquer les requêtes dangereuses avant LLM
2. OUTPUT RAILS — Valider/intercepter les réponses avant exécution
3. ACTION RAILS — Confirmer les actions destructives/irréversibles

Niveaux de risque :
    SAFE        → exécution directe
    WARN        → log + warning UI
    CONFIRM     → popup de confirmation obligatoire
    BLOCK       → blocage total + message clair
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


class RiskLevel(str, Enum):
    SAFE = "safe"
    WARN = "warn"
    CONFIRM = "confirm"
    BLOCK = "block"


@dataclass
class GuardrailResult:
    passed: bool
    risk_level: RiskLevel
    rule_triggered: Optional[str]
    message: str
    suggested_alternative: Optional[str] = None
    requires_confirmation: bool = False
    modified_content: Optional[str] = None


# ── Règles INPUT (requêtes utilisateur) ──────────────────────────────────────

_INPUT_RULES: List[Dict[str, Any]] = [
    {
        "id": "no_system_access",
        "level": RiskLevel.BLOCK,
        "pattern": r"(supprime|efface|formate|rm\s+-rf|del\s+/|shutdown|reboot|taskkill)",
        "message": "QGISIA+ ne peut pas exécuter des commandes système dangereuses.",
        "alternative": "Précise une opération SIG spécifique sur tes couches.",
    },
    {
        "id": "no_sql_injection",
        "level": RiskLevel.BLOCK,
        "pattern": r"(drop\s+table|truncate\s+table|delete\s+from\s+\w+\s+where\s+1=1|exec\s+xp_)",
        "message": "Requête SQL potentiellement destructive détectée.",
        "alternative": "Formule ta requête de sélection spatiale en langage naturel.",
    },
    {
        "id": "sensitive_data_warning",
        "level": RiskLevel.WARN,
        "pattern": r"(propriétaire|nom\s+du\s+propriétaire|adresse\s+personnelle|données\s+privées)",
        "message": "Attention: les données de propriété foncière sont publiques via cadastre.gouv.fr uniquement.",
        "alternative": None,
    },
    {
        "id": "hallucination_risk",
        "level": RiskLevel.WARN,
        "pattern": r"(invente|génère|crée\s+des\s+données|simule\s+des\s+résultats|fictif)",
        "message": "QGISIA+ ne génère jamais de données géographiques fictives.",
        "alternative": "Indique les vraies sources de données à utiliser.",
    },
]

# ── Règles OUTPUT (code PyQGIS généré) ──────────────────────────────────────

_PYQGIS_DESTRUCTIVE_PATTERNS: List[Dict[str, Any]] = [
    {
        "id": "delete_features",
        "level": RiskLevel.CONFIRM,
        "pattern": r"\.deleteFeature[s]?\s*\(",
        "message": "Ce code supprime des entités de façon irréversible.",
        "alternative": None,
    },
    {
        "id": "delete_layer",
        "level": RiskLevel.CONFIRM,
        "pattern": r"QgsProject\.instance\(\)\.removeMapLayer[s]?\s*\(",
        "message": "Ce code supprime une ou plusieurs couches du projet.",
        "alternative": "Vérifier d'abord en mode lecture seule.",
    },
    {
        "id": "overwrite_file",
        "level": RiskLevel.CONFIRM,
        "pattern": r"(QgsVectorFileWriter|writeAsVectorFormat).*overwrite\s*=\s*True",
        "message": "Ce code va écraser un fichier existant.",
        "alternative": "Exporter vers un nouveau fichier avec un nom différent.",
    },
    {
        "id": "drop_table_sql",
        "level": RiskLevel.BLOCK,
        "pattern": r"DROP\s+TABLE",
        "message": "Suppression de table SQL bloquée.",
        "alternative": "Utilisez une requête SELECT pour vérifier les données d'abord.",
    },
    {
        "id": "bulk_delete",
        "level": RiskLevel.CONFIRM,
        "pattern": r"layer\.startEditing\(\).*deleteFeatures.*layer\.commitChanges\(\)",
        "message": "Ce code effectue une suppression massive d'entités.",
        "alternative": "Créer d'abord une sauvegarde de la couche.",
    },
    {
        "id": "subprocess_dangerous",
        "level": RiskLevel.BLOCK,
        "pattern": r"subprocess\.(run|Popen|call)\s*\(\s*[\"\'](rm|del|format|rd\s|shutdown)",
        "message": "Commande système dangereuse détectée dans le code.",
        "alternative": None,
    },
    {
        "id": "os_remove",
        "level": RiskLevel.CONFIRM,
        "pattern": r"os\.(remove|unlink|rmdir|rmtree)\s*\(",
        "message": "Ce code supprime des fichiers du système.",
        "alternative": "Vérifier le chemin du fichier avant suppression.",
    },
    {
        "id": "write_outside_project",
        "level": RiskLevel.WARN,
        "pattern": r"open\s*\(['\"](?!.*temp)(?!.*tmp)(?!.*\.log)[C-Z]:[/\\]",
        "message": "Écriture vers un chemin absolu système détectée.",
        "alternative": "Utiliser un chemin relatif au projet QGIS.",
    },
]

# ── Règles géographiques anti-hallucination ──────────────────────────────────

_GEO_HALLUCINATION_RULES: List[Dict[str, Any]] = [
    {
        "id": "fake_coordinates",
        "level": RiskLevel.WARN,
        "pattern": r"coordonnées?\s*:\s*\d+\.?\d*\s*,\s*\d+\.?\d*",
        "message": "Vérifier que les coordonnées proviennent d'une source réelle (pas générées).",
    },
    {
        "id": "invented_layer_name",
        "level": RiskLevel.WARN,
        "pattern": r"couche\s+[\"'][\w_]+[\"']\s+(contient|possède|inclut)\s+\d+\s+entités",
        "message": "QGISIA+ ne doit jamais inventer un nombre d'entités — vérifier avec le contexte réel.",
    },
]


class AgentGuardrails:
    """
    Système de guardrails pour l'agent QGISIA+.
    Compatible avec n'importe quel LLM via LiteLLM.
    """

    def __init__(self, auto_mode: bool = False):
        self._auto_mode = auto_mode
        self._confirmation_callback: Optional[Callable[[str, str], bool]] = None

    def set_auto_mode(self, enabled: bool) -> None:
        """En mode Auto, seul BLOCK reste bloquant. CONFIRM → avertissement."""
        self._auto_mode = enabled

    def set_confirmation_callback(self, cb: Callable[[str, str], bool]) -> None:
        """
        Callback pour demander confirmation à l'utilisateur.
        Signature: (title: str, message: str) -> bool (True = confirmer)
        En QGIS: QMessageBox. En dev: input() console.
        """
        self._confirmation_callback = cb

    # ── Contrôle des inputs ───────────────────────────────────────────────────

    def check_input(self, user_message: str) -> GuardrailResult:
        """Vérifie la requête utilisateur avant de l'envoyer au LLM."""
        msg_lower = user_message.lower()
        for rule in _INPUT_RULES:
            if re.search(rule["pattern"], msg_lower, re.IGNORECASE):
                level = rule["level"]
                if level == RiskLevel.BLOCK:
                    return GuardrailResult(
                        passed=False, risk_level=level,
                        rule_triggered=rule["id"], message=rule["message"],
                        suggested_alternative=rule.get("alternative"),
                    )
                if level == RiskLevel.WARN:
                    return GuardrailResult(
                        passed=True, risk_level=level,
                        rule_triggered=rule["id"], message=rule["message"],
                    )
        return GuardrailResult(
            passed=True, risk_level=RiskLevel.SAFE,
            rule_triggered=None, message="OK",
        )

    # ── Contrôle du code PyQGIS généré ────────────────────────────────────────

    def check_pyqgis_code(self, code: str) -> GuardrailResult:
        """
        Analyse le code PyQGIS généré par le LLM.
        Retourne le résultat le plus restrictif trouvé.
        """
        highest_risk = RiskLevel.SAFE
        triggered_rule: Optional[Dict] = None

        for rule in _PYQGIS_DESTRUCTIVE_PATTERNS + _GEO_HALLUCINATION_RULES:
            if re.search(rule["pattern"], code, re.IGNORECASE | re.DOTALL):
                if self._is_more_restrictive(rule["level"], highest_risk):
                    highest_risk = rule["level"]
                    triggered_rule = rule

        if triggered_rule is None:
            return GuardrailResult(
                passed=True, risk_level=RiskLevel.SAFE,
                rule_triggered=None, message="Code PyQGIS validé.",
            )

        passed = self._evaluate_risk(highest_risk, triggered_rule)
        return GuardrailResult(
            passed=passed,
            risk_level=highest_risk,
            rule_triggered=triggered_rule["id"],
            message=triggered_rule["message"],
            suggested_alternative=triggered_rule.get("alternative"),
            requires_confirmation=(highest_risk == RiskLevel.CONFIRM and not self._auto_mode),
        )

    def check_output(self, llm_response: str, context: Optional[Dict] = None) -> GuardrailResult:
        """
        Vérifie la réponse complète du LLM avant de la montrer à l'utilisateur.
        Extrait le code Python si présent et l'analyse.
        """
        code_blocks = re.findall(r"```(?:python|pyqgis)?\n(.*?)```", llm_response, re.DOTALL)
        if not code_blocks:
            return GuardrailResult(
                passed=True, risk_level=RiskLevel.SAFE,
                rule_triggered=None, message="Réponse textuelle validée.",
            )
        combined_code = "\n".join(code_blocks)
        return self.check_pyqgis_code(combined_code)

    # ── Confirmation utilisateur ──────────────────────────────────────────────

    def request_confirmation(self, action_description: str, risk_message: str) -> bool:
        """
        Demande confirmation à l'utilisateur pour une action CONFIRM.
        Utilise le callback si défini, sinon bloque en auto_mode.
        """
        if self._auto_mode:
            return True  # En mode auto, CONFIRM → autorisé avec warning
        if self._confirmation_callback:
            return self._confirmation_callback(
                f"⚠️ Confirmation requise — {action_description}",
                f"{risk_message}\n\nConfirmer l'exécution ?",
            )
        return False  # Sans callback, bloquer par défaut

    # ── Rapport de sécurité ───────────────────────────────────────────────────

    def audit_messages(self, messages: List[Dict[str, str]]) -> List[GuardrailResult]:
        """Audit d'une liste de messages (pour tests et logging)."""
        results = []
        for msg in messages:
            if msg.get("role") == "user":
                results.append(self.check_input(msg.get("content", "")))
        return results

    # ── Helpers privés ────────────────────────────────────────────────────────

    @staticmethod
    def _is_more_restrictive(new: RiskLevel, current: RiskLevel) -> bool:
        order = {RiskLevel.SAFE: 0, RiskLevel.WARN: 1, RiskLevel.CONFIRM: 2, RiskLevel.BLOCK: 3}
        return order[new] > order[current]

    def _evaluate_risk(self, level: RiskLevel, rule: Dict) -> bool:
        if level == RiskLevel.BLOCK:
            return False
        if level == RiskLevel.CONFIRM:
            return self._auto_mode  # auto_mode → on passe, sinon UI doit confirmer
        return True  # SAFE / WARN → passe toujours


# ── Singleton global ─────────────────────────────────────────────────────────
_guardrails_instance: Optional[AgentGuardrails] = None


def get_guardrails(auto_mode: bool = False) -> AgentGuardrails:
    global _guardrails_instance
    if _guardrails_instance is None:
        _guardrails_instance = AgentGuardrails(auto_mode=auto_mode)
    return _guardrails_instance


def quick_check_code(code: str) -> Tuple[bool, str]:
    """
    Vérification rapide d'un bloc de code PyQGIS.
    Retourne (safe, message).
    Pratique pour appel direct depuis geoai_assistant.py.
    """
    result = get_guardrails().check_pyqgis_code(code)
    return result.passed, result.message
