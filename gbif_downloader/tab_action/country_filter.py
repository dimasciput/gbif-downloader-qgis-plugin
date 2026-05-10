import os

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel
from qgis.PyQt.QtWidgets import (
    QCompleter,
    QListWidgetItem,
    QWidget,
)

from gbif_downloader.tab_action.accordion import ACTION_BTN_STYLE, AccordionSection
from gbif_downloader.tab_action.countries import COUNTRIES

_GUI_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gui")
FORM_CLASS, _ = uic.loadUiType(os.path.join(_GUI_DIR, "country_filter.ui"))


class CountryFilterWidget(QWidget, FORM_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)


class CountryFilterSection(AccordionSection):
    """AccordionSection with autocomplete and multi-select country chips."""

    def __init__(self, parent=None):
        super().__init__("Country", parent)
        self._selected_codes = set()
        self._country_by_code = {code: name for name, code in COUNTRIES}
        self._code_by_display = {}

        layout = self.content_layout
        self._widget = CountryFilterWidget(self)
        layout.addWidget(self._widget, 0, 0, 1, 4)

        self._edit = self._widget.country_edit
        self._selected_list = self._widget.selected_list

        self._model = QStandardItemModel(self)
        for name, code in COUNTRIES:
            display = self._display_text(name, code)
            item = QStandardItem(display)
            item.setData(code, Qt.UserRole)
            self._model.appendRow(item)
            self._code_by_display[display.casefold()] = code
            self._code_by_display[name.casefold()] = code
            self._code_by_display[code.casefold()] = code

        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCompletionRole(Qt.DisplayRole)
        self._completer.setFilterMode(Qt.MatchContains)
        self._edit.setCompleter(self._completer)

        for btn in (self._widget.remove_btn, self._widget.clear_btn):
            btn.setStyleSheet(ACTION_BTN_STYLE)

        self._completer.activated[str].connect(self._add_country)
        self._edit.returnPressed.connect(lambda: self._add_country(self._edit.text()))
        self._widget.remove_btn.clicked.connect(self._remove_selected)
        self._widget.clear_btn.clicked.connect(self._clear)

    def _display_text(self, name: str, code: str) -> str:
        return f"{name} ({code})"

    def _add_country(self, text: str):
        code = self._code_for_text(text)
        if not code or code in self._selected_codes:
            return

        self._selected_codes.add(code)
        item = QListWidgetItem(self._display_text(self._country_by_code[code], code))
        item.setData(Qt.UserRole, code)
        self._selected_list.addItem(item)
        self._edit.clear()
        self._update_active()

    def _code_for_text(self, text: str) -> str:
        normalized = text.strip().casefold()
        if not normalized:
            return ""
        return self._code_by_display.get(normalized, "")

    def _remove_selected(self):
        for item in self._selected_list.selectedItems():
            self._selected_codes.discard(item.data(Qt.UserRole))
            self._selected_list.takeItem(self._selected_list.row(item))
        self._update_active()

    def _clear(self):
        self._selected_codes.clear()
        self._selected_list.clear()
        self._edit.clear()
        self._update_active()

    def _update_active(self):
        self.set_active(bool(self._selected_codes))

    def get_selected_countries(self) -> list[str]:
        """Return selected GBIF country codes."""
        countries = []
        for index in range(self._selected_list.count()):
            countries.append(self._selected_list.item(index).data(Qt.UserRole))
        return countries
