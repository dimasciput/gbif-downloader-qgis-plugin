import os
import tempfile
import zipfile

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_POLL_MS = 30_000
_PENDING = {"PREPARING", "RUNNING", "SUBMITTED"}
_COLOURS = {
    "SUCCEEDED": Qt.darkGreen,
    "RUNNING":   Qt.darkBlue,
    "PREPARING": Qt.darkCyan,
    "SUBMITTED": Qt.darkCyan,
    "FAILED":    Qt.red,
    "KILLED":    Qt.darkRed,
    "CANCELLED": Qt.gray,
}
_TSV_SKIP = {"citation", "rights", "metadata", "multimedia", "verbatim"}


def _find_tsv(zf: zipfile.ZipFile) -> str:
    """Return the name of the main data file inside the ZIP."""
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
    progress = pyqtSignal(int)   # 0-100
    finished = pyqtSignal(str, str)  # (saved path, fmt)
    error    = pyqtSignal(str)

    def __init__(self, url: str, dest: str, fmt: str):
        super().__init__()
        self._url  = url
        self._dest = dest
        self._fmt  = fmt

    def run(self):
        import urllib.request, shutil
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
# Tab widget
# ---------------------------------------------------------------------------

class DownloadsTab(QWidget):
    COLUMNS = ["Key", "Status", "Created", "Records", "Actions"]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        top_row = QHBoxLayout()
        self.status_label = QLabel("Not connected")
        self.status_label.setStyleSheet("color: grey;")
        self.status_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        top_row.addWidget(self.status_label)
        top_row.addStretch()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        top_row.addWidget(self.refresh_btn)
        layout.addLayout(top_row)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        for col in range(4):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(30)
        layout.addWidget(self.table)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_MS)
        self._poll_timer.timeout.connect(self._poll_pending)

        self._fetch_worker     = None
        self._poll_worker      = None
        self._download_workers = []

    # -- Public API -------------------------------------------------------

    def add_pending(self, key: str):
        self.table.insertRow(0)
        self.table.setItem(0, 0, QTableWidgetItem(key))
        si = QTableWidgetItem("SUBMITTED")
        self._colour(si)
        self.table.setItem(0, 1, si)
        self.table.setItem(0, 2, QTableWidgetItem(""))
        self.table.setItem(0, 3, QTableWidgetItem(""))
        self.table.setCellWidget(0, 4, QWidget())
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
        keys = [
            self.table.item(r, 0).text()
            for r in range(self.table.rowCount())
            if self.table.item(r, 1) and self.table.item(r, 1).text() in _PENDING
            and self.table.item(r, 0)
        ]
        if not keys:
            self._poll_timer.stop()
            return
        self._poll_worker = _PollWorker(keys)
        self._poll_worker.updated.connect(self._on_poll_result)
        self._poll_worker.start()

    def _on_poll_result(self, key: str, data: dict):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text() == key:
                self._fill_row(row, data)
                break

    # -- Table helpers ----------------------------------------------------

    def _on_fetched(self, downloads: list):
        self.refresh_btn.setEnabled(True)
        self.table.setRowCount(0)
        for dl in downloads:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._fill_row(row, dl)
        count = len(downloads)
        self.status_label.setText(f"{count} download(s)")
        self.status_label.setStyleSheet("color: green;" if count else "color: grey;")
        if any(
            self.table.item(r, 1) and self.table.item(r, 1).text() in _PENDING
            for r in range(self.table.rowCount())
        ):
            self._poll_timer.start()

    def _fill_row(self, row: int, data: dict):
        key           = data.get("key", "")
        status        = data.get("status", "")
        created       = (data.get("created") or "")[:10]
        total         = str(data.get("totalRecords") or "")
        download_link = data.get("downloadLink", "")

        def _set(col, text):
            item = self.table.item(row, col)
            if item:
                item.setText(text)
            else:
                self.table.setItem(row, col, QTableWidgetItem(text))

        _set(0, key)
        _set(2, created)
        _set(3, total)

        si = self.table.item(row, 1)
        if si:
            si.setText(status)
        else:
            si = QTableWidgetItem(status)
            self.table.setItem(row, 1, si)
        self._colour(si)

        if status == "SUCCEEDED" and download_link:
            if not isinstance(self.table.cellWidget(row, 4), _ActionsWidget):
                self.table.setCellWidget(row, 4, _ActionsWidget(download_link, key, self))
        elif not self.table.cellWidget(row, 4):
            self.table.setCellWidget(row, 4, QWidget())

    def _colour(self, item: QTableWidgetItem):
        item.setForeground(_COLOURS.get(item.text(), Qt.black))

    # -- Download ---------------------------------------------------------

    def _save(self, url: str, fmt: str, key: str = ""):
        if fmt == "map":
            name = key or "gbif_download"
            dest = os.path.join(tempfile.gettempdir(), f"{name}.tsv")
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


class _ActionsWidget(QWidget):
    def __init__(self, download_link: str, key: str, tab: DownloadsTab):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        btn_map = QPushButton("Load to Map")
        btn_map.setFixedHeight(22)
        btn_map.setToolTip("Download and add as a QGIS layer (no duckdb required)")
        btn_map.clicked.connect(lambda: tab._save(download_link, fmt="map", key=key))
        layout.addWidget(btn_map)

        btn_zip = QPushButton("ZIP")
        btn_zip.setFixedHeight(22)
        btn_zip.setToolTip("Save raw ZIP file")
        btn_zip.clicked.connect(lambda: tab._save(download_link, fmt="zip", key=key))
        layout.addWidget(btn_zip)

        btn_parquet = QPushButton("GeoParquet ⚗")
        btn_parquet.setFixedHeight(22)
        btn_parquet.setToolTip("Convert to GeoParquet via DuckDB and add as layer (requires duckdb)")
        btn_parquet.clicked.connect(lambda: tab._save(download_link, fmt="geoparquet", key=key))
        layout.addWidget(btn_parquet)

        layout.addStretch()
