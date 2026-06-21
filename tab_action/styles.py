HEADER_STYLE = """
QToolButton {
    font-weight: bold;
    font-size: 13px;
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

ACTIVE_HEADER_STYLE = """
QToolButton {
    font-weight: bold;
    font-size: 13px;
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

ACTION_BTN_STYLE = """
QPushButton {
    border: 1px solid #888888;
    border-radius: 3px;
    padding: 2px 8px;
    font-size: 11px;
}
QPushButton:hover { background-color: rgba(0, 0, 0, 18); }
QPushButton:pressed { background-color: rgba(0, 0, 0, 35); }
"""
