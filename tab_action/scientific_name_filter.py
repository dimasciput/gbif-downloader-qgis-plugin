import json

from qgis.PyQt.QtCore import Qt, QTimer, QUrl, QUrlQuery
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import QCompleter, QLineEdit, QListWidget, QListWidgetItem, QPushButton

from .accordion import ACTION_BTN_STYLE, AccordionSection
from .taxon_filter import AutocompleteNameDelegate


class Taxon:
    def __init__(self, name: str, key: str):
        self.name = name
        self.key = key


class ScientificNameFilterSection(AccordionSection):
    """AccordionSection with GBIF Species API autocomplete for scientific names (multi-select)."""

    _SUGGEST_URL = "https://api.gbif.org/v1/species/suggest"

    def __init__(self, parent=None):
        super().__init__(
            "Scientific name",
            description="Scientific name of the occurrence as determined by the identifier.",
            parent=parent,
        )
        self._manager = QNetworkAccessManager(self)
        self._reply = None
        self._pending_query = ""
        self._suggestion_keys: dict[str, str] = {}
        self._selected: list[Taxon] = []

        layout = self.content_layout

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("e.g. Panthera leo (leave blank for all)")

        self._model = QStandardItemModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setCompletionRole(Qt.UserRole)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setFilterMode(Qt.MatchContains)
        self._edit.setCompleter(self._completer)
        self._completer.popup().setItemDelegate(AutocompleteNameDelegate(self))
        self._completer.activated[str].connect(self._add_taxon)

        self._selected_list = QListWidget()
        self._selected_list.setMaximumHeight(90)

        remove_btn = QPushButton("Remove")
        remove_btn.setStyleSheet(ACTION_BTN_STYLE)
        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(ACTION_BTN_STYLE)

        layout.addWidget(self._edit,          0, 0, 1, 4)
        layout.addWidget(self._selected_list, 1, 0, 1, 4)
        layout.addWidget(remove_btn,          2, 2)
        layout.addWidget(clear_btn,           2, 3)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)

        self._edit.textEdited.connect(self._on_text_edited)
        self._timer.timeout.connect(self._fetch_suggestions)
        remove_btn.clicked.connect(self._remove_selected)
        clear_btn.clicked.connect(self._clear)
        self.toggled.connect(lambda _: self._update_active())

    def _on_text_edited(self, text: str):
        self._pending_query = text.strip()
        if len(self._pending_query) < 3:
            self._timer.stop()
            self._model.clear()
            return
        self._timer.start()

    def _fetch_suggestions(self):
        query = self._pending_query
        if len(query) < 3:
            return
        if self._reply and self._reply.isRunning():
            self._reply.abort()
        url = QUrl(self._SUGGEST_URL)
        params = QUrlQuery()
        params.addQueryItem("q", query)
        params.addQueryItem("limit", "12")
        url.setQuery(params)
        request = QNetworkRequest(url)
        request.setRawHeader(b"User-Agent", b"gbif-downloader-qgis-plugin/1.0")
        request.setRawHeader(b"Accept", b"application/json")
        self._reply = self._manager.get(request)
        self._reply.finished.connect(
            lambda reply=self._reply, q=query: self._on_reply(reply, q)
        )

    def _on_reply(self, reply: QNetworkReply, query: str):
        try:
            if reply.error() != QNetworkReply.NoError:
                if reply.error() != QNetworkReply.OperationCanceledError:
                    self._model.clear()
                return
            if query != self._pending_query:
                return
            try:
                suggestions = json.loads(bytes(reply.readAll()).decode("utf-8"))
                self._suggestion_keys = {}
            except ValueError:
                self._model.clear()
                return
            items = []
            seen = set()
            for item in suggestions:
                name = item.get("scientificName") or item.get("canonicalName") or ""
                if name and name not in seen:
                    seen.add(name)
                    rank = (item.get("rank") or "").replace("_", " ").title()
                    items.append((name, f"{name}\n{rank}" if rank else name))
                    self._suggestion_keys[name] = str(item.get("key", ""))
            self._model.clear()
            for name, display in items:
                si = QStandardItem(display)
                si.setData(name, Qt.UserRole)
                self._model.appendRow(si)
            if items and self._edit.hasFocus():
                self._completer.complete()
        finally:
            reply.deleteLater()
            if reply is self._reply:
                self._reply = None

    def _add_taxon(self, value: str):
        name = value.split("\n", 1)[0].strip()
        if not name or any(t.name == name for t in self._selected):
            QTimer.singleShot(0, self._edit.clear)
            return
        key = self._suggestion_keys.get(name, "")
        self._selected.append(Taxon(name, key))
        item = QListWidgetItem(name)
        item.setData(Qt.UserRole, name)
        self._selected_list.addItem(item)
        self._model.clear()
        QTimer.singleShot(0, self._edit.clear)
        self._update_active()
        self.filter_changed.emit()

    def _remove_selected(self):
        for item in self._selected_list.selectedItems():
            name = item.data(Qt.UserRole)
            self._selected = [t for t in self._selected if t.name != name]
            self._selected_list.takeItem(self._selected_list.row(item))
        self._update_active()
        self.filter_changed.emit()

    def _clear(self):
        self._selected.clear()
        self._selected_list.clear()
        self._edit.clear()
        self._model.clear()
        self._update_active()
        self.filter_changed.emit()

    def _update_active(self):
        self.set_active(bool(self._selected))

    def get_selected(self) -> list[Taxon]:
        """Return the selected taxa."""
        return list(self._selected)
