import json
import zipfile

from qgis.core import QgsWkbTypes

POLL_MS = 30_000
PENDING = {"PREPARING", "RUNNING", "SUBMITTED"}
_STATUS_CSS = {
    "SUCCEEDED":   "#2d6a2d",
    "RUNNING":     "#1a3a6b",
    "PREPARING":   "#1a7070",
    "SUBMITTED":   "#1a7070",
    "FAILED":      "#b22222",
    "KILLED":      "#6b1a1a",
    "CANCELLED":   "#888888",
    "SUSPENDED":   "#735c0f",
    "FILE_ERASED": "#5f6368",
}
_TSV_SKIP = {"citation", "rights", "metadata", "multimedia", "verbatim"}
STATUSES = [
    "PREPARING", "RUNNING", "SUCCEEDED",
    "CANCELLED", "KILLED", "FAILED",
    "SUSPENDED", "FILE_ERASED",
]


def _find_tsv(zf: zipfile.ZipFile) -> str:
    candidates = [
        n for n in zf.namelist()
        if n.lower().endswith((".csv", ".tsv", ".txt"))
        and not any(s in n.lower() for s in _TSV_SKIP)
    ]
    return candidates[0] if candidates else zf.namelist()[0]


def _fmt_size(size_bytes) -> str:
    if not size_bytes:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _predicate_to_rows(pred) -> list[tuple[str, str, str, str]]:
    if not pred:
        return []
    if isinstance(pred, str):
        try:
            pred = json.loads(pred)
        except json.JSONDecodeError:
            return [("", "predicate", "", pred)]
    if not isinstance(pred, dict):
        return [("", "predicate", "", str(pred))]

    _OP = {
        "equals": "=",
        "in": "in",
        "greaterThan": ">",
        "lessThan": "<",
        "greaterThanOrEquals": ">=",
        "lessThanOrEquals": "<=",
        "like": "like",
    }

    def _collect(p, condition="AND"):
        t = p.get("type", "")
        if t == "and":
            rows = []
            for child in p.get("predicates", []):
                rows.extend(_collect(child, "AND"))
            return rows
        if t == "or":
            rows = []
            for child in p.get("predicates", []):
                rows.extend(_collect(child, "OR"))
            return rows
        if t == "not":
            return _collect(p.get("predicate", {}), "NOT")
        if t == "within":
            return [(condition, "GEOMETRY", "within", str(p.get("geometry", "")))]
        if t == "geoDistance":
            value = ", ".join(
                str(p.get(k, ""))
                for k in ("latitude", "longitude", "distance")
                if p.get(k, "") != ""
            )
            return [(condition, "GEOMETRY", "within distance", value)]
        if t in _OP:
            value = p.get("values", p.get("value", "?"))
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            return [(condition, p.get("key", "?"), _OP[t], str(value))]
        if t in ("isNull", "isNotNull"):
            operator = "IS NULL" if t == "isNull" else "IS NOT NULL"
            return [(condition, p.get("key", p.get("parameter", "?")), operator, "")]
        return [(condition, t or "predicate", "", str(p))]

    return _collect(pred)


def _memory_layer_type(geom) -> str:
    wkb_name = QgsWkbTypes.displayString(geom.wkbType())
    if wkb_name and wkb_name.lower() != "unknown":
        return wkb_name
    geom_type = geom.type()
    if geom_type == QgsWkbTypes.PointGeometry:
        return "Point"
    if geom_type == QgsWkbTypes.LineGeometry:
        return "LineString"
    if geom_type == QgsWkbTypes.PolygonGeometry:
        return "Polygon"
    return "Geometry"
