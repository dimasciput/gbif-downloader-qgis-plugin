import datetime
import json

from qgis.PyQt.QtCore import (
    QRect,
    QSize,
    Qt,
    QTimer,
    QUrl,
    QUrlQuery,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_HEADER_STYLE = """
QToolButton {
    font-weight: bold;
    padding: 4px 8px;
    border: none;
    border-radius: 3px;
    border-bottom: 1px solid transparent;
    background: transparent;
    text-align: left;
}
QToolButton:hover { background-color: rgba(0, 0, 0, 18); }
QToolButton:checked {
    border-bottom-color: #aaaaaa;
    border-bottom-right-radius: 0;
    border-bottom-left-radius: 0;
}
"""

_ACTIVE_HEADER_STYLE = """
QToolButton {
    font-weight: bold;
    padding: 4px 8px;
    border: none;
    border-radius: 3px;
    border-bottom: 1px solid transparent;
    background: rgba(76, 175, 80, 22);
    text-align: left;
}
QToolButton:hover { background-color: rgba(76, 175, 80, 45); }
QToolButton:checked {
    border-bottom-color: #88bb88;
    border-bottom-right-radius: 0;
    border-bottom-left-radius: 0;
}
"""

_ACTION_BTN_STYLE = """
QPushButton {
    border: 1px solid #888888;
    border-radius: 3px;
    padding: 2px 8px;
    font-size: 11px;
}
QPushButton:hover { background-color: rgba(0, 0, 0, 18); }
QPushButton:pressed { background-color: rgba(0, 0, 0, 35); }
"""


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


class AccordionSection(QWidget):
    """Collapsible section with a styled header toggle and content panel.
    """

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(0)

        self._frame = QFrame()
        self._frame.setObjectName("accordionFrame")
        self._frame.setStyleSheet(
            "QFrame#accordionFrame { border: 1px solid #aaaaaa; border-radius: 3px; }"
        )
        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        self._header = QToolButton()
        self._header.setText(title)
        self._header.setCheckable(True)
        self._header.setChecked(False)
        self._header.setArrowType(Qt.RightArrow)
        self._header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._header.setAutoRaise(False)
        self._header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._header.setStyleSheet(_HEADER_STYLE)
        self._header.toggled.connect(self._on_toggle)

        self._panel = QWidget()
        self._panel.setAutoFillBackground(True)
        self._panel.setVisible(False)

        self._content_layout = QGridLayout(self._panel)
        self._content_layout.setContentsMargins(20, 6, 8, 6)
        self._content_layout.setHorizontalSpacing(12)
        self._content_layout.setVerticalSpacing(4)

        frame_layout.addWidget(self._header)
        frame_layout.addWidget(self._panel)
        outer.addWidget(self._frame)

    @property
    def content_layout(self) -> QGridLayout:
        """Grid layout inside the collapsible panel."""
        return self._content_layout

    def is_expanded(self) -> bool:
        return self._header.isChecked()

    def set_expanded(self, expanded: bool):
        self._header.setChecked(expanded)

    def set_active(self, active: bool):
        self._header.setStyleSheet(_ACTIVE_HEADER_STYLE if active else _HEADER_STYLE)
        border = "#88bb88" if active else "#aaaaaa"
        self._frame.setStyleSheet(
            f"QFrame#accordionFrame {{ border: 1px solid {border}; border-radius: 3px; }}"
        )

    def _on_toggle(self, checked: bool):
        self._panel.setVisible(checked)
        self._header.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.toggled.emit(checked)


class CheckboxFilterSection(AccordionSection):
    """AccordionSection pre-populated with labeled checkboxes and Select All / Clear buttons.

    Args:
        title:   Header label.
        items:   Sequence of ``(label, value)`` pairs — one checkbox per entry.
        columns: Number of checkboxes per row (default 4).
    """

    def __init__(
        self,
        title: str,
        items: list[tuple[str, object]],
        columns: int = 4,
        parent=None,
    ):
        super().__init__(title, parent)
        self._checkboxes: list[tuple[QCheckBox, object]] = []

        layout = self.content_layout
        for i, (label, value) in enumerate(items):
            cb = QCheckBox(label)
            cb.stateChanged.connect(self._update_active)
            layout.addWidget(cb, i // columns, i % columns)
            self._checkboxes.append((cb, value))

        action_row = (len(items) + columns - 1) // columns
        half = columns // 2
        select_all_btn = QPushButton("Select All")
        select_all_btn.setStyleSheet(_ACTION_BTN_STYLE)
        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(_ACTION_BTN_STYLE)
        layout.addWidget(select_all_btn, action_row, 0, 1, half)
        layout.addWidget(clear_btn,      action_row, half, 1, columns - half)

        select_all_btn.clicked.connect(self._select_all)
        clear_btn.clicked.connect(self._clear_all)

    def _select_all(self):
        for cb, _ in self._checkboxes:
            cb.setChecked(True)

    def _clear_all(self):
        for cb, _ in self._checkboxes:
            cb.setChecked(False)

    def _update_active(self):
        self.set_active(bool(self.get_checked_values()))

    def get_checked_values(self) -> list:
        """Return the values of all currently checked items."""
        return [v for cb, v in self._checkboxes if cb.isChecked()]


class ScientificNameFilterSection(AccordionSection):
    """AccordionSection with GBIF Species API autocomplete for scientific names."""

    _SUGGEST_URL = "https://api.gbif.org/v1/species/suggest"

    def __init__(self, parent=None):
        super().__init__("Scientific name", parent)

        self._manager = QNetworkAccessManager(self)
        self._reply = None
        self._pending_query = ""

        layout = self.content_layout

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("e.g. Panthera leo  (leave blank for all)")

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
        clear_btn.setStyleSheet(_ACTION_BTN_STYLE)

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
            b"gbif-downloader-qgis-plugin/1.0 (https://github.com/dimasciputra/gbif-project-2026)",
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
            except ValueError:
                self._model.clear()
                return

            for item in suggestions:
                name = item.get("scientificName") or item.get("canonicalName")
                if name and name not in seen:
                    seen.add(name)
                    rank = (item.get("rank") or "").replace("_", " ").title()
                    names.append((name, f"{name}\n{rank}" if rank else name))
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
        self.set_active(self.is_expanded() and bool(self.get_scientific_name()))

    def get_scientific_name(self) -> str:
        """Return the selected/entered scientific name, or empty string for no filter."""
        if not self.is_expanded():
            return ""
        return self._edit.text().strip()


class YearFilterSection(AccordionSection):
    """AccordionSection with GBIF-style year filter.

    Modes: Between, Is, Before end of, After start of.
    Collapsed = no year filter applied.
    """

    _MODES = [
        ("No filter",      "none"),
        ("Between",        "between"),
        ("Is",             "is"),
        ("Before end of",  "before"),
        ("After start of", "after"),
    ]

    def __init__(self, parent=None):
        super().__init__("Year", parent)
        current_year = datetime.date.today().year

        layout = self.content_layout

        self._mode_combo = QComboBox()
        for label, _ in self._MODES:
            self._mode_combo.addItem(label)
        layout.addWidget(self._mode_combo, 0, 0, 1, 4)

        self._year_from = QSpinBox()
        self._year_from.setRange(1750, current_year)
        self._year_from.setValue(current_year - 5)

        self._label_to = QLabel("to")
        self._label_to.setAlignment(Qt.AlignCenter)

        self._year_to = QSpinBox()
        self._year_to.setRange(1750, current_year)
        self._year_to.setValue(current_year)

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(_ACTION_BTN_STYLE)

        layout.addWidget(self._year_from, 1, 0)
        layout.addWidget(self._label_to,  1, 1)
        layout.addWidget(self._year_to,   1, 2)
        layout.addWidget(clear_btn,       1, 3)

        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        clear_btn.clicked.connect(self._clear)
        self.toggled.connect(lambda _: self._update_active())
        self._on_mode_changed(0)

    def _mode_key(self) -> str:
        return self._MODES[self._mode_combo.currentIndex()][1]

    def _update_active(self):
        self.set_active(self.is_expanded() and self._mode_key() != "none")

    def _on_mode_changed(self, _index: int = 0):
        mode = self._mode_key()
        has_input = mode != "none"
        is_between = mode == "between"
        self._year_from.setVisible(has_input)
        self._label_to.setVisible(is_between)
        self._year_to.setVisible(is_between)
        self._update_active()

    def _clear(self):
        current_year = datetime.date.today().year
        self._year_from.setValue(current_year - 5)
        self._year_to.setValue(current_year)
        self._mode_combo.setCurrentIndex(0)

    def get_year_predicate(self) -> list[dict]:
        """Return GBIF predicate parts for the year filter, or [] for no filter."""
        if not self.is_expanded():
            return []
        mode = self._mode_key()
        if mode == "none":
            return []
        y1 = self._year_from.value()
        y2 = self._year_to.value()
        if mode == "between":
            if y1 > y2:
                y1, y2 = y2, y1
            return [
                {"type": "greaterThanOrEquals", "key": "YEAR", "value": str(y1)},
                {"type": "lessThanOrEquals",    "key": "YEAR", "value": str(y2)},
            ]
        if mode == "is":
            return [{"type": "equals", "key": "YEAR", "value": str(y1)}]
        if mode == "before":
            return [{"type": "lessThanOrEquals", "key": "YEAR", "value": str(y1)}]
        if mode == "after":
            return [{"type": "greaterThanOrEquals", "key": "YEAR", "value": str(y1)}]
        return []
