import os

from qgis.PyQt.QtCore import Qt, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolButton

from .dock_widget import GbifDownloaderDock


class GbifDownloaderPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.dock = None
        self.toolbar = self.iface.addToolBar("GBIF Downloader")
        self.toolbar.setObjectName("GbifDownloaderToolbar")
        self._tool_button = None

    def tr(self, message):
        return QCoreApplication.translate("GbifDownloader", message)

    def initGui(self):
        icon = QIcon(os.path.join(self.plugin_dir, "gbif-downloader-icon.png"))

        # Main action — toggles the dock panel
        self.action_toggle = QAction(icon, self.tr("GBIF Downloader"), self.iface.mainWindow())
        self.action_toggle.setCheckable(True)
        self.action_toggle.setStatusTip(self.tr("Toggle GBIF Downloader panel"))
        self.action_toggle.triggered.connect(self._toggle_dock)

        # Dropdown action — opens credentials dialog
        self.action_credentials = QAction(
            self.tr("Configure GBIF Credentials"),
            self.iface.mainWindow(),
        )
        self.action_credentials.setStatusTip(self.tr("Set GBIF username and password"))
        self.action_credentials.triggered.connect(self._open_credentials)

        # Dropdown menu attached to the toolbar button
        menu = QMenu(self.iface.mainWindow())
        menu.addAction(self.action_toggle)
        menu.addSeparator()
        menu.addAction(self.action_credentials)

        # Single QToolButton: left-click toggles dock, arrow shows menu
        self._tool_button = QToolButton()
        self._tool_button.setIcon(icon)
        self._tool_button.setText(self.tr("GBIF Downloader"))
        self._tool_button.setToolTip(self.tr("GBIF Downloader"))
        self._tool_button.setCheckable(True)
        self._tool_button.setPopupMode(QToolButton.MenuButtonPopup)
        self._tool_button.setMenu(menu)
        self._tool_button.clicked.connect(self._on_button_clicked)
        self.toolbar.addWidget(self._tool_button)

        # Keep menu entries in the Plugins menu as well
        self.iface.addPluginToMenu(self.tr("&GBIF Downloader"), self.action_toggle)
        self.iface.addPluginToMenu(self.tr("&GBIF Downloader"), self.action_credentials)

        self._create_dock()

    def _create_dock(self):
        self.dock = GbifDownloaderDock(self.iface, self.iface.mainWindow())
        self.dock.visibilityChanged.connect(self._tool_button.setChecked)
        self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.hide()

    def _on_button_clicked(self, checked):
        if checked:
            self.dock.show()
            self.dock.raise_()
        else:
            self.dock.hide()

    def _toggle_dock(self, checked):
        self._tool_button.setChecked(checked)
        self._on_button_clicked(checked)

    def _open_credentials(self):
        from .credentials_dialog import CredentialsDialog
        dlg = CredentialsDialog(self.iface.mainWindow())
        dlg.exec_()

    def unload(self):
        self.iface.removePluginMenu(self.tr("&GBIF Downloader"), self.action_toggle)
        self.iface.removePluginMenu(self.tr("&GBIF Downloader"), self.action_credentials)
        self.toolbar.clear()
        del self.toolbar
        if self.dock:
            self.dock.cleanup()
            self.iface.mainWindow().removeDockWidget(self.dock)
            self.dock.setParent(None)
            self.dock = None
