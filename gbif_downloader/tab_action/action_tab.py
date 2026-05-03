import os

from qgis.core import QgsWkbTypes
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QWidget

from .accordion import CheckboxFilterSection, YearFilterSection
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

        self._year_section = YearFilterSection()
        self.params_group.layout().insertRow(2, self._year_section)

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

        self._month_section = CheckboxFilterSection(
            "Month",
            [
                ("Jan", 1), ("Feb", 2),  ("Mar", 3),  ("Apr", 4),
                ("May", 5), ("Jun", 6),  ("Jul", 7),  ("Aug", 8),
                ("Sep", 9), ("Oct", 10), ("Nov", 11), ("Dec", 12),
            ],
            columns=4,
        )
        self.params_group.layout().insertRow(3, self._month_section)

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

    def _get_month_filter(self) -> list[int]:
        checked = self._month_section.get_checked_values()
        return checked if 0 < len(checked) < 12 else []

    def _submit(self):
        predicate = build_predicate(
            species=self.species_edit.text().strip(),
            country=self.country_combo.currentData(),
            basis=self.basis_combo.currentData(),
            geometry_wkt=self._extent_wkt,
            year_predicates=self._year_section.get_year_predicate(),
            months=self._get_month_filter(),
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
