from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsMarkerSymbol,
    QgsRendererCategory,
    QgsVectorLayer,
)

# IUCN Red List standard colors
_IUCN_COLORS = {
    "EX":  ("#000000", "Extinct"),
    "EW":  ("#542344", "Extinct in the Wild"),
    "CR":  ("#D81E05", "Critically Endangered"),
    "EN":  ("#FC7F3F", "Endangered"),
    "VU":  ("#F9E814", "Vulnerable"),
    "NT":  ("#CCE226", "Near Threatened"),
    "LC":  ("#60C659", "Least Concern"),
    "DD":  ("#D1D1C6", "Data Deficient"),
    "NE":  ("#CCCCCC", "Not Evaluated"),
}
_FIELD = "iucnredlistcategory"


def apply_iucn_style(layer: QgsVectorLayer) -> bool:
    """Apply categorized IUCN Red List styling. Returns False if the field is absent."""
    fields = [f.name().lower() for f in layer.fields()]
    if _FIELD not in fields:
        return False

    actual_field = layer.fields()[fields.index(_FIELD)].name()

    categories = []
    for code, (color, label) in _IUCN_COLORS.items():
        symbol = QgsMarkerSymbol.createSimple({
            "name":         "circle",
            "color":        color,
            "outline_color": "#383838",
            "outline_width": "0.4",
            "size":          "2.5",
        })
        categories.append(QgsRendererCategory(code, symbol, f"{code} – {label}"))

    catch_all = QgsMarkerSymbol.createSimple({
        "name":          "circle",
        "color":         "#aaaaaa",
        "outline_color": "#ffffff",
        "outline_width": "0.3",
        "size":          "2",
    })
    categories.append(QgsRendererCategory("", catch_all, "(unknown)"))

    renderer = QgsCategorizedSymbolRenderer(actual_field, categories)
    layer.setRenderer(renderer)
    layer.triggerRepaint()
    return True
