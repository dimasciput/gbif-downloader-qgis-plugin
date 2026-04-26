import datetime

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

_WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")


def _geom_to_wkt(geom: QgsGeometry, canvas_crs) -> str:
    if canvas_crs != _WGS84:
        g = QgsGeometry(geom)
        g.transform(QgsCoordinateTransform(canvas_crs, _WGS84, QgsProject.instance()))
        return g.asWkt()
    return geom.asWkt()


def _build_predicate(
    species: str,
    country: str,
    year_from: int,
    year_to: int,
    basis: str,
    geometry_wkt: str,
) -> dict:
    parts = [
        {"type": "equals", "key": "HAS_COORDINATE",      "value": "true"},
        {"type": "equals", "key": "HAS_GEOSPATIAL_ISSUE", "value": "false"},
        {"type": "greaterThanOrEquals", "key": "YEAR", "value": str(year_from)},
        {"type": "lessThanOrEquals",    "key": "YEAR", "value": str(year_to)},
    ]
    if species:
        parts.append({"type": "equals", "key": "SCIENTIFIC_NAME", "value": species})
    if country:
        parts.append({"type": "equals", "key": "COUNTRY", "value": country})
    if basis:
        parts.append({"type": "equals", "key": "BASIS_OF_RECORD", "value": basis})
    if geometry_wkt:
        parts.append({"type": "within", "geometry": geometry_wkt})

    return {"type": "and", "predicates": parts}


class _PolygonTool(QgsMapTool):
    """Click to add vertices, right-click to close and finish."""

    polygon_captured = pyqtSignal(object)  # QgsGeometry

    def __init__(self, canvas):
        super().__init__(canvas)
        self._vertices = []

        self._rb = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self._rb.setColor(QColor(255, 140, 0, 60))
        self._rb.setStrokeColor(QColor(255, 140, 0, 220))
        self._rb.setWidth(2)

        # Thin line previewing the edge from last vertex to cursor
        self._preview = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._preview.setStrokeColor(QColor(255, 140, 0, 160))
        self._preview.setWidth(1)
        self._preview.setLineStyle(Qt.DashLine)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pt = self.toMapCoordinates(event.pos())
            self._vertices.append(QgsPointXY(pt))
            self._redraw_polygon()
        elif event.button() == Qt.RightButton:
            self._finish()

    def canvasMoveEvent(self, event):
        if not self._vertices:
            return
        cursor = self.toMapCoordinates(event.pos())
        self._preview.reset(QgsWkbTypes.LineGeometry)
        self._preview.addPoint(self._vertices[-1])
        self._preview.addPoint(QgsPointXY(cursor))

    def _redraw_polygon(self):
        self._rb.reset(QgsWkbTypes.PolygonGeometry)
        for pt in self._vertices:
            self._rb.addPoint(pt)

    def _finish(self):
        self._preview.reset(QgsWkbTypes.LineGeometry)
        if len(self._vertices) >= 3:
            geom = QgsGeometry.fromPolygonXY([self._vertices])
            self.polygon_captured.emit(geom)
        else:
            self._rb.reset(QgsWkbTypes.PolygonGeometry)
        self.canvas().unsetMapTool(self)

    def rubber_band(self):
        return self._rb

    def deactivate(self):
        self._preview.reset(QgsWkbTypes.LineGeometry)
        super().deactivate()


class _SubmitWorker(QThread):
    submitted = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, predicate: dict, fmt: str, send_notification: bool):
        super().__init__()
        self._predicate = predicate
        self._fmt = fmt
        self._notify = send_notification

    def run(self):
        from .gbif_api import get_credentials, submit_predicate_download
        username, password = get_credentials()
        if not username:
            self.error.emit(
                "No GBIF credentials configured. "
                "Use the dropdown → Configure GBIF Credentials."
            )
            return
        try:
            key = submit_predicate_download(username, password, self._predicate, self._fmt, self._notify)
            self.submitted.emit(key)
        except Exception as exc:
            self.error.emit(str(exc))


class ActionTab(QWidget):
    download_submitted = pyqtSignal(str)  # download key

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self._iface = iface
        self._polygon_tool = None
        self._prev_tool = None
        self._rubber_band = None
        self._extent_wkt = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        params_group = QGroupBox("Query Parameters")
        form = QFormLayout(params_group)

        self.species_edit = QLineEdit()
        self.species_edit.setPlaceholderText("e.g. Panthera leo  (leave blank for all)")
        form.addRow("Species:", self.species_edit)

        self.country_combo = QComboBox()
        self.country_combo.addItem("(any)", "")
        for code in ["AU", "BR", "CA", "DE", "ID", "IN", "MX", "US", "ZA"]:
            self.country_combo.addItem(code, code)
        form.addRow("Country:", self.country_combo)

        current_year = datetime.date.today().year
        year_row = QWidget()
        year_layout = QHBoxLayout(year_row)
        year_layout.setContentsMargins(0, 0, 0, 0)
        self.year_from = QSpinBox()
        self.year_from.setRange(1750, current_year)
        self.year_from.setValue(current_year - 5)
        self.year_to = QSpinBox()
        self.year_to.setRange(1750, current_year)
        self.year_to.setValue(current_year)
        year_layout.addWidget(self.year_from)
        year_layout.addWidget(QLabel("to"))
        year_layout.addWidget(self.year_to)
        year_layout.addStretch()
        form.addRow("Year range:", year_row)

        self.basis_combo = QComboBox()
        self.basis_combo.addItem("(any)", "")
        for v in [
            "HUMAN_OBSERVATION",
            "MACHINE_OBSERVATION",
            "PRESERVED_SPECIMEN",
            "MATERIAL_CITATION",
            "OCCURRENCE",
        ]:
            self.basis_combo.addItem(v, v)
        form.addRow("Basis of record:", self.basis_combo)

        self.format_combo = QComboBox()
        self.format_combo.addItem("Simple CSV", "SIMPLE_CSV")
        self.format_combo.addItem("Darwin Core Archive", "DWCA")
        form.addRow("Download format:", self.format_combo)

        # Polygon row
        polygon_row = QWidget()
        polygon_layout = QHBoxLayout(polygon_row)
        polygon_layout.setContentsMargins(0, 0, 0, 0)
        self.draw_btn = QPushButton("Draw Polygon")
        self.draw_btn.setToolTip(
            "Click to add vertices, right-click to close the polygon"
        )
        self.draw_btn.clicked.connect(self._toggle_draw)
        self.clear_polygon_btn = QPushButton("Clear")
        self.clear_polygon_btn.setEnabled(False)
        self.clear_polygon_btn.clicked.connect(self._clear_polygon)
        polygon_layout.addWidget(self.draw_btn)
        polygon_layout.addWidget(self.clear_polygon_btn)
        polygon_layout.addStretch()
        form.addRow("Polygon:", polygon_row)

        layout.addWidget(params_group)

        bottom_row = QHBoxLayout()
        self.notify_check = QCheckBox("Send email notification")
        self.notify_check.setChecked(True)
        bottom_row.addWidget(self.notify_check)
        bottom_row.addStretch()
        self.submit_btn = QPushButton("Submit Download")
        self.submit_btn.clicked.connect(self._submit)
        bottom_row.addWidget(self.submit_btn)
        layout.addLayout(bottom_row)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        layout.addWidget(self.status_label)

        layout.addStretch()
        self._worker = None

    # -- Polygon drawing --------------------------------------------------

    def _toggle_draw(self):
        canvas = self._iface.mapCanvas()
        if self._polygon_tool and canvas.mapTool() is self._polygon_tool:
            self._stop_draw()
        else:
            self._start_draw()

    def _start_draw(self):
        canvas = self._iface.mapCanvas()
        self._prev_tool = canvas.mapTool()
        self._polygon_tool = _PolygonTool(canvas)
        self._polygon_tool.polygon_captured.connect(self._on_polygon_captured)
        self._polygon_tool.deactivated.connect(self._stop_draw)
        canvas.setMapTool(self._polygon_tool)
        self.draw_btn.setText("Cancel")
        self.status_label.setText(
            "Click to add vertices — right-click to close the polygon."
        )
        self.status_label.setStyleSheet("color: #555;")

    def _stop_draw(self):
        canvas = self._iface.mapCanvas()
        if self._polygon_tool:
            try:
                self._polygon_tool.polygon_captured.disconnect()
                self._polygon_tool.deactivated.disconnect()
            except Exception:
                pass
            self._polygon_tool = None
        if self._prev_tool:
            canvas.setMapTool(self._prev_tool)
            self._prev_tool = None
        self.draw_btn.setText("Draw Polygon")
        if not self._extent_wkt:
            self.status_label.setText("")
            self.status_label.setStyleSheet("")

    def _on_polygon_captured(self, geom: QgsGeometry):
        canvas = self._iface.mapCanvas()

        # Keep the rubber band from the tool as the persistent one
        if self._rubber_band is not None:
            self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self._rubber_band = self._polygon_tool.rubber_band()

        self._extent_wkt = _geom_to_wkt(geom, canvas.mapSettings().destinationCrs())
        self.clear_polygon_btn.setEnabled(True)
        self.status_label.setText("")
        self.status_label.setStyleSheet("")
        self._stop_draw()

    def _clear_polygon(self):
        if self._rubber_band is not None:
            self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)
            self._rubber_band = None
        self._extent_wkt = ""
        self.clear_polygon_btn.setEnabled(False)

    def cleanup(self):
        """Remove rubber band and map tool — call on plugin unload."""
        self._stop_draw()
        self._clear_polygon()

    # -- Submit -----------------------------------------------------------

    def _submit(self):
        year_from = self.year_from.value()
        year_to = self.year_to.value()
        if year_from > year_to:
            self.status_label.setText("Year 'from' must be ≤ year 'to'.")
            self.status_label.setStyleSheet("color: red;")
            return

        predicate = _build_predicate(
            species=self.species_edit.text().strip(),
            country=self.country_combo.currentData(),
            year_from=year_from,
            year_to=year_to,
            basis=self.basis_combo.currentData(),
            geometry_wkt=self._extent_wkt,
        )
        fmt = self.format_combo.currentData()

        self.submit_btn.setEnabled(False)
        self.status_label.setText("Submitting…")
        self.status_label.setStyleSheet("color: grey;")

        self._worker = _SubmitWorker(predicate, fmt, self.notify_check.isChecked())
        self._worker.submitted.connect(self._on_submitted)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_submitted(self, key: str):
        self.submit_btn.setEnabled(True)
        self.status_label.setText(f"Queued ✓  Download key: {key}")
        self.status_label.setStyleSheet("color: green;")
        self.download_submitted.emit(key)

    def _on_error(self, message: str):
        self.submit_btn.setEnabled(True)
        self.status_label.setText(f"Error: {message}")
        self.status_label.setStyleSheet("color: red;")
