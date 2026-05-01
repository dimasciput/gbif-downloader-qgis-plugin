import datetime
import json
import os
import pathlib
import shutil
import tempfile
import zipfile

from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QRect, QSize, QThread, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QPainter
from qgis.PyQt.QtWidgets import (
    QFileDialog,
    QLabel,
    QListWidgetItem,
    QWidget,
)

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "gui", "downloads_tab.ui")
)
ITEM_FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "gui", "download_item.ui")
)
FILTER_ITEM_FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "gui", "filter_item.ui")
)
DETAIL_FORM_CLASS, DETAIL_BASE_CLASS = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "gui", "download_detail_dialog.ui")
)

_POLL_MS = 30_000
_PENDING = {"PREPARING", "RUNNING", "SUBMITTED"}
_STATUS_CSS = {
    "SUCCEEDED": "#2d6a2d",
    "RUNNING":   "#1a3a6b",
    "PREPARING": "#1a7070",
    "SUBMITTED": "#1a7070",
    "FAILED":    "#b22222",
    "KILLED":    "#6b1a1a",
    "CANCELLED": "#888888",
}
_TSV_SKIP = {"citation", "rights", "metadata", "multimedia", "verbatim"}


def _find_tsv(zf: zipfile.ZipFile) -> str:
    candidates = [
        n for n in zf.namelist()
        if n.lower().endswith((".csv", ".tsv", ".txt"))
        and not any(s in n.lower() for s in _TSV_SKIP)
    ]
    return candidates[0] if candidates else zf.namelist()[0]


# ---------------------------------------------------------------------------
# Local cache helpers
# ---------------------------------------------------------------------------

def _cache_dir() -> pathlib.Path:
    base = pathlib.Path(QgsApplication.qgisSettingsDirPath()) / "gbif_downloader" / "downloads"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _save_cached(data: dict) -> None:
    key = data.get("key", "")
    if not key:
        return
    key_dir = _cache_dir() / key
    key_dir.mkdir(exist_ok=True)
    (key_dir / "detail.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_all_cached() -> list[dict]:
    results = []
    cache = _cache_dir()
    for key_dir in sorted(cache.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not key_dir.is_dir():
            continue
        detail_file = key_dir / "detail.json"
        if not detail_file.exists():
            continue
        try:
            results.append(json.loads(detail_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    return results


def _sync_cache(remote_keys: set) -> None:
    """Remove cached entries whose keys are no longer in the remote list."""
    cache = _cache_dir()
    for key_dir in cache.iterdir():
        if key_dir.is_dir() and key_dir.name not in remote_keys:
            shutil.rmtree(key_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class _FetchAllWorker(QThread):
    finished = pyqtSignal(list)
    error    = pyqtSignal(str)

    def run(self):
        from .gbif_api import get_credentials, list_downloads
        username, password = get_credentials()
        if not username:
            self.error.emit("No GBIF credentials configured. Use the dropdown → Configure GBIF Credentials.")
            return
        try:
            self.finished.emit(list_downloads(username, password))
        except Exception as exc:
            self.error.emit(str(exc))


class _PollWorker(QThread):
    updated = pyqtSignal(str, dict)

    def __init__(self, keys: list):
        super().__init__()
        self._keys = keys

    def run(self):
        from .gbif_api import get_download
        for key in self._keys:
            try:
                self.updated.emit(key, get_download(key))
            except Exception:
                pass


class _DownloadWorker(QThread):
    """
    fmt:
      "zip" – download the raw ZIP and save to dest
      "map" – download ZIP, extract TSV to dest (no duckdb needed)
    """
    progress = pyqtSignal(int)
    finished = pyqtSignal(str, str)  # (saved path, fmt)
    error    = pyqtSignal(str)

    def __init__(self, url: str, dest: str, fmt: str):
        super().__init__()
        self._url  = url
        self._dest = dest
        self._fmt  = fmt

    def run(self):
        import urllib.request
        tmp_zip = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        tmp_path = tmp_zip.name
        tmp_zip.close()
        try:
            with urllib.request.urlopen(self._url) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                received = 0
                with open(tmp_path, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        received += len(chunk)
                        if total:
                            self.progress.emit(int(received * 100 / total))

            if self._fmt == "zip":
                shutil.move(tmp_path, self._dest)
                tmp_path = None
            elif self._fmt == "map":
                self._extract_tsv(tmp_path, self._dest)

            self.finished.emit(self._dest, self._fmt)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _extract_tsv(self, zip_path: str, dest: str):
        with zipfile.ZipFile(zip_path) as zf:
            name = _find_tsv(zf)
            with zf.open(name) as src, open(dest, "wb") as dst:
                dst.write(src.read())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_size(size_bytes) -> str:
    if not size_bytes:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _predicate_to_rows(pred) -> list[tuple[str, str, str, str]]:
    if not pred:
        return []
    if isinstance(pred, str):
        try:
            pred = json.loads(pred)
        except json.JSONDecodeError:
            return [("", "predicate", "", pred)]
    if not isinstance(pred, dict):
        return [("", "predicate", "", str(pred))]

    _OP = {
        "equals": "=",
        "in": "in",
        "greaterThan": ">",
        "lessThan": "<",
        "greaterThanOrEquals": ">=",
        "lessThanOrEquals": "<=",
        "like": "like",
    }

    def _collect(p, condition="AND"):
        t = p.get("type", "")
        if t == "and":
            rows = []
            for child in p.get("predicates", []):
                rows.extend(_collect(child, "AND"))
            return rows
        if t == "or":
            rows = []
            for child in p.get("predicates", []):
                rows.extend(_collect(child, "OR"))
            return rows
        if t == "not":
            return _collect(p.get("predicate", {}), "NOT")
        if t == "within":
            return [(condition, "GEOMETRY", "within", str(p.get("geometry", "")))]
        if t == "geoDistance":
            value = ", ".join(
                str(p.get(k, ""))
                for k in ("latitude", "longitude", "distance")
                if p.get(k, "") != ""
            )
            return [(condition, "GEOMETRY", "within distance", value)]
        if t in _OP:
            value = p.get("values", p.get("value", "?"))
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            return [(condition, p.get("key", "?"), _OP[t], str(value))]
        if t in ("isNull", "isNotNull"):
            operator = "IS NULL" if t == "isNull" else "IS NOT NULL"
            return [(condition, p.get("key", p.get("parameter", "?")), operator, "")]
        return [(condition, t or "predicate", "", str(p))]

    return _collect(pred)


# ---------------------------------------------------------------------------
# Filter item widget
# ---------------------------------------------------------------------------

def _memory_layer_type(geom: QgsGeometry) -> str:
    wkb_name = QgsWkbTypes.displayString(geom.wkbType())
    if wkb_name and wkb_name.lower() != "unknown":
        return wkb_name

    geom_type = geom.type()
    if geom_type == QgsWkbTypes.PointGeometry:
        return "Point"
    if geom_type == QgsWkbTypes.LineGeometry:
        return "LineString"
    if geom_type == QgsWkbTypes.PolygonGeometry:
        return "Polygon"
    return "Geometry"


class _FilterItemWidget(QWidget, FILTER_ITEM_FORM_CLASS):
    _COLORS = {
        "AND": "#446a8f",
        "OR": "#7a5a1f",
        "NOT": "#8b3f3f",
    }

    def __init__(
        self,
        condition: str,
        key: str,
        operator: str,
        value: str,
        download_key: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setupUi(self)
        self._download_key = download_key
        self._geometry_wkt = value if key == "GEOMETRY" and operator == "within" else ""

        condition = condition or "FILTER"
        self.condition_label.setText(condition)
        self.condition_frame.setStyleSheet(
            f"background-color: {self._COLORS.get(condition, '#66717f')};"
        )
        self.key_label.setText(key or "—")
        self.operator_label.setText(operator or " ")
        self.value_edit.setPlainText(value or "—")
        self.value_edit.document().setDocumentMargin(4)
        self.load_geometry_btn.setIcon(QgsApplication.getThemeIcon("/mActionAddOgrLayer.svg"))
        self.load_geometry_btn.setVisible(bool(self._geometry_wkt))
        self.load_geometry_btn.clicked.connect(self._load_geometry_to_map)

    def _load_geometry_to_map(self):
        geom = QgsGeometry.fromWkt(self._geometry_wkt)
        if geom.isNull() or geom.isEmpty():
            return

        name = f"{self._download_key or 'download'} geometry filter"
        layer = QgsVectorLayer(f"{_memory_layer_type(geom)}?crs=EPSG:4326", name, "memory")
        if not layer.isValid():
            return

        feature = QgsFeature()
        feature.setGeometry(geom)
        provider = layer.dataProvider()
        provider.addFeatures([feature])
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)


# ---------------------------------------------------------------------------
# Detail dialog
# ---------------------------------------------------------------------------

class _DetailDialog(DETAIL_BASE_CLASS, DETAIL_FORM_CLASS):
    def __init__(self, data: dict, save_callback=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self._save_callback = save_callback
        self._download_link = ""
        self.button_box.rejected.connect(self.reject)
        self.load_btn.setIcon(QgsApplication.getThemeIcon("/mActionAddOgrLayer.svg"))
        self.zip_btn.setIcon(QgsApplication.getThemeIcon("/mActionFileSave.svg"))
        self.load_btn.clicked.connect(lambda: self._save("map"))
        self.zip_btn.clicked.connect(lambda: self._save("zip"))
        self._populate(data)

    def _populate(self, data: dict):
        key = data.get("key", "")
        self._download_key = key
        self._download_link = data.get("downloadLink", "")
        self.setWindowTitle(f"Download Details — {key}")

        self.key_label.setText(
            f'<a href="https://www.gbif.org/occurrence/download/{key}">{key}</a>'
        )
        self.status_label.setText(data.get("status", "—"))
        self.format_label.setText((data.get("request") or {}).get("format", "—"))
        self.created_label.setText((data.get("created") or "—")[:19].replace("T", " "))

        total = data.get("totalRecords")
        self.records_label.setText(f"{int(total):,}" if total is not None else "—")

        datasets = data.get("numberDatasets")
        self.datasets_label.setText(f"{int(datasets):,}" if datasets is not None else "—")

        self.size_label.setText(_fmt_size(data.get("size")))

        doi = data.get("doi", "")
        if doi:
            url = doi if doi.startswith("http") else f"https://doi.org/{doi}"
            self.doi_label.setText(f'<a href="{url}">{doi}</a>')
        else:
            self.doi_label.setText("—")

        license_url = data.get("license", "")
        if license_url:
            self.license_label.setText(f'<a href="{license_url}">{license_url}</a>')
        else:
            self.license_label.setText("—")

        predicate = (data.get("request") or {}).get("predicate")
        self._populate_filter_list(predicate)

        has_link = bool(self._download_link) and data.get("status", "") == "SUCCEEDED"
        self.load_btn.setVisible(has_link)
        self.zip_btn.setVisible(has_link)

    def _save(self, fmt: str):
        if self._save_callback and self._download_link:
            self._save_callback(self._download_link, fmt, self._download_key)

    def _populate_filter_list(self, predicate: dict):
        rows = _predicate_to_rows(predicate)
        if not rows:
            rows = [("", "(no filter)", "", "")]

        self.filter_list.clear()
        for condition, key, operator, value in rows:
            widget = _FilterItemWidget(
                condition,
                key,
                operator,
                value,
                download_key=self._download_key,
                parent=self.filter_list,
            )
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 136))
            self.filter_list.addItem(item)
            self.filter_list.setItemWidget(item, widget)


# ---------------------------------------------------------------------------
# Vertical label
# ---------------------------------------------------------------------------

class _VerticalLabel(QLabel):
    """QLabel that renders its text rotated 90° counter-clockwise."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().windowText().color())
        painter.setFont(self.font())
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(-90)
        rect = QRect(-self.height() // 2, -self.width() // 2, self.height(), self.width())
        painter.drawText(rect, Qt.AlignCenter, self.text())

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.height(), s.width())

    def minimumSizeHint(self):
        s = super().minimumSizeHint()
        return QSize(s.height(), s.width())


# ---------------------------------------------------------------------------
# Download item widget
# ---------------------------------------------------------------------------

class _DownloadItemWidget(QWidget, ITEM_FORM_CLASS):
    def __init__(self, data: dict, tab: "DownloadsTab"):
        super().__init__()
        self.setupUi(self)
        self._key = data.get("key", "")
        self._tab = tab
        self._download_link = ""
        self._status = ""
        self._data = {}

        # Swap the plain status_label for a vertical one
        layout = self.status_frame.layout()
        layout.removeWidget(self.status_label)
        self.status_label.deleteLater()
        self.status_label = _VerticalLabel("", self.status_frame)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(
            "color: white; font-size: 10px; font-weight: bold; background: transparent;"
        )
        layout.addWidget(self.status_label)

        self.key_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard | Qt.LinksAccessibleByMouse
        )
        self.key_label.setOpenExternalLinks(True)

        self.load_btn.setIcon(QgsApplication.getThemeIcon("/mActionAddOgrLayer.svg"))
        self.zip_btn.setIcon(QgsApplication.getThemeIcon("/mActionFileSave.svg"))
        self.details_btn.setIcon(QgsApplication.getThemeIcon("/mActionIdentify.svg"))

        self.load_btn.clicked.connect(
            lambda: tab._save(self._download_link, "map", self._key)
        )
        self.zip_btn.clicked.connect(
            lambda: tab._save(self._download_link, "zip", self._key)
        )
        self.details_btn.clicked.connect(self._open_details)

        self.update_data(data)

    def status(self) -> str:
        return self._status

    def _open_details(self):
        dlg = _DetailDialog(self._data, save_callback=self._tab._save, parent=self)
        dlg.exec()

    def update_data(self, data: dict):
        self._data = data
        self._status = data.get("status", "")
        created = (data.get("created") or "")[:10]
        total = data.get("totalRecords")
        self._download_link = data.get("downloadLink", "")

        self.key_label.setText(
            f'<a href="https://www.gbif.org/occurrence/download/{self._key}">{self._key}</a>'
        )

        parts = []
        if created:
            parts.append(f"Created: {created}")
        if total is not None:
            parts.append(f"{int(total):,} records")
        if not parts and self._status:
            parts.append(self._status)
        self.info_label.setText(" · ".join(parts))

        erase_after = (data.get("eraseAfter") or "")[:10]
        expiry_text = ""
        if erase_after:
            try:
                delta = (datetime.date.fromisoformat(erase_after) - datetime.date.today()).days
                if delta > 0:
                    expiry_text = f"Will be deleted in {delta} days ({erase_after})"
                else:
                    expiry_text = f"Eligible for deletion (since {erase_after})"
            except ValueError:
                pass
        self.expiry_label.setText(expiry_text)
        self.expiry_label.setVisible(bool(expiry_text))

        color = _STATUS_CSS.get(self._status, "#aaaaaa")
        self.status_frame.setStyleSheet(f"background-color: {color};")
        self.status_label.setText(self._status)

        has_link = bool(self._download_link) and self._status == "SUCCEEDED"
        self.load_btn.setVisible(has_link)
        self.zip_btn.setVisible(has_link)


# ---------------------------------------------------------------------------
# Tab widget
# ---------------------------------------------------------------------------

class DownloadsTab(QWidget, FORM_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.status_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.refresh_btn.clicked.connect(self.refresh)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_MS)
        self._poll_timer.timeout.connect(self._poll_pending)

        self._items: dict[str, tuple[QListWidgetItem, _DownloadItemWidget]] = {}
        self._fetch_worker     = None
        self._poll_worker      = None
        self._download_workers = []

        # Populate from cache immediately, then kick off a background refresh
        for dl in _load_all_cached():
            self._insert_item(dl)
        if self._items:
            self.status_label.setText(f"{len(self._items)} download(s) (cached)")
            self.status_label.setStyleSheet("color: grey;")
            if any(w.status() in _PENDING for _, (_, w) in self._items.items()):
                self._poll_timer.start()
        self.refresh()

    # -- Public API -------------------------------------------------------

    def add_pending(self, key: str):
        data = {"key": key, "status": "SUBMITTED", "created": "", "totalRecords": None, "downloadLink": ""}
        _save_cached(data)
        self._insert_item(data, at_top=True)
        self.status_label.setText(f"Queued: {key}")
        self.status_label.setStyleSheet("color: green;")
        self._poll_pending()
        self._poll_timer.start()

    def refresh(self):
        self.refresh_btn.setEnabled(False)
        self.status_label.setText("Loading…")
        self.status_label.setStyleSheet("color: grey;")
        self._fetch_worker = _FetchAllWorker()
        self._fetch_worker.finished.connect(self._on_fetched)
        self._fetch_worker.error.connect(self._on_error)
        self._fetch_worker.start()

    # -- Polling ----------------------------------------------------------

    def _poll_pending(self):
        if self._poll_worker and self._poll_worker.isRunning():
            return
        keys = [k for k, (_, w) in self._items.items() if w.status() in _PENDING]
        if not keys:
            self._poll_timer.stop()
            return
        self._poll_worker = _PollWorker(keys)
        self._poll_worker.updated.connect(self._on_poll_result)
        self._poll_worker.start()

    def _on_poll_result(self, key: str, data: dict):
        _save_cached(data)
        if key not in self._items:
            return
        list_item, widget = self._items[key]
        widget.update_data(data)
        list_item.setSizeHint(widget.sizeHint())

    # -- List helpers -----------------------------------------------------

    def _insert_item(self, data: dict, at_top: bool = False):
        key = data.get("key", "")
        if key in self._items:
            _, widget = self._items[key]
            widget.update_data(data)
            return
        widget = _DownloadItemWidget(data, self)
        list_item = QListWidgetItem()
        list_item.setSizeHint(QSize(0, 125))
        if at_top:
            self.list_widget.insertItem(0, list_item)
        else:
            self.list_widget.addItem(list_item)
        self.list_widget.setItemWidget(list_item, widget)
        self._items[key] = (list_item, widget)

    def _on_fetched(self, downloads: list):
        self.refresh_btn.setEnabled(True)

        # Save all fetched entries and remove stale ones from cache
        remote_keys = {dl.get("key", "") for dl in downloads if dl.get("key")}
        for dl in downloads:
            _save_cached(dl)
        _sync_cache(remote_keys)

        # Rebuild the list from the authoritative remote data
        self.list_widget.clear()
        self._items.clear()
        for dl in downloads:
            self._insert_item(dl)

        count = len(downloads)
        self.status_label.setText(f"{count} download(s)")
        self.status_label.setStyleSheet("color: green;" if count else "color: grey;")
        if any(w.status() in _PENDING for _, (_, w) in self._items.items()):
            self._poll_timer.start()

    # -- Download ---------------------------------------------------------

    def _save(self, url: str, fmt: str, key: str = ""):
        if fmt == "map":
            dest = os.path.join(tempfile.gettempdir(), f"{key or 'gbif_download'}.tsv")
        elif fmt == "zip":
            dest, _ = QFileDialog.getSaveFileName(
                self, "Save ZIP", "", "ZIP files (*.zip);;All files (*)"
            )
            if not dest:
                return
        else:
            return

        self.status_label.setText("Downloading… 0%")
        self.status_label.setStyleSheet("color: grey;")

        w = _DownloadWorker(url, dest, fmt)
        w.progress.connect(lambda p: self.status_label.setText(f"Downloading… {p}%"))
        w.finished.connect(self._on_saved)
        w.error.connect(self._on_error)
        self._download_workers.append(w)
        w.start()

    def _on_saved(self, path: str, fmt: str):
        name = os.path.splitext(os.path.basename(path))[0]

        if fmt == "map":
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
                QgsProject.instance().addMapLayer(layer)
                self.status_label.setText(f"Layer added: {name}")
            else:
                self.status_label.setText(f"Saved but could not load layer: {path}")
        else:
            self.status_label.setText(f"Saved: {os.path.basename(path)}")

        self.status_label.setStyleSheet("color: green;")
        self._download_workers = [w for w in self._download_workers if w.isRunning()]

    def _on_error(self, message: str):
        self.refresh_btn.setEnabled(True)
        self.status_label.setText(f"Error: {message}")
        self.status_label.setStyleSheet("color: red;")
