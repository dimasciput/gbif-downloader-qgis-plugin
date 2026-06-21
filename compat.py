"""
Patch Qt classes so PyQt5-style flat enum access works under PyQt6.
Import this module once before any Qt widgets are created.
"""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtNetwork import QNetworkReply
from qgis.PyQt.QtWidgets import (
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QMessageBox,
    QSizePolicy,
    QStyle,
    QToolButton,
)

_QT_ALIASES = {
    # TextInteractionFlag
    "TextSelectableByMouse":    ("TextInteractionFlag", "TextSelectableByMouse"),
    "TextSelectableByKeyboard": ("TextInteractionFlag", "TextSelectableByKeyboard"),
    "LinksAccessibleByMouse":   ("TextInteractionFlag", "LinksAccessibleByMouse"),
    "TextBrowserInteraction":   ("TextInteractionFlag", "TextBrowserInteraction"),
    # CaseSensitivity
    "CaseInsensitive": ("CaseSensitivity", "CaseInsensitive"),
    "CaseSensitive":   ("CaseSensitivity", "CaseSensitive"),
    # MatchFlag
    "MatchContains": ("MatchFlag", "MatchContains"),
    "MatchExactly":  ("MatchFlag", "MatchExactly"),
    # ArrowType
    "RightArrow": ("ArrowType", "RightArrow"),
    "DownArrow":  ("ArrowType", "DownArrow"),
    "NoArrow":    ("ArrowType", "NoArrow"),
    "LeftArrow":  ("ArrowType", "LeftArrow"),
    # ToolButtonStyle
    "ToolButtonTextBesideIcon": ("ToolButtonStyle", "ToolButtonTextBesideIcon"),
    "ToolButtonTextOnly":       ("ToolButtonStyle", "ToolButtonTextOnly"),
    "ToolButtonIconOnly":       ("ToolButtonStyle", "ToolButtonIconOnly"),
    # AlignmentFlag
    "AlignLeft":    ("AlignmentFlag", "AlignLeft"),
    "AlignRight":   ("AlignmentFlag", "AlignRight"),
    "AlignCenter":  ("AlignmentFlag", "AlignCenter"),
    "AlignHCenter": ("AlignmentFlag", "AlignHCenter"),
    "AlignVCenter": ("AlignmentFlag", "AlignVCenter"),
    "AlignTop":     ("AlignmentFlag", "AlignTop"),
    "AlignBottom":  ("AlignmentFlag", "AlignBottom"),
    # Orientation
    "Horizontal": ("Orientation", "Horizontal"),
    "Vertical":   ("Orientation", "Vertical"),
    # ItemDataRole
    "UserRole":    ("ItemDataRole", "UserRole"),
    "DisplayRole": ("ItemDataRole", "DisplayRole"),
    # TextElideMode
    "ElideRight":  ("TextElideMode", "ElideRight"),
    "ElideLeft":   ("TextElideMode", "ElideLeft"),
    "ElideMiddle": ("TextElideMode", "ElideMiddle"),
    # PenStyle
    "NoPen":    ("PenStyle", "NoPen"),
    "DashLine": ("PenStyle", "DashLine"),
    # BrushStyle
    "NoBrush": ("BrushStyle", "NoBrush"),
    # WindowType
    "WindowContextHelpButtonHint": ("WindowType", "WindowContextHelpButtonHint"),
    # DockWidgetArea
    "RightDockWidgetArea": ("DockWidgetArea", "RightDockWidgetArea"),
    "LeftDockWidgetArea":  ("DockWidgetArea", "LeftDockWidgetArea"),
    # MouseButton
    "LeftButton":  ("MouseButton", "LeftButton"),
    "RightButton": ("MouseButton", "RightButton"),
}

# (widget_class, flat_name, enum_class_name, enum_member)
_CLASS_ALIASES = [
    # QCompleter.CompletionMode
    (QCompleter, "PopupCompletion",          "CompletionMode", "PopupCompletion"),
    (QCompleter, "UnfilteredPopupCompletion","CompletionMode", "UnfilteredPopupCompletion"),
    (QCompleter, "InlineCompletion",         "CompletionMode", "InlineCompletion"),
    # QNetworkReply.NetworkError
    (QNetworkReply, "NoError",                 "NetworkError", "NoError"),
    (QNetworkReply, "OperationCanceledError",   "NetworkError", "OperationCanceledError"),
    (QNetworkReply, "ConnectionRefusedError",   "NetworkError", "ConnectionRefusedError"),
    (QNetworkReply, "RemoteHostClosedError",    "NetworkError", "RemoteHostClosedError"),
    (QNetworkReply, "TimeoutError",             "NetworkError", "TimeoutError"),
    # QDialogButtonBox.StandardButton
    (QDialogButtonBox, "Ok",     "StandardButton", "Ok"),
    (QDialogButtonBox, "Cancel", "StandardButton", "Cancel"),
    (QDialogButtonBox, "Save",   "StandardButton", "Save"),
    (QDialogButtonBox, "Close",  "StandardButton", "Close"),
    (QDialogButtonBox, "Yes",    "StandardButton", "Yes"),
    (QDialogButtonBox, "No",     "StandardButton", "No"),
    # QMessageBox.StandardButton
    (QMessageBox, "Yes",    "StandardButton", "Yes"),
    (QMessageBox, "No",     "StandardButton", "No"),
    (QMessageBox, "Ok",     "StandardButton", "Ok"),
    (QMessageBox, "Cancel", "StandardButton", "Cancel"),
    # QToolButton.ToolButtonPopupMode
    (QToolButton, "MenuButtonPopup", "ToolButtonPopupMode", "MenuButtonPopup"),
    (QToolButton, "InstantPopup",    "ToolButtonPopupMode", "InstantPopup"),
    (QToolButton, "DelayedPopup",    "ToolButtonPopupMode", "DelayedPopup"),
    # QFont.Weight
    (QFont, "Bold",   "Weight", "Bold"),
    (QFont, "Normal", "Weight", "Normal"),
    (QFont, "Light",  "Weight", "Light"),
    (QFont, "Black",  "Weight", "Black"),
    # QFrame.Shape / QFrame.Shadow
    (QFrame, "HLine",  "Shape",  "HLine"),
    (QFrame, "VLine",  "Shape",  "VLine"),
    (QFrame, "Box",    "Shape",  "Box"),
    (QFrame, "Panel",  "Shape",  "Panel"),
    (QFrame, "Sunken", "Shadow", "Sunken"),
    (QFrame, "Raised", "Shadow", "Raised"),
    (QFrame, "Plain",  "Shadow", "Plain"),
    # QSizePolicy.Policy
    (QSizePolicy, "Expanding", "Policy", "Expanding"),
    (QSizePolicy, "Fixed",     "Policy", "Fixed"),
    (QSizePolicy, "Preferred", "Policy", "Preferred"),
    (QSizePolicy, "Maximum",   "Policy", "Maximum"),
    (QSizePolicy, "Minimum",   "Policy", "Minimum"),
    (QSizePolicy, "Ignored",   "Policy", "Ignored"),
    # QDialog.DialogCode
    (QDialog, "Accepted", "DialogCode", "Accepted"),
    (QDialog, "Rejected", "DialogCode", "Rejected"),
    # QStyle.ControlElement
    (QStyle, "CE_ItemViewItem", "ControlElement", "CE_ItemViewItem"),
]


def _patch():
    for flat, (enum_cls_name, enum_attr) in _QT_ALIASES.items():
        if hasattr(Qt, flat):
            continue
        enum_cls = getattr(Qt, enum_cls_name, None)
        if enum_cls is None:
            continue
        val = getattr(enum_cls, enum_attr, None)
        if val is not None:
            try:
                setattr(Qt, flat, val)
            except (AttributeError, TypeError):
                pass

    for cls, flat_name, enum_cls_name, enum_attr in _CLASS_ALIASES:
        if hasattr(cls, flat_name):
            continue
        enum_cls = getattr(cls, enum_cls_name, None)
        if enum_cls is None:
            continue
        val = getattr(enum_cls, enum_attr, None)
        if val is not None:
            try:
                setattr(cls, flat_name, val)
            except (AttributeError, TypeError):
                pass


_patch()
