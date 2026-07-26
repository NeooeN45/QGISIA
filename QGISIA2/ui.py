# -*- coding: utf-8 -*-
"""
Interface utilisateur améliorée pour le plugin GeoAI Assistant
Utilise le navigateur externe par défaut
"""
import os
import sys
import subprocess
import webbrowser

import qgis.PyQt
from qgis.PyQt.QtCore import Qt, QUrl, pyqtSignal, pyqtSlot, QTimer, QProcess
from qgis.PyQt.QtGui import QIcon, QDesktopServices
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
    QScrollArea,
    QGridLayout,
    QProgressBar,
    QMessageBox,
)
import webbrowser
import subprocess
import sys
import os
import time
import requests
from qgis.core import Qgis

from .config import PLUGIN_CONFIG


class LaunchButton(QPushButton):
    """Bouton de lancement principal avec design moderne"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText("🚀 Lancer QGISAI+ AI")
        self.setMinimumHeight(60)
        self.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #10b981, stop:1 #059669);
                border: none;
                border-radius: 12px;
                color: white;
                font-size: 16px;
                font-weight: 600;
                padding: 16px 24px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #059669, stop:1 #047857);
                transform: translateY(-2px);
            }
            QPushButton:pressed {
                background: #047857;
                transform: translateY(0px);
            }
        """)


class InfoCard(QFrame):
    """Carte d'information avec style moderne"""

    def __init__(self, title, content, icon="ℹ️", parent=None):
        super().__init__(parent)
        # Qt6: utiliser Shape et Shadow au lieu de StyledPanel
        self.setFrameShape(QFrame.Shape.Panel)
        self.setFrameShadow(QFrame.Shadow.Sunken)
        self.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
                padding: 16px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # Header
        header = QLabel(f"{icon} {title}")
        header.setStyleSheet("""
            QLabel {
                color: #e3e3e3;
                font-size: 14px;
                font-weight: 600;
            }
        """)
        layout.addWidget(header)

        # Content
        content_label = QLabel(content)
        content_label.setStyleSheet("""
            QLabel {
                color: #9ca3af;
                font-size: 12px;
                line-height: 1.5;
            }
        """)
        content_label.setWordWrap(True)
        layout.addWidget(content_label)


class QGISAILaunchDock(QDockWidget):
    """Dock widget de lancement pour QGISAI+ - affiché sur le côté de QGIS"""

    def __init__(self, iface, server_url="http://localhost:5173", parent=None):
        super().__init__("QGISAI+", parent)
        self.iface = iface
        self.server_url = server_url
        self.project_path = self._find_project_path()
        self.server_process = None
        self.server_ready = False
        self.setObjectName("geoaiLaunchDock")

        # Configuration du dock
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable |
                        QDockWidget.DockWidgetFeature.DockWidgetMovable |
                        QDockWidget.DockWidgetFeature.DockWidgetFloatable)

        # Créer le widget principal
        self._create_ui()

        # Appliquer le style
        self._apply_style()

    def _find_project_path(self):
        """Trouve le chemin du projet QGISAI+"""
        # Chemins possibles du projet
        possible_paths = [
            r"c:\Users\camil\Desktop\Micro Entreprise\04_PROJETS_EN_COURS\Projet\GeoSylva_AI_QGIS_OpenRouter",
            os.path.expanduser(r"~\Desktop\Micro Entreprise\04_PROJETS_EN_COURS\Projet\GeoSylva_AI_QGIS_OpenRouter"),
            os.path.expanduser(r"~\GeoSylva_AI_QGIS_OpenRouter"),
        ]

        for path in possible_paths:
            if os.path.exists(path) and os.path.exists(os.path.join(path, "package.json")):
                return path

        return None

    def _check_server_running(self):
        """Vérifie si le serveur est déjà en cours d'exécution"""
        try:
            response = requests.get(self.server_url, timeout=2)
            return response.status_code == 200
        except:
            return False

    def _start_server(self):
        """Démarre le serveur de développement"""
        if not self.project_path:
            self.status_label.setText("❌ Projet non trouvé")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #ef4444;
                    font-size: 12px;
                    font-weight: 600;
                }
            """)
            return False

        try:
            self.status_label.setText("🔄 Démarrage du serveur...")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #f59e0b;
                    font-size: 12px;
                    font-weight: 600;
                }
            """)

            # Trouver npm
            npm_path = self._find_npm()
            if not npm_path:
                self.status_label.setText("❌ npm non trouvé")
                self.status_label.setStyleSheet("""
                    QLabel {
                        color: #ef4444;
                        font-size: 12px;
                        font-weight: 600;
                    }
                """)
                return False

            # Lancer npm run dev en arrière-plan
            if sys.platform == "win32":
                # Windows: utiliser npm directement
                self.server_process = subprocess.Popen(
                    [npm_path, "run", "dev"],
                    cwd=self.project_path,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                # Linux/Mac
                self.server_process = subprocess.Popen(
                    [npm_path, "run", "dev"],
                    cwd=self.project_path,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

            # Utiliser QTimer pour vérifier périodiquement sans bloquer l'UI
            self.server_check_count = 0
            self.server_check_timer = QTimer()
            self.server_check_timer.timeout.connect(self._check_server_ready)
            self.server_check_timer.start(500)  # Vérifier toutes les 500ms

            return True

        except Exception as e:
            self.status_label.setText(f"❌ Erreur: {str(e)}")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #ef4444;
                    font-size: 12px;
                    font-weight: 600;
                }
            """)
            return False

    def _check_server_ready(self):
        """Vérifie si le serveur est prêt (appelé par QTimer)"""
        self.server_check_count += 1

        if self._check_server_running():
            # Serveur prêt
            self.server_ready = True
            self.server_check_timer.stop()
            self.status_label.setText("✅ Serveur prêt!")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #10b981;
                    font-size: 12px;
                    font-weight: 600;
                }
            """)
            # Lancer le navigateur automatiquement
            self._open_browser()
        elif self.server_check_count >= 60:  # 60 * 500ms = 30 secondes
            # Timeout
            self.server_check_timer.stop()
            self.status_label.setText("⏱️ Timeout - serveur non démarré")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #f59e0b;
                    font-size: 12px;
                    font-weight: 600;
                }
            """)
        else:
            # Continuer à attendre
            self.status_label.setText(f"⏳ Attente du serveur... ({self.server_check_count}/60)")

    def _open_browser(self):
        """Ouvre le navigateur"""
        try:
            webbrowser.open(self.server_url)
            self.status_label.setText("✅ Navigateur ouvert!")
            self.iface.messageBar().pushMessage(
                "QGISAI+ AI",
                "Navigateur ouvert. Connectez-vous à l'interface.",
                Qgis.MessageLevel.Success,
                5
            )
            # Fermer le dock après un délai
            QTimer.singleShot(2000, self.close)
        except Exception as e:
            self.status_label.setText(f"❌ Erreur navigateur: {str(e)}")

    def _find_npm(self):
        """Trouve le chemin vers npm"""
        # Essayer npm directement
        try:
            result = subprocess.run(["npm", "--version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return "npm"
        except:
            pass

        # Essayer avec where/which
        try:
            if sys.platform == "win32":
                result = subprocess.run(["where", "npm"], capture_output=True, timeout=5, text=True)
                if result.returncode == 0:
                    npm_path = result.stdout.strip().split('\n')[0]
                    return npm_path
            else:
                result = subprocess.run(["which", "npm"], capture_output=True, timeout=5, text=True)
                if result.returncode == 0:
                    return result.stdout.strip()
        except:
            pass

        # Chemins communs pour npm
        common_paths = [
            r"C:\Program Files\nodejs\npm.cmd",
            r"C:\Program Files (x86)\nodejs\npm.cmd",
            os.path.expanduser(r"~\AppData\Roaming\npm\npm.cmd"),
        ]

        for path in common_paths:
            if os.path.exists(path):
                return path

        return None

    def _create_ui(self):
        """Configure l'interface utilisateur"""
        # Widget conteneur
        container = QWidget()
        container.setObjectName("geoaiContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Header
        header = self._create_header()
        layout.addWidget(header)

        # Séparateur
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("background: rgba(255, 255, 255, 0.1);")
        layout.addWidget(separator)

        # Cartes d'information
        info_cards = self._create_info_cards()
        layout.addWidget(info_cards)

        # Bouton de lancement
        launch_btn = LaunchButton()
        launch_btn.clicked.connect(self._launch_browser)
        layout.addWidget(launch_btn)

        # Zone de status
        self.status_label = QLabel("Prêt à lancer")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #6b7280;
                font-size: 12px;
                text-align: center;
            }
        """)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # Footer
        footer = self._create_footer()
        layout.addWidget(footer)

        # Définir le widget du dock
        self.setWidget(container)

    def _create_header(self):
        """Crée le header avec logo et titre"""
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setSpacing(8)

        # Logo et titre
        title_row = QWidget()
        title_row_layout = QHBoxLayout(title_row)
        title_row_layout.setContentsMargins(0, 0, 0, 0)

        logo_label = QLabel("🌲")
        logo_label.setStyleSheet("font-size: 48px;")
        title_row_layout.addWidget(logo_label)

        title_column = QWidget()
        title_column_layout = QVBoxLayout(title_column)
        title_column_layout.setContentsMargins(0, 0, 0, 0)
        title_column_layout.setSpacing(4)

        title = QLabel("QGISAI+ AI")
        title.setStyleSheet("""
            QLabel {
                color: #e3e3e3;
                font-size: 24px;
                font-weight: 700;
            }
        """)

        subtitle = QLabel("Assistant SIG intelligent pour QGIS")
        subtitle.setStyleSheet("""
            QLabel {
                color: #9ca3af;
                font-size: 14px;
            }
        """)

        title_column_layout.addWidget(title)
        title_column_layout.addWidget(subtitle)
        title_row_layout.addWidget(title_column, 1)

        header_layout.addWidget(title_row)

        return header

    def _create_info_cards(self):
        """Crée les cartes d'information"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(12)

        cards = [
            {
                "title": "🤖 Assistant Conversationnel",
                "content": "Discutez avec votre projet QGIS en langage naturel. L'IA comprend vos demandes et exécute les actions appropriées."
            },
            {
                "title": "🗺️ Sources Officielles",
                "content": "Accédez directement aux données IGN, API Carto, geo.api.gouv.fr, Copernicus et plus encore."
            },
            {
                "title": "⚡ Automatisation PyQGIS",
                "content": "Générez et exécutez automatiquement des scripts PyQGIS pour vos tâches SIG complexes."
            }
        ]

        for card in cards:
            info_card = InfoCard(card["title"], card["content"])
            layout.addWidget(info_card)

        return container

    def _create_footer(self):
        """Crée le footer avec informations de connexion"""
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setSpacing(8)

        # Chemin du projet
        if self.project_path:
            path_label = QLabel(f"📁 Projet: {self.project_path}")
            path_label.setStyleSheet("""
                QLabel {
                    color: #6b7280;
                    font-size: 10px;
                    font-family: monospace;
                    background: rgba(107, 114, 128, 0.1);
                    padding: 6px 10px;
                    border-radius: 4px;
                }
            """)
            path_label.setWordWrap(True)
            footer_layout.addWidget(path_label)

        url_label = QLabel(f"🌐 Serveur: {self.server_url}")
        url_label.setStyleSheet("""
            QLabel {
                color: #10b981;
                font-size: 12px;
                font-family: monospace;
                background: rgba(16, 185, 129, 0.1);
                padding: 8px 12px;
                border-radius: 6px;
            }
        """)
        url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_layout.addWidget(url_label)

        hint_label = QLabel("💡 Le serveur démarrera automatiquement. Le navigateur s'ouvrira une fois le serveur prêt.")
        hint_label.setStyleSheet("""
            QLabel {
                color: #6b7280;
                font-size: 11px;
                font-style: italic;
            }
        """)
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_label.setWordWrap(True)
        footer_layout.addWidget(hint_label)

        return footer

    def _apply_style(self):
        """Applique le style global"""
        self.setStyleSheet("""
            QDockWidget#geoaiLaunchDock {
                background: #131314;
                border: none;
            }
            QWidget#geoaiContainer {
                background: #131314;
            }
        """)

    def _launch_browser(self):
        """Lance le navigateur externe avec l'interface QGISAI+"""
        try:
            # Vérifier si le serveur est déjà en cours d'exécution
            if self._check_server_running():
                self.status_label.setText("✅ Serveur déjà en cours d'exécution")
                self.status_label.setStyleSheet("""
                    QLabel {
                        color: #10b981;
                        font-size: 12px;
                        font-weight: 600;
                    }
                """)
                self.server_ready = True
                # Ouvrir le navigateur immédiatement
                self._open_browser()
            else:
                # Démarrer le serveur (le QTimer gérera l'ouverture du navigateur)
                if not self._start_server():
                    # Échec du démarrage
                    QMessageBox.warning(
                        self,
                        "Serveur non démarré",
                        f"Le serveur n'a pas pu être démarré automatiquement.\n\n"
                        f"Chemin du projet: {self.project_path or 'Non trouvé'}\n\n"
                        f"Veuillez démarrer manuellement:\n"
                        f"cd {self.project_path}\n"
                        f"npm run dev"
                    )
                    return

        except Exception as e:
            self.status_label.setText(f"❌ Erreur: {str(e)}")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #ef4444;
                    font-size: 12px;
                    font-weight: 600;
                }
            """)


class QuickActionButton(QPushButton):
    """Bouton d'action rapide avec icône et tooltip"""
    
    def __init__(self, action_config, parent=None):
        super().__init__(parent)
        self.action_id = action_config["id"]
        self.setText(action_config["label"])
        self.setToolTip(action_config["tooltip"])
        self.setMinimumHeight(40)
        self.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(8, 145, 178, 0.2), stop:1 rgba(8, 145, 178, 0.1));
                border: 1px solid rgba(8, 145, 178, 0.3);
                border-radius: 8px;
                color: #e3e3e3;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(8, 145, 178, 0.4), stop:1 rgba(8, 145, 178, 0.2));
                border-color: rgba(8, 145, 178, 0.5);
            }
            QPushButton:pressed {
                background: rgba(8, 145, 178, 0.3);
            }
        """)


class StatusIndicator(QLabel):
    """Indicateur de status avec animation"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._status = "disconnected"
        self._update_style()

    def set_status(self, status):
        """Définit le status: connected, disconnected, loading, error"""
        self._status = status
        self._update_style()

    def _update_style(self):
        """Met à jour le style selon le status"""
        colors = {
            "connected": "#10b981",  # green
            "disconnected": "#6b7280",  # gray
            "loading": "#f59e0b",  # amber
            "error": "#ef4444",  # red
        }
        color = colors.get(self._status, "#6b7280")
        self.setStyleSheet(f"""
            QLabel {{
                background: {color};
                border-radius: 6px;
            }}
        """)


class LoadingOverlay(QWidget):
    """Overlay de chargement semi-transparent"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._animation_timer = None
        self._dot_index = 0

    def _setup_ui(self):
        """Configure l'interface de l'overlay"""
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Container semi-transparent
        container = QWidget()
        container.setStyleSheet("""
            QWidget {
                background: rgba(19, 19, 20, 0.95);
                border-radius: 8px;
            }
        """)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(24, 24, 24, 24)
        container_layout.setSpacing(16)

        # Message de chargement
        self.message_label = QLabel("Chargement...")
        self.message_label.setStyleSheet("""
            QLabel {
                color: #e3e3e3;
                font-size: 14px;
                font-weight: 500;
            }
        """)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(self.message_label)

        # Indicateur de progression animé
        self.progress_label = QLabel("●●●")
        self.progress_label.setStyleSheet("""
            QLabel {
                color: #10b981;
                font-size: 20px;
                letter-spacing: 4px;
            }
        """)
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(self.progress_label)

        layout.addWidget(container, 0, Qt.AlignmentFlag.AlignCenter)

    def set_message(self, message):
        """Définit le message de chargement"""
        self.message_label.setText(message)

    def _animate_dots(self):
        """Anime les points de progression"""
        dots = ["●", "●●", "●●●"]
        self._dot_index = (self._dot_index + 1) % len(dots)
        self.progress_label.setText(dots[self._dot_index])

    def start_animation(self):
        """Démarre l'animation"""
        if self._animation_timer is None:
            self._animation_timer = QTimer()
            self._animation_timer.timeout.connect(self._animate_dots)
            self._animation_timer.start(500)

    def stop_animation(self):
        """Arrête l'animation"""
        if self._animation_timer is not None:
            self._animation_timer.stop()
            self._animation_timer = None
        self.progress_label.setText("●●●")


class EnhancedDockWidget(QDockWidget):
    """Dock widget amélioré avec interface utilisateur moderne"""
    
    # Signaux
    action_triggered = pyqtSignal(str)  # Quand une action rapide est déclenchée
    settings_requested = pyqtSignal()  # Quand les paramètres sont demandés
    
    def __init__(self, iface, parent=None):
        super().__init__(PLUGIN_CONFIG["dock_title"], parent)
        self.iface = iface
        self.setObjectName("geoaiEnhancedDock")

        # Overlay de chargement
        self.loading_overlay = None

        # Configuration
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        # Créer le widget principal
        self._create_ui()

        # Appliquer le style
        self._apply_style()
    
    def _create_ui(self):
        """Crée l'interface utilisateur"""
        # Widget conteneur
        container = QWidget()
        container.setObjectName("geoaiContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        
        # Header avec status
        header = self._create_header()
        layout.addWidget(header)
        
        # Séparateur
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("background: rgba(255, 255, 255, 0.1);")
        layout.addWidget(separator)
        
        # Actions rapides
        if PLUGIN_CONFIG["show_quick_actions"]:
            quick_actions = self._create_quick_actions()
            layout.addWidget(quick_actions)
        
        # Zone de contenu (WebView sera ajoutée ici)
        self.content_area = QWidget()
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.content_area, 1)
        
        # Footer avec boutons
        footer = self._create_footer()
        layout.addWidget(footer)
        
        # Définir le widget du dock
        self.setWidget(container)
    
    def _create_header(self):
        """Crée le header avec titre et status"""
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        # Titre
        title = QLabel(PLUGIN_CONFIG["dock_title"])
        title.setStyleSheet("""
            QLabel {
                color: #e3e3e3;
                font-size: 16px;
                font-weight: 600;
            }
        """)
        header_layout.addWidget(title, 1)
        
        # Indicateur de status
        self.status_indicator = StatusIndicator()
        self.status_indicator.set_status("disconnected")
        header_layout.addWidget(self.status_indicator)
        
        return header
    
    def _create_quick_actions(self):
        """Crée les boutons d'action rapide"""
        container = QWidget()
        container.setObjectName("quickActionsContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Titre
        title = QLabel("Actions rapides")
        title.setStyleSheet("""
            QLabel {
                color: #9ca3af;
                font-size: 11px;
                font-weight: 500;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
        """)
        layout.addWidget(title)
        
        # Grille de boutons
        grid = QGridLayout()
        grid.setSpacing(8)
        
        actions = PLUGIN_CONFIG["quick_actions"]
        for i, action_config in enumerate(actions):
            button = QuickActionButton(action_config)
            button.clicked.connect(lambda checked, aid=action_config["id"]: self.action_triggered.emit(aid))
            row = i // 2
            col = i % 2
            grid.addWidget(button, row, col)
        
        layout.addLayout(grid)
        
        return container
    
    def _create_footer(self):
        """Crée le footer avec boutons d'action"""
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(8)
        
        # Bouton de paramètres
        if PLUGIN_CONFIG["show_settings_button"]:
            settings_btn = QPushButton("⚙️")
            settings_btn.setToolTip("Paramètres")
            settings_btn.setFixedSize(32, 32)
            settings_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.05);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 6px;
                    color: #9ca3af;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.1);
                    color: #e3e3e3;
                }
            """)
            settings_btn.clicked.connect(self.settings_requested.emit)
            footer_layout.addWidget(settings_btn)
        
        footer_layout.addStretch()
        
        # Label de version
        version_label = QLabel(f"v{PLUGIN_CONFIG['version']}")
        version_label.setStyleSheet("""
            QLabel {
                color: #6b7280;
                font-size: 10px;
            }
        """)
        footer_layout.addWidget(version_label)
        
        return footer
    
    def _apply_style(self):
        """Applique le style global"""
        self.setStyleSheet("""
            QDockWidget#geoaiEnhancedDock {
                background: #131314;
                border: none;
            }
            QWidget#geoaiContainer {
                background: #131314;
            }
        """)
    
    def set_web_view(self, web_view):
        """Définit la WebView dans la zone de contenu"""
        # Nettoyer le layout existant
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Ajouter la WebView
        self.content_layout.addWidget(web_view)
    
    def set_connection_status(self, connected):
        """Met à jour l'indicateur de connexion"""
        self.status_indicator.set_status("connected" if connected else "disconnected")

    def show_loading(self, message="Chargement..."):
        """Affiche un indicateur de chargement"""
        if self.loading_overlay is None:
            self.loading_overlay = LoadingOverlay(self)
            self.loading_overlay.setGeometry(self.rect())

        self.loading_overlay.set_message(message)
        self.loading_overlay.start_animation()
        self.loading_overlay.raise_()
        self.loading_overlay.show()

    def hide_loading(self):
        """Masque l'indicateur de chargement"""
        if self.loading_overlay is not None:
            self.loading_overlay.stop_animation()
            self.loading_overlay.hide()
