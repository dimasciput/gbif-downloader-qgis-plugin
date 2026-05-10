import os

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QWidget,
    QMessageBox
)

from gbif_downloader.tab_action.taxon_filter import ScientificNameFilterSection

from .accordion import (
    CheckboxFilterSection,
    YearFilterSection,
)
from .country_filter import CountryFilterSection
from .geometry_filter import GeometryFilterSection
from .predicate import build_predicate, format_predicate_summary
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
        self._worker       = None
        self._download_format = "SIMPLE_CSV"

        self.status_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self._params_layout = self.formLayout

        self._params_layout.removeRow(self.species_edit)
        self._taxon_filter = ScientificNameFilterSection()
        self._params_layout.insertRow(0, self._taxon_filter)

        self._params_layout.removeRow(self.basis_combo)
        self._basis_section = CheckboxFilterSection(
            "Basis of record",
            [
                ("Observation",          "OBSERVATION"),
                ("Machine observation",  "MACHINE_OBSERVATION"),
                ("Human observation",    "HUMAN_OBSERVATION"),
                ("Material sample",      "MATERIAL_SAMPLE"),
                ("Material citation",    "MATERIAL_CITATION"),
                ("Preserved specimen",   "PRESERVED_SPECIMEN"),
                ("Fossil specimen",      "FOSSIL_SPECIMEN"),
                ("Living specimen",      "LIVING_SPECIMEN"),
                ("Occurrence",           "OCCURRENCE"),
            ],
            columns=2,
        )
        self._params_layout.insertRow(1, self._basis_section)

        self._country_section = CountryFilterSection()
        self._params_layout.insertRow(2, self._country_section)

        self._year_section = YearFilterSection()
        self._params_layout.insertRow(3, self._year_section)

        self._params_layout.removeRow(self.format_combo)
        self._params_layout.removeRow(self.polygon_row)
        self._geometry_section = GeometryFilterSection(self._iface)
        self._geometry_section.set_draw_handlers(self._toggle_draw, self._stop_draw)
        self._params_layout.insertRow(5, self._geometry_section)

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
        self._params_layout.insertRow(4, self._month_section)

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
        self._geometry_section.set_draw_active(True)
        self._geometry_section.set_draw_prompt()

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
        self._geometry_section.set_draw_cancelled()

    def _on_polygon_captured(self, geom):
        canvas = self._iface.mapCanvas()
        self._geometry_section.set_drawn_geometry(
            geom,
            canvas.mapSettings().destinationCrs(),
            self._polygon_tool.rubber_band(),
        )
        self._stop_draw()

    def cleanup(self):
        """Remove rubber band and map tool — call on plugin unload."""
        self._stop_draw()
        self._geometry_section.clear_geometry()

    def _get_month_filter(self) -> list[int]:
        checked = self._month_section.get_checked_values()
        return checked if 0 < len(checked) < 12 else []

    def _get_basis_filter(self) -> list[str]:
        checked = self._basis_section.get_checked_values()
        return checked if 0 < len(checked) < 9 else []

    def _get_country_filter(self) -> list[str]:
        return self._country_section.get_selected_countries()

    def _submit(self):
        has_filter = any([
            self._taxon_filter.get_selected_taxon(),
            self._get_country_filter(),
            self._get_basis_filter(),
            self._geometry_section.get_geometry_wkt(),
            self._year_section.get_year_predicate(),
            self._get_month_filter(),
        ])
        if not has_filter:
            QMessageBox.warning(
                self,
                "No Filters Applied",
                "Please apply at least one filter before submitting a download request.",
            )
            return

        predicate = build_predicate(
            taxon=self._taxon_filter.get_selected_taxon(),
            country=self._get_country_filter(),
            basis=self._get_basis_filter(),
            geometry_wkt=self._geometry_section.get_geometry_wkt(),
            year_predicates=self._year_section.get_year_predicate(),
            months=self._get_month_filter(),
        )
        fmt = self._download_format
        
        summary = format_predicate_summary(predicate)
        reply = QMessageBox.question(
            self,
            "Submit Download",
            f"Submit this GBIF download request?\n\nFilters:\n{summary}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

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
