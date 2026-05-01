import os
import tempfile
import zipfile

from qgis.core import QgsApplication, QgsProject, QgsVectorLayer
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QSize, QThread, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtWidgets import QFileDialog, QListWidgetItem, QWidget

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "gui", "downloads_tab.ui")
)
ITEM_FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "gui", "download_item.ui")
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
      "zip"        – download the raw ZIP and save to dest
      "map"        – download ZIP, extract TSV to dest (no duckdb needed)
      "geoparquet" – download ZIP, convert to GeoParquet via duckdb, save to dest
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
        import shutil
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
            elif self._fmt == "geoparquet":
                self._to_geoparquet(tmp_path, self._dest)

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

    def _to_geoparquet(self, zip_path: str, dest: str):
        try:
            import duckdb
        except ImportError:
            raise RuntimeError(
                "duckdb not found.\n"
                "Install it in the QGIS Python environment:\n"
                "  pip install duckdb"
            )
        tmp_tsv = tempfile.NamedTemporaryFile(suffix=".tsv", delete=False)
        tmp_tsv_path = tmp_tsv.name
        tmp_tsv.close()
        try:
            with zipfile.ZipFile(zip_path) as zf:
                name = _find_tsv(zf)
                with zf.open(name) as src, open(tmp_tsv_path, "wb") as dst:
                    dst.write(src.read())

            conn = duckdb.connect()
            conn.execute("INSTALL spatial; LOAD spatial;")
            conn.execute(f"""
                COPY (
                    SELECT *,
                        ST_Point(
                            TRY_CAST(decimallongitude AS DOUBLE),
                            TRY_CAST(decimallatitude  AS DOUBLE)
                        ) AS geometry
                    FROM read_csv(
                        '{tmp_tsv_path}',
                        delim='\t', header=true,
                        nullstr='', all_varchar=true
                    )
                    WHERE TRY_CAST(decimallatitude  AS DOUBLE) IS NOT NULL
                      AND TRY_CAST(decimallongitude AS DOUBLE) IS NOT NULL
                )
                TO '{dest}' (FORMAT PARQUET)
            """)
            conn.close()
        finally:
            os.unlink(tmp_tsv_path)


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


def _predicate_to_text(pred: dict) -> str:
    if not pred:
        return "(no filter)"
    _OP = {
        "equals": "=",
        "greaterThan": ">",
        "lessThan": "<",
        "greaterThanOrEquals": ">=",
        "lessThanOrEquals": "<=",
        "like": "like",
    }

    def _render(p, indent=0):
        pad = "  " * indent
        t = p.get("type", "")
        if t == "and":
            return "\n".join(_render(c, indent) for c in p.get("predicates", []))
        if t == "or":
            lines = [_render(c, indent + 1) for c in p.get("predicates", [])]
            return f"{pad}OR:\n" + "\n".join(lines)
        if t == "not":
            return f"{pad}NOT {_render(p.get('predicate', {}), indent)}"
        if t == "within":
            geom = p.get("geometry", "")
            if len(geom) > 80:
                geom = geom[:77] + "…"
            return f"{pad}GEOMETRY within {geom}"
        if t in _OP:
            return f"{pad}{p.get('key', '?')} {_OP[t]} {p.get('value', '?')}"
        if t in ("isNull", "isNotNull"):
            suffix = "IS NULL" if t == "isNull" else "IS NOT NULL"
            return f"{pad}{p.get('parameter', '?')} {suffix}"
        return f"{pad}{p}"

    return _render(pred)


# ---------------------------------------------------------------------------
# Detail dialog
# ---------------------------------------------------------------------------

class _DetailDialog(DETAIL_BASE_CLASS, DETAIL_FORM_CLASS):
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.button_box.rejected.connect(self.reject)
        self._populate(data)

    def _populate(self, data: dict):
        key = data.get("key", "")
        self.setWindowTitle(f"Download Details — {key}")

        self.key_label.setText(
            f'<a href="https://www.gbif.org/occurrence/download/{key}">{key}</a>'
        )
        self.status_label.setText(data.get("status", "—"))
        self.format_label.setText(
            (data.get("request") or {}).get("format", "—")
        )
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
        self.predicate_edit.setPlainText(
            _predicate_to_text(predicate) if predicate else "(no filter)"
        )

class _DownloadItemWidget(QWidget, ITEM_FORM_CLASS):
    def __init__(self, data: dict, tab: "DownloadsTab"):
        super().__init__()
        self.setupUi(self)
        self._key = data.get("key", "")
        self._tab = tab
        self._download_link = ""
        self._status = ""
        self._data = {}

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
        dlg = _DetailDialog(self._data, parent=self)
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

    # -- Public API -------------------------------------------------------

    def add_pending(self, key: str):
        data = {"key": key, "status": "SUBMITTED", "created": "", "totalRecords": None, "downloadLink": ""}
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
        list_item.setSizeHint(QSize(0, 110))
        if at_top:
            self.list_widget.insertItem(0, list_item)
        else:
            self.list_widget.addItem(list_item)
        self.list_widget.setItemWidget(list_item, widget)
        self._items[key] = (list_item, widget)

    def _on_fetched(self, downloads: list):
        self.refresh_btn.setEnabled(True)
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
        elif fmt == "geoparquet":
            dest, _ = QFileDialog.getSaveFileName(
                self, "Save GeoParquet", "", "GeoParquet (*.parquet);;All files (*)"
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
            self.status_label.setStyleSheet("color: green;")

        elif fmt == "geoparquet":
            layer = QgsVectorLayer(path, name, "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self.status_label.setText(f"Layer added: {name}")
            else:
                self.status_label.setText(f"Saved: {os.path.basename(path)}")
            self.status_label.setStyleSheet("color: green;")

        else:
            self.status_label.setText(f"Saved: {os.path.basename(path)}")
            self.status_label.setStyleSheet("color: green;")

        self._download_workers = [w for w in self._download_workers if w.isRunning()]

    def _on_error(self, message: str):
        self.refresh_btn.setEnabled(True)
        self.status_label.setText(f"Error: {message}")
        self.status_label.setStyleSheet("color: red;")
