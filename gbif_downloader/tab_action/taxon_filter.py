import json

from qgis.core import QgsMessageLog
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel
from qgis.PyQt.QtNetwork import (
    QNetworkAccessManager, 
    QNetworkReply, 
    QNetworkRequest
)
from qgis.PyQt.QtWidgets import (
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

from gbif_downloader.tab_action.accordion import ACTION_BTN_STYLE, AccordionSection


class Taxon(object):
    name: str
    key: str

    def __init__(self, name: str, key: str):
        self.name = name
        self.key = key


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
    suggestion_keys = {}

    def __init__(self, parent=None):
        super().__init__("Scientific name", parent)

        self._manager = QNetworkAccessManager(self)
        self._reply = None
        self._pending_query = ""

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
                self.suggestion_keys = {}
            except ValueError:
                self._model.clear()
                return

            for item in suggestions:
                name = item.get("scientificName") or item.get("canonicalName")
                if name and name not in seen:
                    seen.add(name)
                    rank = (item.get("rank") or "").replace("_", " ").title()
                    names.append((name, f"{name}\n{rank}" if rank else name))
                    self.suggestion_keys[name] = item.get('key')
            self._set_suggestions(names)
            if names and self._edit.hasFocus():
                self._completer.complete()
        finally:
            reply.deleteLater()
            if reply is self._reply:
                self._reply = None

    def _apply_completion(self, value: str):
        self._edit.setText(value.split("\n", 1)[0].strip())

    def _set_suggestions(self, suggestions: list[tuple[str, str]]):
        self._model.clear()
        for name, display_text in suggestions:
            item = QStandardItem(display_text)
            item.setData(name, Qt.UserRole)
            self._model.appendRow(item)

    def _clear(self):
        self._edit.clear()
        self._model.clear()
        self._update_active()

    def _update_active(self):
        self.set_active(self.is_expanded() and bool(self.get_selected_taxon()))

    def get_selected_taxon(self) -> Taxon:
        """Return the selected/entered scientific name, or empty string for no filter."""
        if not self.is_expanded():
            return None
        scientific_name = self._edit.text().strip()
        taxon_key = ''
        if scientific_name in self.suggestion_keys:
            taxon_key = self.suggestion_keys[scientific_name]
        return Taxon(scientific_name, taxon_key)
    