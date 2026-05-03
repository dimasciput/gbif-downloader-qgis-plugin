import datetime
import os

from qgis.core import QgsWkbTypes
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QWidget

from .predicate import build_predicate, geom_to_wkt
from .polygon_tool import PolygonTool
from .worker import SubmitWorker

_GUI_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gui")
FORM_CLASS, _ = uic.loadUiType(os.path.join(_GUI_DIR, "action_tab.ui"))


class ActionTab(QWidget, FORM_CLASS):
    download_submitted = pyqtSignal(str)  # download key

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self._iface        = iface
        self._polygon_tool = None
        self._prev_tool    = None
        self._rubber_band  = None
        self._extent_wkt   = ""
        self._worker       = None

        self.status_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )

        self.country_combo.addItem("(any)", "")
        for code in ["AU", "BR", "CA", "DE", "ID", "IN", "MX", "US", "ZA"]:
            self.country_combo.addItem(code, code)

        current_year = datetime.date.today().year
        self.year_from.setRange(1750, current_year)
        self.year_from.setValue(current_year - 5)
        self.year_to.setRange(1750, current_year)
        self.year_to.setValue(current_year)

        self.basis_combo.addItem("(any)", "")
        for v in [
            "HUMAN_OBSERVATION",
            "MACHINE_OBSERVATION",
            "PRESERVED_SPECIMEN",
            "MATERIAL_CITATION",
            "OCCURRENCE",
        ]:
            self.basis_combo.addItem(v, v)

        self.format_combo.addItem("Simple CSV", "SIMPLE_CSV")
        self.format_combo.addItem("Darwin Core Archive", "DWCA")

        self.draw_btn.clicked.connect(self._toggle_draw)
        self.clear_polygon_btn.clicked.connect(self._clear_polygon)
        self.submit_btn.clicked.connect(self._submit)

    def _toggle_draw(self):
        canvas = self._iface.mapCanvas()
        if self._polygon_tool and canvas.mapTool() is self._polygon_tool:
            self._stop_draw()
        else:
            self._start_draw()

    def _start_draw(self):
        canvas = self._iface.mapCanvas()
        self._prev_tool    = canvas.mapTool()
        self._polygon_tool = PolygonTool(canvas)
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

    def _on_polygon_captured(self, geom):
        canvas = self._iface.mapCanvas()
        if self._rubber_band is not None:
            self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self._rubber_band = self._polygon_tool.rubber_band()
        self._extent_wkt  = geom_to_wkt(geom, canvas.mapSettings().destinationCrs())
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

    def _submit(self):
        year_from = self.year_from.value()
        year_to   = self.year_to.value()
        if year_from > year_to:
            self.status_label.setText("Year 'from' must be ≤ year 'to'.")
            self.status_label.setStyleSheet("color: red;")
            return

        predicate = build_predicate(
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

        self._worker = SubmitWorker(predicate, fmt, self.notify_check.isChecked())
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
