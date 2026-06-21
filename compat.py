"""
Patch the Qt namespace so PyQt5-style flat enum access works under PyQt6.
Import this module once before any Qt widgets are created.
"""
from qgis.PyQt.QtCore import Qt

_ALIASES = {
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
    "NoPen":   ("PenStyle", "NoPen"),
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


def _patch():
    for flat, (enum_cls, enum_attr) in _ALIASES.items():
        if hasattr(Qt, flat):
            continue
        cls = getattr(Qt, enum_cls, None)
        if cls is None:
            continue
        val = getattr(cls, enum_attr, None)
        if val is not None:
            try:
                setattr(Qt, flat, val)
            except (AttributeError, TypeError):
                pass


_patch()
