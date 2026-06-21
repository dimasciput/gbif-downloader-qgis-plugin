import os
import tempfile

import sip

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QDate, QSize, QTimer, QUrl
from qgis.PyQt.QtWidgets import (
    QAction,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QWidget,
)

from .cache import (
    cache_dir,
    load_cached_keys,
    load_page_cache,
    save_cached,
    save_page_cache,
)
from .helpers import PENDING, POLL_MS, STATUSES
from .styling import apply_iucn_style
from .widgets import DownloadItemWidget
from .report_worker import ReportWorker
from .workers import DownloadWorker, FetchPageWorker, PollWorker

PAGE_LIMIT = 50

_GUI_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gui")
FORM_CLASS, _ = uic.loadUiType(os.path.join(_GUI_DIR, "downloads_tab.ui"))


class DownloadsTab(QWidget, FORM_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.status_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.from_date.setDate(QDate.currentDate())
        self.refresh_btn.clicked.connect(self.refresh)
        self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn.clicked.connect(self._next_page)
        self.clear_filter_btn.clicked.connect(self._clear_filters)
        self.from_check.toggled.connect(self.from_date.setEnabled)
        self.from_check.toggled.connect(self._on_filter_changed)
        self.from_date.dateChanged.connect(self._on_filter_changed)

        self._status_menu    = QMenu(self)
        self._status_actions: dict[str, QAction] = {}
        for s in STATUSES:
            action = QAction(s, self)
            action.setCheckable(True)
            action.triggered.connect(self._on_filter_changed)
            self._status_menu.addAction(action)
            self._status_actions[s] = action
        self.status_btn.setMenu(self._status_menu)

        self._credentials_btn = QPushButton("Configure GBIF Credentials…")
        self._credentials_btn.clicked.connect(self._open_credentials_dialog)
        self._credentials_btn.hide()
        self.verticalLayout.insertWidget(1, self._credentials_btn)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_MS)
        self._poll_timer.timeout.connect(self._poll_pending)

        self._page_limit  = PAGE_LIMIT
        self._page_offset = 0
        self._total       = 0

        self._items: dict[str, tuple[QListWidgetItem, DownloadItemWidget]] = {}
        self._fetch_worker     = None
        self._poll_worker      = None
        self._download_workers = []
        self._report_workers   = []

        cached = load_page_cache(
            0, self._page_limit,
            self._get_status_filter(), self._get_from_filter(),
        )
        if cached:
            for dl in load_cached_keys(cached["keys"]):
                self._insert_item(dl)
            self._total = cached["count"]
            self._update_pagination()
            self.status_label.setText(f"{len(self._items)} download(s) (cached)")
            self.status_label.setStyleSheet("color: grey;")
            if any(w.status() in PENDING for _, (_, w) in self._items.items()):
                self._poll_timer.start()
        self.refresh()

    def add_pending(self, key: str):
        data = {
            "key": key, "status": "SUBMITTED",
            "created": "", "totalRecords": None, "downloadLink": "",
        }
        save_cached(data)
        if self._page_offset == 0:
            self._insert_item(data, at_top=True)
        self.status_label.setText(f"Queued: {key}")
        self.status_label.setStyleSheet("color: green;")
        self._poll_pending()
        self._poll_timer.start()

    def _get_status_filter(self) -> list:
        return [s for s, a in self._status_actions.items() if a.isChecked()]

    def _get_from_filter(self) -> str:
        if self.from_check.isChecked():
            return self.from_date.date().toString("yyyy-MM-dd") + "T00:00:00Z"
        return ""

    def _on_filter_changed(self):
        selected = self._get_status_filter()
        if not selected:
            self.status_btn.setText("Status: All")
        elif len(selected) <= 2:
            self.status_btn.setText(f"Status: {', '.join(selected)}")
        else:
            self.status_btn.setText(f"Status: {len(selected)} selected")
        self._page_offset = 0
        self.refresh()

    def _clear_filters(self):
        self.status_btn.blockSignals(True)
        self.from_check.blockSignals(True)
        self.from_date.blockSignals(True)
        try:
            for action in self._status_actions.values():
                action.setChecked(False)
            self.from_check.setChecked(False)
            self.from_date.setDate(QDate.currentDate())
        finally:
            self.status_btn.blockSignals(False)
            self.from_check.blockSignals(False)
            self.from_date.blockSignals(False)
        self.from_date.setEnabled(False)
        self.status_btn.setText("Status: All")
        self._page_offset = 0
        self.refresh()

    def _open_credentials_dialog(self):
        from ..credentials_dialog import CredentialsDialog
        dlg = CredentialsDialog(self)
        dlg.exec_()
        self.refresh()

    def refresh(self):
        from ..gbif_api import get_credentials
        username, _ = get_credentials()
        if not username:
            self.status_label.setText(
                "No GBIF credentials configured.\n"
                "Use the dropdown → Configure GBIF Credentials."
            )
            self.status_label.setStyleSheet("color: orange;")
            self._credentials_btn.show()
            return
        self._credentials_btn.hide()
        self.refresh_btn.setEnabled(False)
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.status_label.setText("Loading…")
        self.status_label.setStyleSheet("color: grey;")
        self._fetch_worker = FetchPageWorker(
            self._page_offset, self._page_limit,
            self._get_status_filter(), self._get_from_filter(),
        )
        self._fetch_worker.finished.connect(self._on_fetched)
        self._fetch_worker.error.connect(self._on_error)
        self._fetch_worker.start()

    def _prev_page(self):
        if self._page_offset > 0:
            self._page_offset = max(0, self._page_offset - self._page_limit)
            self._load_page(self._page_offset)

    def _next_page(self):
        if self._page_offset + self._page_limit < self._total:
            self._page_offset += self._page_limit
            self._load_page(self._page_offset)

    def _load_page(self, offset: int):
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        statuses  = self._get_status_filter()
        from_date = self._get_from_filter()
        cached    = load_page_cache(offset, self._page_limit, statuses, from_date)
        if cached:
            self.list_widget.clear()
            self._items.clear()
            for dl in load_cached_keys(cached["keys"]):
                self._insert_item(dl)
            self._total = cached["count"]
            if self._total:
                current_page = offset // self._page_limit + 1
                total_pages  = (self._total + self._page_limit - 1) // self._page_limit
                self.page_label.setText(
                    f"Page {current_page} of {total_pages}  ({self._total:,} total)"
                )
        self.refresh()

    def _update_pagination(self):
        if self._total == 0:
            self.page_label.setText("-")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return
        current_page = self._page_offset // self._page_limit + 1
        total_pages  = (self._total + self._page_limit - 1) // self._page_limit
        self.page_label.setText(
            f"Page {current_page} of {total_pages}  ({self._total:,} total)"
        )
        self.prev_btn.setEnabled(self._page_offset > 0)
        self.next_btn.setEnabled(self._page_offset + self._page_limit < self._total)

    def _poll_pending(self):
        if self._poll_worker and self._poll_worker.isRunning():
            return
        keys = [k for k, (_, w) in self._items.items() if w.status() in PENDING]
        if not keys:
            self._poll_timer.stop()
            return
        self._poll_worker = PollWorker(keys)
        self._poll_worker.updated.connect(self._on_poll_result)
        self._poll_worker.start()

    def _on_poll_result(self, key: str, data: dict):
        save_cached(data)
        if key not in self._items:
            return
        list_item, widget = self._items[key]
        widget.update_data(data)
        list_item.setSizeHint(widget.sizeHint())

    def _insert_item(self, data: dict, at_top: bool = False):
        key = data.get("key", "")
        if key in self._items:
            _, widget = self._items[key]
            widget.update_data(data)
            return
        widget    = DownloadItemWidget(data, self)
        list_item = QListWidgetItem()
        list_item.setSizeHint(QSize(0, 100))
        if at_top:
            self.list_widget.insertItem(0, list_item)
        else:
            self.list_widget.addItem(list_item)
        self.list_widget.setItemWidget(list_item, widget)
        self._items[key] = (list_item, widget)

    def _on_fetched(self, downloads: list, total: int, offset: int, limit: int):
        self.refresh_btn.setEnabled(True)
        self._total       = total
        self._page_offset = offset
        for dl in downloads:
            save_cached(dl)
        save_page_cache(
            offset, limit, total,
            [dl.get("key", "") for dl in downloads],
            self._get_status_filter(),
            self._get_from_filter(),
        )
        self.list_widget.clear()
        self._items.clear()
        for dl in downloads:
            self._insert_item(dl)
        self._update_pagination()
        count = len(downloads)
        self.status_label.setText(f"{count} download(s) on this page")
        self.status_label.setStyleSheet("color: green;" if count else "color: grey;")
        if any(w.status() in PENDING for _, (_, w) in self._items.items()):
            self._poll_timer.start()

    def _save(self, url: str, fmt: str, key: str = ""):
        from qgis.PyQt.QtGui import QDesktopServices
        source_zip = ""
        if fmt == "zip":
            key_dir = cache_dir() / key
            key_dir.mkdir(exist_ok=True)
            dest = str(key_dir / "download.zip")
            if os.path.exists(dest):
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(key_dir)))
                self.status_label.setText("Already saved - opened folder")
                self.status_label.setStyleSheet("color: green;")
                return
        elif fmt == "map":
            dest = os.path.join(tempfile.gettempdir(), f"{key or 'gbif_download'}.tsv")
            cached_zip = str(cache_dir() / key / "download.zip")
            source_zip = cached_zip if os.path.exists(cached_zip) else ""
        else:
            return
        using_cache = bool(source_zip)
        self.status_label.setText("Extracting from cache…" if using_cache else "Downloading… 0%")
        self.status_label.setStyleSheet("color: grey;")
        w = DownloadWorker(url, dest, fmt, source_zip=source_zip)
        w.progress.connect(lambda p, lbl=self.status_label: lbl.setText(f"Downloading… {p}%") if not sip.isdeleted(lbl) else None)
        w.finished.connect(self._on_saved)
        w.error.connect(self._on_error)
        self._download_workers.append(w)
        w.start()

    def _on_saved(self, path: str, fmt: str):
        from qgis.PyQt.QtGui import QDesktopServices
        name = os.path.splitext(os.path.basename(path))[0]
        if fmt == "zip":
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
            self.status_label.setText("ZIP saved, folder opened")
        elif fmt == "map":
            file_url = QUrl.fromLocalFile(path).toString()
            uri = (
                f"{file_url}"
                f"?delimiter=%5Ct"
                f"&xField=decimallongitude"
                f"&yField=decimallatitude"
                f"&crs=EPSG:4326"
            )
            layer = QgsVectorLayer(uri, name, "delimitedtext")
            if layer.isValid():
                apply_iucn_style(layer)
                QgsProject.instance().addMapLayer(layer)
                self.status_label.setText(f"Layer added: {name}")
            else:
                self.status_label.setText(f"Saved but could not load layer: {path}")
        self.status_label.setStyleSheet("color: green;")
        self._download_workers = [w for w in self._download_workers if w.isRunning()]

    def _generate_report(self, url: str, key: str):
        from qgis.PyQt.QtGui import QDesktopServices
        existing = cache_dir() / key / "report.pdf"
        if existing.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(existing.parent)))
            self.status_label.setText(f"Report already exists: {key}")
            self.status_label.setStyleSheet("color: green;")
            return
        self.status_label.setText("Generating report…")
        self.status_label.setStyleSheet("color: grey;")
        w = ReportWorker(key, url)
        w.progress.connect(lambda msg, lbl=self.status_label: lbl.setText(msg) if not sip.isdeleted(lbl) else None)
        w.finished.connect(self._on_report_done)
        w.error.connect(self._on_report_error)
        self._report_workers.append(w)
        w.start()

    def _on_report_done(self, path: str):
        from qgis.PyQt.QtGui import QDesktopServices
        self.status_label.setText(f"Report saved: {os.path.basename(path)}")
        self.status_label.setStyleSheet("color: green;")
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
        self._report_workers = [w for w in self._report_workers if w.isRunning()]

    def _on_report_error(self, message: str):
        self.status_label.setText(f"Report failed: {message}")
        self.status_label.setStyleSheet("color: red;")
        self._report_workers = [w for w in self._report_workers if w.isRunning()]

    def _on_error(self, message: str):
        self.refresh_btn.setEnabled(True)
        self._update_pagination()
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: red;")
