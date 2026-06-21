import os

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QTimer, QUrl, QUrlQuery, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .accordion import (
    CheckboxFilterSection,
    NumericRangeFilterSection,
    YearFilterSection,
)
from .country_filter import CountryFilterSection
from .geometry_filter import GeometryFilterSection
from .predicate import build_predicate, format_predicate_summary, predicate_to_search_params
from .polygon_tool import PolygonTool
from .taxon_filter import HigherTaxonFilterSection
from .dataset_filter import DatasetFilterSection
from .institution_filter import InstitutionFilterSection
from .scientific_name_filter import ScientificNameFilterSection
from .worker import SubmitWorker

_GUI_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gui")
FORM_CLASS, _ = uic.loadUiType(os.path.join(_GUI_DIR, "action_tab.ui"))


class DisclaimerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Before You Download")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        agreement_title = QLabel("<b>Data Use Agreement</b>")
        layout.addWidget(agreement_title)

        agreement_body = QLabel(
            "By downloading this data, you acknowledge that you have read and accepted "
            "the terms of the data use agreement."
        )
        agreement_body.setWordWrap(True)
        layout.addWidget(agreement_body)

        self._cb_agreement = QCheckBox(
            "I have read and accept the data use agreement."
        )
        layout.addWidget(self._cb_agreement)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        citation_title = QLabel("<b>Data Citation</b>")
        layout.addWidget(citation_title)

        citation_body = QLabel(
            "By downloading this data, you agree to:\n"
            "•  follow the citation guidelines for GBIF-mediated data\n"
            "•  always include the DOI assigned to the download when citing or "
            "referring to the data in any publication"
        )
        citation_body.setWordWrap(True)
        layout.addWidget(citation_body)

        self._cb_citation = QCheckBox(
            "I agree to the citation requirements."
        )
        layout.addWidget(self._cb_citation)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._ok_btn = self._buttons.button(QDialogButtonBox.Ok)
        self._ok_btn.setEnabled(False)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._cb_agreement.toggled.connect(self._update_ok)
        self._cb_citation.toggled.connect(self._update_ok)

    def _update_ok(self):
        self._ok_btn.setEnabled(
            self._cb_agreement.isChecked() and self._cb_citation.isChecked()
        )


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

        self._clear_all_btn = QPushButton("Clear All Filters")
        self.bottomLayout.insertWidget(2, self._clear_all_btn)
        self._clear_all_btn.clicked.connect(self._clear_all_filters)

        self._params_layout = self.formLayout

        self._params_layout.removeRow(self.species_edit)
        self._taxon_filter = ScientificNameFilterSection()
        self._params_layout.insertRow(0, self._taxon_filter)

        self._higher_taxon_section = HigherTaxonFilterSection()
        self._params_layout.insertRow(1, self._higher_taxon_section)

        self._dataset_section = DatasetFilterSection()
        self._params_layout.insertRow(2, self._dataset_section)

        self._institution_section = InstitutionFilterSection()
        self._params_layout.insertRow(3, self._institution_section)

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
            description="Basis of record, as defined in our BasisOfRecord vocabulary.",
        )
        self._params_layout.insertRow(4, self._basis_section)

        self._country_section = CountryFilterSection()
        self._params_layout.insertRow(5, self._country_section)

        self._year_section = YearFilterSection()
        self._params_layout.insertRow(6, self._year_section)

        self._coord_uncertainty_section = NumericRangeFilterSection(
            "Coordinate uncertainty",
            "COORDINATE_UNCERTAINTY_IN_METERS",
            min_val=0,
            max_val=200000,
            step=100,
            default_from=0,
            default_to=1000,
            description=(
                "The horizontal distance (in metres) from the given decimalLatitude and "
                "decimalLongitude describing the smallest circle containing the whole of "
                "the Location. Supports range queries."
            ),
        )
        self._params_layout.insertRow(7, self._coord_uncertainty_section)

        self._elevation_section = NumericRangeFilterSection(
            "Elevation",
            "ELEVATION",
            min_val=-500,
            max_val=8849,
            step=10,
            default_from=0,
            default_to=1000,
            description="Elevation (altitude) in metres above sea level. Supports range queries.",
        )
        self._params_layout.insertRow(8, self._elevation_section)

        self._month_section = CheckboxFilterSection(
            "Month",
            [
                ("Jan", 1), ("Feb", 2),  ("Mar", 3),  ("Apr", 4),
                ("May", 5), ("Jun", 6),  ("Jul", 7),  ("Aug", 8),
                ("Sep", 9), ("Oct", 10), ("Nov", 11), ("Dec", 12),
            ],
            columns=4,
            description="The ordinal month in which the event occurred.",
        )
        self._params_layout.insertRow(9, self._month_section)

        self._conservation_section = CheckboxFilterSection(
            "Conservation status (IUCN)",
            [
                ("Extinct",                  "EX"),
                ("Extinct in the Wild",       "EW"),
                ("Critically Endangered",     "CR"),
                ("Endangered",                "EN"),
                ("Vulnerable",                "VU"),
                ("Near Threatened",           "NT"),
                ("Least Concern",             "LC"),
                ("Data Deficient",            "DD"),
                ("Not Evaluated",             "NE"),
            ],
            columns=2,
            description="The IUCN Red List Category of the taxon at the time of the occurrence.",
        )
        self._params_layout.insertRow(10, self._conservation_section)

        self._params_layout.removeRow(self.format_combo)
        self._params_layout.removeRow(self.polygon_row)
        self._geometry_section = GeometryFilterSection(self._iface)
        self._geometry_section.set_draw_handlers(self._toggle_draw, self._stop_draw)
        self._params_layout.insertRow(11, self._geometry_section)

        self._estimate_manager = QNetworkAccessManager(self)
        self._estimate_reply = None

        self._estimate_timer = QTimer(self)
        self._estimate_timer.setSingleShot(True)
        self._estimate_timer.setInterval(600)
        self._estimate_timer.timeout.connect(self._estimate)

        for section in (
            self._taxon_filter,
            self._higher_taxon_section,
            self._dataset_section,
            self._institution_section,
            self._basis_section,
            self._country_section,
            self._year_section,
            self._coord_uncertainty_section,
            self._elevation_section,
            self._month_section,
            self._conservation_section,
            self._geometry_section,
        ):
            section.filter_changed.connect(self._on_filter_changed)

        self.submit_btn.clicked.connect(self._submit)

        self._credentials_btn = QPushButton("Configure GBIF Credentials…")
        self._credentials_btn.clicked.connect(self._open_credentials_dialog)
        self._credentials_btn.hide()
        idx = self.verticalLayout.indexOf(self.status_label)
        self.verticalLayout.insertWidget(idx + 1, self._credentials_btn)

        self._warn_if_no_credentials()

    def _warn_if_no_credentials(self):
        from ..gbif_api import get_credentials
        username, _ = get_credentials()
        if not username:
            self.status_label.setText(
                "No GBIF credentials configured.\n"
                "Use the dropdown → Configure GBIF Credentials."
            )
            self.status_label.setStyleSheet("color: orange;")
            self._credentials_btn.show()
        else:
            self._credentials_btn.hide()
            self.status_label.setText("")
            self.status_label.setStyleSheet("")

    def _open_credentials_dialog(self):
        from ..credentials_dialog import CredentialsDialog
        dlg = CredentialsDialog(self)
        dlg.exec()
        self._warn_if_no_credentials()

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
        """Remove rubber band and map tool - call on plugin unload."""
        self._stop_draw()
        self._geometry_section.clear_geometry()

    def _get_month_filter(self) -> list[int]:
        checked = self._month_section.get_checked_values()
        return checked if 0 < len(checked) < 12 else []

    def _get_basis_filter(self) -> list[str]:
        checked = self._basis_section.get_checked_values()
        return checked if 0 < len(checked) < 9 else []

    def _get_conservation_filter(self) -> list[str]:
        checked = self._conservation_section.get_checked_values()
        return checked if 0 < len(checked) < 9 else []

    def _get_country_filter(self) -> list[str]:
        return self._country_section.get_selected_countries()

    def _clear_all_filters(self):
        self._taxon_filter._clear()
        self._higher_taxon_section._clear()
        self._dataset_section._clear()
        self._institution_section._clear()
        self._basis_section._clear_all()
        self._country_section._clear()
        self._year_section._clear()
        self._coord_uncertainty_section._clear()
        self._elevation_section._clear()
        self._month_section._clear_all()
        self._conservation_section._clear_all()
        self._stop_draw()
        self._geometry_section.clear_geometry()

    def _get_higher_taxon_filter(self):
        return self._higher_taxon_section.get_selected()

    def _on_filter_changed(self):
        self._estimate_timer.start()

    def _estimate(self):
        predicate = build_predicate(
            taxon=self._taxon_filter.get_selected(),
            higher_taxon=self._get_higher_taxon_filter(),
            dataset=self._dataset_section.get_selected(),
            institution=self._institution_section.get_selected(),
            country=self._get_country_filter(),
            basis=self._get_basis_filter(),
            geometry_wkt=self._geometry_section.get_geometry_wkt(),
            year_predicates=self._year_section.get_year_predicate(),
            coordinate_uncertainty_predicates=self._coord_uncertainty_section.get_predicate(),
            elevation_predicates=self._elevation_section.get_predicate(),
            months=self._get_month_filter(),
            conservation_statuses=self._get_conservation_filter(),
        )

        if self._estimate_reply and self._estimate_reply.isRunning():
            self._estimate_reply.abort()

        url = QUrl("https://api.gbif.org/v1/occurrence/search")
        query = QUrlQuery()
        query.addQueryItem("limit", "0")
        for key, value in predicate_to_search_params(predicate):
            query.addQueryItem(key, value)
        url.setQuery(query)

        request = QNetworkRequest(url)
        request.setRawHeader(b"Accept", b"application/json")

        self.status_label.setText("Counting…")
        self.status_label.setStyleSheet("color: grey;")

        self._estimate_reply = self._estimate_manager.get(request)
        self._estimate_reply.finished.connect(self._on_estimate_reply)

    def _on_estimate_reply(self):
        reply = self._estimate_reply
        self._estimate_reply = None
        try:
            if reply.error() != QNetworkReply.NoError:
                self.status_label.setText("Estimate failed - network error.")
                self.status_label.setStyleSheet("color: red;")
                return
            import json
            data = json.loads(bytes(reply.readAll()).decode("utf-8"))
            count = data.get("count", 0)
            size_gb = count * 112 / 1_000_000_000
            if size_gb >= 1:
                size_str = f"~{size_gb:.1f} GB"
            else:
                size_str = f"~{size_gb * 1000:.0f} MB"
            self.status_label.setText(f"~{count:,} occurrences  •  {size_str}")
            self.status_label.setStyleSheet("color: grey;")
        except Exception:
            self.status_label.setText("Estimate failed - unexpected response.")
            self.status_label.setStyleSheet("color: red;")
        finally:
            reply.deleteLater()

    def _submit(self):
        has_filter = any([
            self._taxon_filter.get_selected(),
            self._get_higher_taxon_filter(),
            self._dataset_section.get_selected(),
            self._institution_section.get_selected(),
            self._get_country_filter(),
            self._get_basis_filter(),
            self._geometry_section.get_geometry_wkt(),
            self._year_section.get_year_predicate(),
            self._coord_uncertainty_section.get_predicate(),
            self._elevation_section.get_predicate(),
            self._get_month_filter(),
            self._get_conservation_filter(),
        ])
        if not has_filter:
            QMessageBox.warning(
                self,
                "No Filters Applied",
                "Please apply at least one filter before submitting a download request.",
            )
            return

        if DisclaimerDialog(self).exec() != QDialog.Accepted:
            return

        predicate = build_predicate(
            taxon=self._taxon_filter.get_selected(),
            higher_taxon=self._get_higher_taxon_filter(),
            dataset=self._dataset_section.get_selected(),
            institution=self._institution_section.get_selected(),
            country=self._get_country_filter(),
            basis=self._get_basis_filter(),
            geometry_wkt=self._geometry_section.get_geometry_wkt(),
            year_predicates=self._year_section.get_year_predicate(),
            coordinate_uncertainty_predicates=self._coord_uncertainty_section.get_predicate(),
            elevation_predicates=self._elevation_section.get_predicate(),
            months=self._get_month_filter(),
            conservation_statuses=self._get_conservation_filter(),
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
        self._credentials_btn.hide()
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
        self._clear_all_filters()

    def _on_error(self, message: str):
        self.submit_btn.setEnabled(True)
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: red;")
