import datetime

from .styles import ACTION_BTN_STYLE, ACTIVE_HEADER_STYLE, HEADER_STYLE
from qgis.PyQt.QtCore import (
    Qt,
    pyqtSignal,
)
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class AccordionSection(QWidget):
    """Collapsible section with a styled header toggle and content panel.
    """

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, description: str = "", parent=None):
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
        self._header.setStyleSheet(HEADER_STYLE)
        self._header.toggled.connect(self._on_toggle)

        self._panel = QWidget()
        self._panel.setAutoFillBackground(True)
        self._panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._panel.setVisible(False)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        if description:
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet(
                "color: #888; font-size: 12px; padding: 4px 8px 2px 18px;"
            )
            panel_layout.addWidget(desc_label)

        _content_widget = QWidget()
        self._content_layout = QGridLayout(_content_widget)
        self._content_layout.setContentsMargins(20, 6, 8, 6)
        self._content_layout.setHorizontalSpacing(12)
        self._content_layout.setVerticalSpacing(4)
        panel_layout.addWidget(_content_widget)

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
        self._header.setStyleSheet(ACTIVE_HEADER_STYLE if active else HEADER_STYLE)
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
        description: str = "",
        parent=None,
    ):
        super().__init__(title, description=description, parent=parent)
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
        select_all_btn.setStyleSheet(ACTION_BTN_STYLE)
        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(ACTION_BTN_STYLE)
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


class YearFilterSection(AccordionSection):
    """AccordionSection with GBIF-style year filter.

    Modes: Between, Is, Before end of, After start of.
    The selected mode applies even when the section is collapsed.
    """

    _MODES = [
        ("No filter",      "none"),
        ("Between",        "between"),
        ("Is",             "is"),
        ("Before end of",  "before"),
        ("After start of", "after"),
    ]

    def __init__(self, parent=None):
        super().__init__(
            "Year",
            description="The four-digit year in which the event occurred, following ISO 8601.",
            parent=parent,
        )
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
        clear_btn.setStyleSheet(ACTION_BTN_STYLE)

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
        self.set_active(self._mode_key() != "none")

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


class NumericRangeFilterSection(AccordionSection):
    """AccordionSection with a mode dropdown and one or two numeric spinboxes."""

    _MODES = [
        ("No filter", "none"),
        ("At most",   "atmost"),
        ("At least",  "atleast"),
        ("Between",   "between"),
    ]

    def __init__(
        self,
        title: str,
        key: str,
        min_val: int,
        max_val: int,
        step: int = 1,
        default_from: int | None = None,
        default_to: int | None = None,
        description: str = "",
        parent=None,
    ):
        super().__init__(title, description=description, parent=parent)
        self._key = key

        layout = self.content_layout

        self._mode_combo = QComboBox()
        for label, _ in self._MODES:
            self._mode_combo.addItem(label)
        layout.addWidget(self._mode_combo, 0, 0, 1, 4)

        self._spin_from = QSpinBox()
        self._spin_from.setRange(min_val, max_val)
        self._spin_from.setSingleStep(step)
        self._spin_from.setValue(default_from if default_from is not None else min_val)

        self._label_to = QLabel("to")
        self._label_to.setAlignment(Qt.AlignCenter)

        self._spin_to = QSpinBox()
        self._spin_to.setRange(min_val, max_val)
        self._spin_to.setSingleStep(step)
        self._spin_to.setValue(default_to if default_to is not None else max_val)

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(ACTION_BTN_STYLE)

        layout.addWidget(self._spin_from, 1, 0)
        layout.addWidget(self._label_to,  1, 1)
        layout.addWidget(self._spin_to,   1, 2)
        layout.addWidget(clear_btn,       1, 3)

        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        clear_btn.clicked.connect(self._clear)
        self.toggled.connect(lambda _: self._update_active())
        self._on_mode_changed(0)

    def _mode_key(self) -> str:
        return self._MODES[self._mode_combo.currentIndex()][1]

    def _update_active(self):
        self.set_active(self._mode_key() != "none")

    def _on_mode_changed(self, _index: int = 0):
        mode = self._mode_key()
        has_input = mode != "none"
        is_between = mode == "between"
        self._spin_from.setVisible(has_input)
        self._label_to.setVisible(is_between)
        self._spin_to.setVisible(is_between)
        self._update_active()

    def _clear(self):
        self._mode_combo.setCurrentIndex(0)

    def get_predicate(self) -> list[dict]:
        """Return GBIF predicate parts for this filter, or [] for no filter."""
        mode = self._mode_key()
        if mode == "none":
            return []
        v1 = self._spin_from.value()
        v2 = self._spin_to.value()
        if mode == "atmost":
            return [{"type": "lessThanOrEquals", "key": self._key, "value": str(v1)}]
        if mode == "atleast":
            return [{"type": "greaterThanOrEquals", "key": self._key, "value": str(v1)}]
        if mode == "between":
            lo, hi = min(v1, v2), max(v1, v2)
            return [
                {"type": "greaterThanOrEquals", "key": self._key, "value": str(lo)},
                {"type": "lessThanOrEquals",    "key": self._key, "value": str(hi)},
            ]
        return []
