import json

from qgis.core import QgsMessageLog
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel
from qgis.PyQt.QtNetwork import (
    QNetworkAccessManager, 
    QNetworkReply, 
    QNetworkRequest
)
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QCompleter,
    QLineEdit,
    QPushButton,
    QStyledItemDelegate,
    QStyle,
)
from qgis.PyQt.QtCore import (
    Qt,
    QTimer,
    QUrl,
    QSize,
    QUrlQuery,
    QRect
)

from .accordion import ACTION_BTN_STYLE, AccordionSection


class Taxon(object):
    name: str
    key: str

    def __init__(self, name: str, key: str):
        self.name = name
        self.key = key


class HigherTaxon(object):
    name: str
    key: str
    rank: str  # KINGDOM, PHYLUM, CLASS, ORDER, FAMILY

    def __init__(self, name: str, key: str, rank: str):
        self.name = name
        self.key = key
        self.rank = rank


_HIGHER_RANKS = [
    ("Family",  "FAMILY"),
    ("Order",   "ORDER"),
    ("Class",   "CLASS"),
]


class _ScientificNameDelegate(QStyledItemDelegate):
    """Paint autocomplete rows as name + taxonomic rank."""

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), 38))

    def paint(self, painter, option, index):
        text = index.data(Qt.DisplayRole) or ""
        name, _, rank = text.partition("\n")

        painter.save()
        self.initStyleOption(option, index)
        option.text = ""
        option.widget.style().drawControl(QStyle.CE_ItemViewItem, option, painter)

        left = option.rect.left() + 6
        width = option.rect.width() - 12
        name_rect = QRect(left, option.rect.top() + 4, width, 17)
        rank_rect = QRect(left, option.rect.top() + 21, width, 13)

        painter.setPen(option.palette.text().color())
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, name)
        if rank:
            painter.drawText(rank_rect, Qt.AlignLeft | Qt.AlignVCenter, rank)
        painter.restore()


class ScientificNameFilterSection(AccordionSection):
    """AccordionSection with GBIF Species API autocomplete for scientific names."""

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
        self._selected_taxon: Taxon | None = None

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
        self._completer.popup().setItemDelegate(_ScientificNameDelegate(self))
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
        self._selected_taxon = None
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
        request.setRawHeader(
            b"User-Agent",
            b"gbif-downloader-qgis-plugin/1.0",
        )
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
            names = []
            seen = set()
            try:
                suggestions = json.loads(data)
                self._suggestion_keys = {}
            except ValueError:
                self._model.clear()
                return

            for item in suggestions:
                name = item.get("scientificName") or item.get("canonicalName")
                if name and name not in seen:
                    seen.add(name)
                    rank = (item.get("rank") or "").replace("_", " ").title()
                    names.append((name, f"{name}\n{rank}" if rank else name))
                    self._suggestion_keys[name] = item.get('key')
            self._set_suggestions(names)
            if names and self._edit.hasFocus():
                self._completer.complete()
        finally:
            reply.deleteLater()
            if reply is self._reply:
                self._reply = None

    def _apply_completion(self, value: str):
        name = value.split("\n", 1)[0].strip()
        self._edit.setText(name)
        key = self._suggestion_keys.get(name, "")
        self._selected_taxon = Taxon(name, key)
        self._update_active()

    def _set_suggestions(self, suggestions: list[tuple[str, str]]):
        self._model.clear()
        for name, display_text in suggestions:
            item = QStandardItem(display_text)
            item.setData(name, Qt.UserRole)
            self._model.appendRow(item)

    def _clear(self):
        self._selected_taxon = None
        self._edit.clear()
        self._model.clear()
        self._update_active()

    def _update_active(self):
        self.set_active(self._selected_taxon is not None)

    def get_selected_taxon(self) -> Taxon | None:
        """Return the selected taxon, or None for no filter."""
        return self._selected_taxon


class HigherTaxonFilterSection(AccordionSection):
    """AccordionSection with rank selector and GBIF autocomplete for higher taxonomy."""

    _SUGGEST_URL = "https://api.gbif.org/v1/species/suggest"

    def __init__(self, parent=None):
        super().__init__(
            "Higher taxonomy",
            description="A higher-rank taxon (family, order, or class) to filter occurrences by.",
            parent=parent,
        )

        self._manager = QNetworkAccessManager(self)
        self._reply = None
        self._pending_query = ""
        self._suggestion_keys: dict[str, str] = {}
        self._selected: HigherTaxon | None = None

        layout = self.content_layout

        self._rank_combo = QComboBox()
        for label, value in _HIGHER_RANKS:
            self._rank_combo.addItem(label, value)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("e.g. Felidae (leave blank for all)")

        self._model = QStandardItemModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setCompletionRole(Qt.UserRole)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setFilterMode(Qt.MatchContains)
        self._edit.setCompleter(self._completer)
        self._completer.popup().setItemDelegate(_ScientificNameDelegate(self))
        self._completer.activated[str].connect(self._apply_completion)

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(ACTION_BTN_STYLE)

        layout.addWidget(self._rank_combo, 0, 0, 1, 3)
        layout.addWidget(self._edit,       1, 0, 1, 4)
        layout.addWidget(clear_btn,        2, 3)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)

        self._rank_combo.currentIndexChanged.connect(self._on_rank_changed)
        self._edit.textEdited.connect(self._on_text_edited)
        self._edit.textChanged.connect(self._update_active)
        self._timer.timeout.connect(self._fetch_suggestions)
        clear_btn.clicked.connect(self._clear)
        self.toggled.connect(lambda _: self._update_active())

    def _current_rank(self) -> str:
        return self._rank_combo.currentData()

    def _on_rank_changed(self):
        self._selected = None
        self._edit.clear()
        self._model.clear()
        self._update_active()

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
        params.addQueryItem("rank", self._current_rank())
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

            names = []
            seen = set()
            for item in suggestions:
                name = item.get("scientificName") or item.get("canonicalName")
                if name and name not in seen:
                    seen.add(name)
                    rank = (item.get("rank") or "").replace("_", " ").title()
                    names.append((name, f"{name}\n{rank}" if rank else name))
                    self._suggestion_keys[name] = item.get("key")
            self._set_suggestions(names)
            if names and self._edit.hasFocus():
                self._completer.complete()
        finally:
            reply.deleteLater()
            if reply is self._reply:
                self._reply = None

    def _apply_completion(self, value: str):
        name = value.split("\n", 1)[0].strip()
        self._edit.setText(name)
        key = self._suggestion_keys.get(name, "")
        self._selected = HigherTaxon(name, key, self._current_rank())
        self._update_active()

    def _set_suggestions(self, suggestions: list[tuple[str, str]]):
        self._model.clear()
        for name, display_text in suggestions:
            item = QStandardItem(display_text)
            item.setData(name, Qt.UserRole)
            self._model.appendRow(item)

    def _clear(self):
        self._selected = None
        self._edit.clear()
        self._model.clear()
        self._update_active()

    def _update_active(self):
        self.set_active(self._selected is not None)

    def get_selected(self) -> HigherTaxon | None:
        """Return the selected higher taxon, or None for no filter."""
        return self._selected
