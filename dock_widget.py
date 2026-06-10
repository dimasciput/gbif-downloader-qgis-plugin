from qgis.PyQt.QtWidgets import QDockWidget, QTabWidget, QVBoxLayout, QWidget

from .tab_action import ActionTab
from .tab_downloads import DownloadsTab


class GbifDownloaderDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("GBIF Downloader", parent)
        self.setObjectName("GbifDownloaderDock")
        self.setMinimumWidth(360)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        self.tabs = QTabWidget()
        self.tab_action = ActionTab(iface)
        self.tab_downloads = DownloadsTab()
        self.tabs.addTab(self.tab_action, "Action")
        self.tabs.addTab(self.tab_downloads, "Downloads")

        self.tab_action.download_submitted.connect(self._on_download_submitted)

        layout.addWidget(self.tabs)
        self.setWidget(container)

    def _on_download_submitted(self, key: str):
        self.tabs.setCurrentWidget(self.tab_downloads)
        self.tab_downloads.add_pending(key)

    def cleanup(self):
        self.tab_action.cleanup()
