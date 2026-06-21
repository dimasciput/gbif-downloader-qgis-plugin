import datetime
import os

from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QRect, QSize
from qgis.PyQt.QtGui import QPainter
from qgis.PyQt.QtWidgets import QLabel, QListWidgetItem, QWidget

from .helpers import _STATUS_CSS, PENDING, _fmt_size, _predicate_to_rows, _memory_layer_type

_GUI_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gui")

ITEM_FORM_CLASS, _          = uic.loadUiType(os.path.join(_GUI_DIR, "download_item.ui"))
FILTER_ITEM_FORM_CLASS, _   = uic.loadUiType(os.path.join(_GUI_DIR, "filter_item.ui"))
DETAIL_FORM_CLASS, DETAIL_BASE_CLASS = uic.loadUiType(
    os.path.join(_GUI_DIR, "download_detail_dialog.ui")
)


class VerticalLabel(QLabel):
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


class FilterItemWidget(QWidget, FILTER_ITEM_FORM_CLASS):
    _COLORS = {
        "AND": "#446a8f",
        "OR":  "#7a5a1f",
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
        self._download_key  = download_key
        self._geometry_wkt  = value if key == "GEOMETRY" and operator == "within" else ""

        condition = condition or "FILTER"
        self.condition_label.setText(condition)
        self.condition_frame.setStyleSheet(
            f"background-color: {self._COLORS.get(condition, '#66717f')};"
        )
        self.key_label.setText(key or "-")
        self.operator_label.setText(operator or " ")
        self.value_edit.setPlainText(value or "-")
        self.value_edit.document().setDocumentMargin(4)
        self.load_geometry_btn.setIcon(QgsApplication.getThemeIcon("/mActionAddOgrLayer.svg"))
        self.load_geometry_btn.setVisible(bool(self._geometry_wkt))
        self.load_geometry_btn.clicked.connect(self._load_geometry_to_map)

    def _load_geometry_to_map(self):
        geom = QgsGeometry.fromWkt(self._geometry_wkt)
        if geom.isNull() or geom.isEmpty():
            return
        name    = f"{self._download_key or 'download'} geometry filter"
        layer   = QgsVectorLayer(f"{_memory_layer_type(geom)}?crs=EPSG:4326", name, "memory")
        if not layer.isValid():
            return
        feature = QgsFeature()
        feature.setGeometry(geom)
        provider = layer.dataProvider()
        provider.addFeatures([feature])
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)


class DetailDialog(DETAIL_BASE_CLASS, DETAIL_FORM_CLASS):
    def __init__(self, data: dict, save_callback=None, report_callback=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self._save_callback   = save_callback
        self._report_callback = report_callback
        self._download_link   = ""
        self._download_key    = ""
        self.button_box.rejected.connect(self.reject)
        self.load_btn.setIcon(QgsApplication.getThemeIcon("/mActionAddOgrLayer.svg"))
        self.zip_btn.setIcon(QgsApplication.getThemeIcon("/mActionFileSave.svg"))
        self.report_btn.setIcon(QgsApplication.getThemeIcon("/mActionSaveAsPDF.svg"))
        self.load_btn.clicked.connect(lambda: self._save("map"))
        self.zip_btn.clicked.connect(lambda: self._save("zip"))
        self.report_btn.clicked.connect(self._do_report)
        self._populate(data)

    def _populate(self, data: dict):
        key = data.get("key", "")
        self._download_key  = key
        self._download_link = data.get("downloadLink", "")
        self.setWindowTitle(f"Download Details - {key}")

        self.key_label.setText(
            f'<a href="https://www.gbif.org/occurrence/download/{key}">{key}</a>'
        )
        self.status_label.setText(data.get("status", "-"))
        self.format_label.setText((data.get("request") or {}).get("format", "-"))
        self.created_label.setText((data.get("created") or "-")[:19].replace("T", " "))

        total = data.get("totalRecords")
        self.records_label.setText(f"{int(total):,}" if total is not None else "-")

        datasets = data.get("numberDatasets")
        self.datasets_label.setText(f"{int(datasets):,}" if datasets is not None else "-")

        self.size_label.setText(_fmt_size(data.get("size")))

        doi = data.get("doi", "")
        doi_suffix = ""
        if doi:
            doi_suffix = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
            doi_url = f"https://doi.org/{doi_suffix}"
            self.doi_label.setText(f'<a href="{doi_url}">{doi}</a>')
        else:
            self.doi_label.setText("-")

        license_url = data.get("license", "")
        if license_url:
            self.license_label.setText(f'<a href="{license_url}">{license_url}</a>')
        else:
            self.license_label.setText("-")

        if doi_suffix:
            from qgis.PyQt.QtWidgets import QLabel
            date_str = datetime.date.today().strftime("%-d %B %Y")
            citation_text = (
                f"GBIF.org ({date_str}) GBIF Occurrence Download "
                f"https://doi.org/{doi_suffix}"
            )
            cite_label = QLabel(citation_text)
            cite_label.setWordWrap(True)
            cite_label.setTextInteractionFlags(
                Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
            )
            cite_label.setStyleSheet("font-size: 12px;")

            ris_url  = f"https://data.crosscite.org/application/x-research-info-systems/{doi_suffix}"
            bib_url  = f"https://data.crosscite.org/application/x-bibtex/{doi_suffix}"
            export_label = QLabel(
                f'<a href="{ris_url}">Download RIS</a>'
                f'&nbsp;&nbsp;·&nbsp;&nbsp;'
                f'<a href="{bib_url}">Download BibTeX</a>'
            )
            export_label.setOpenExternalLinks(True)

            self.formLayout_citation.addRow("Cite as:", cite_label)
            self.formLayout_citation.addRow("Export:", export_label)

        predicate = (data.get("request") or {}).get("predicate")
        self._populate_filter_list(predicate)

        has_link = bool(self._download_link) and data.get("status", "") == "SUCCEEDED"
        self.load_btn.setVisible(has_link)
        self.zip_btn.setVisible(has_link)
        self.report_btn.setVisible(has_link)

    def _save(self, fmt: str):
        if self._save_callback and self._download_link:
            self._save_callback(self._download_link, fmt, self._download_key)

    def _do_report(self):
        if self._report_callback:
            self._report_callback()

    def _populate_filter_list(self, predicate):
        rows = _predicate_to_rows(predicate)
        if not rows:
            rows = [("", "(no filter)", "", "")]
        self.filter_list.clear()
        for condition, key, operator, value in rows:
            widget = FilterItemWidget(
                condition, key, operator, value,
                download_key=self._download_key,
                parent=self.filter_list,
            )
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 136))
            self.filter_list.addItem(item)
            self.filter_list.setItemWidget(item, widget)


class DownloadItemWidget(QWidget, ITEM_FORM_CLASS):
    def __init__(self, data: dict, tab):
        super().__init__()
        self.setupUi(self)
        self._key           = data.get("key", "")
        self._tab           = tab
        self._download_link = ""
        self._status        = ""
        self._data          = {}

        # Swap the plain status_label for a vertical one
        layout = self.status_frame.layout()
        layout.removeWidget(self.status_label)
        self.status_label.deleteLater()
        self.status_label = VerticalLabel("", self.status_frame)
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
        self.details_btn.setIcon(QgsApplication.getThemeIcon("/mActionFormView.svg"))
        self.report_btn.setIcon(QgsApplication.getThemeIcon("/mActionSaveAsPDF.svg"))
        self.load_btn.clicked.connect(lambda: tab._save(self._download_link, "map", self._key))
        self.zip_btn.clicked.connect(lambda: tab._save(self._download_link, "zip", self._key))
        self.details_btn.clicked.connect(self._open_details)
        self.report_btn.clicked.connect(lambda: tab._generate_report(self._download_link, self._key))

        self.update_data(data)

    def status(self) -> str:
        return self._status

    def _open_details(self):
        key = self._key
        url = self._download_link
        dlg = DetailDialog(
            self._data,
            save_callback=self._tab._save,
            report_callback=lambda: self._tab._generate_report(url, key),
            parent=self,
        )
        dlg.exec()

    def update_data(self, data: dict):
        self._data          = data
        self._status        = data.get("status", "")
        created             = (data.get("created") or "")[:10]
        total               = data.get("totalRecords")
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

        erase_after  = (data.get("eraseAfter") or "")[:10]
        expiry_text  = ""
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
        self.report_btn.setVisible(has_link)
