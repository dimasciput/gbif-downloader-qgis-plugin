import json

from qgis.PyQt.QtNetwork import (
    QNetworkAccessManager, 
    QNetworkReply, 
    QNetworkRequest
)
from qgis.PyQt.QtWidgets import (
    QCompleter,
    QLineEdit,
    QPushButton,
)
from qgis.PyQt.QtCore import (
    Qt,
    QTimer,
    QUrl,
    QUrlQuery,
)
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel

from .accordion import ACTION_BTN_STYLE, AccordionSection
from .taxon_filter import AutocompleteNameDelegate


class Dataset(object):
    title: str
    key: str

    def __init__(self, title: str, key: str):
        self.title = title
        self.key = key


class DatasetFilterSection(AccordionSection):
    """AccordionSection with GBIF Dataset API autocomplete."""

    _SUGGEST_URL = "https://api.gbif.org/v1/dataset/suggest"

    def __init__(self, parent=None):
        super().__init__(
            "Dataset",
            description="Limit occurrences to a specific GBIF dataset.",
            parent=parent,
        )

        self._manager = QNetworkAccessManager(self)
        self._reply = None
        self._pending_query = ""
        self._suggestion_keys: dict[str, str] = {}
        self._selected: Dataset | None = None

        layout = self.content_layout

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("e.g. iNaturalist (leave blank for all)")

        self._model = QStandardItemModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setCompletionRole(Qt.UserRole)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setFilterMode(Qt.MatchContains)
        self._edit.setCompleter(self._completer)
        self._completer.popup().setItemDelegate(AutocompleteNameDelegate(self))
        self._completer.activated[str].connect(self._apply_completion)

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(ACTION_BTN_STYLE)

        layout.addWidget(self._edit, 0, 0, 1, 4)
        layout.addWidget(clear_btn, 1, 3)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)

        self._edit.textEdited.connect(self._on_text_edited)
        self._edit.textChanged.connect(self._update_active)
        self._timer.timeout.connect(self._fetch_suggestions)
        clear_btn.clicked.connect(self._clear)
        self.toggled.connect(lambda _: self._update_active())

    def _on_text_edited(self, text: str):
        self._selected = None
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
        params.addQueryItem("type", "OCCURRENCE")
        params.addQueryItem("limit", "12")
        url.setQuery(params)

        request = QNetworkRequest(url)
        request.setRawHeader(b"User-Agent", b"gbif-downloader-qgis-plugin/1.0")
        request.setRawHeader(b"Accept", b"application/json")

        self._reply = self._manager.get(request)
        self._reply.finished.connect(
            lambda reply=self._reply, query=query: self._on_reply(reply, query)
        )

    def _on_reply(self, reply: QNetworkReply, query: str):
        try:
            if reply.error() != QNetworkReply.NoError:
                if reply.error() != QNetworkReply.OperationCanceledError:
                    self._model.clear()
                return

            if query != self._pending_query:
                return

            data = bytes(reply.readAll()).decode("utf-8")
            try:
                suggestions = json.loads(data)
                self._suggestion_keys = {}
            except ValueError:
                self._model.clear()
                return

            items = []
            seen = set()
            for item in suggestions:
                title = item.get("title", "").strip()
                if title and title not in seen:
                    seen.add(title)
                    items.append((title, title))
                    self._suggestion_keys[title] = item.get("key", "")
            self._set_suggestions(items)
            if items and self._edit.hasFocus():
                self._completer.complete()
        finally:
            reply.deleteLater()
            if reply is self._reply:
                self._reply = None

    def _apply_completion(self, value: str):
        title = value.split("\n", 1)[0].strip()
        self._edit.setText(title)
        key = self._suggestion_keys.get(title, "")
        self._selected = Dataset(title, key)
        self._update_active()

    def _set_suggestions(self, suggestions: list[tuple[str, str]]):
        self._model.clear()
        for title, display_text in suggestions:
            item = QStandardItem(display_text)
            item.setData(title, Qt.UserRole)
            self._model.appendRow(item)

    def _clear(self):
        self._selected = None
        self._edit.clear()
        self._model.clear()
        self._update_active()

    def _update_active(self):
        self.set_active(self._selected is not None)

    def get_selected(self) -> Dataset | None:
        """Return the selected dataset, or None for no filter."""
        return self._selected
