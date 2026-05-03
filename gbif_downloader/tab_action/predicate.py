from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
    QgsWkbTypes,
)

_WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")


def geom_to_wkt(geom: QgsGeometry, canvas_crs) -> str:
    g = QgsGeometry(geom)
    if canvas_crs != _WGS84:
        g.transform(QgsCoordinateTransform(canvas_crs, _WGS84, QgsProject.instance()))
    g = _normalize_polygon_orientation(g)
    return g.asWkt()


def _normalize_polygon_orientation(geom: QgsGeometry) -> QgsGeometry:
    if QgsWkbTypes.geometryType(geom.wkbType()) != QgsWkbTypes.PolygonGeometry:
        return geom

    if QgsWkbTypes.isMultiType(geom.wkbType()):
        polygons = [_normalize_polygon_rings(poly) for poly in geom.asMultiPolygon()]
        return QgsGeometry.fromMultiPolygonXY(polygons)

    return QgsGeometry.fromPolygonXY(_normalize_polygon_rings(geom.asPolygon()))


def _normalize_polygon_rings(polygon: list) -> list:
    if not polygon:
        return polygon

    rings = []
    for index, ring in enumerate(polygon):
        ring = _without_consecutive_duplicate_points(ring)
        is_exterior = index == 0
        is_counter_clockwise = _ring_signed_area(ring) > 0
        if is_exterior != is_counter_clockwise:
            ring = list(reversed(ring))
        rings.append(ring)
    return rings


def _without_consecutive_duplicate_points(ring: list) -> list:
    cleaned = []
    for point in ring:
        if not cleaned or point != cleaned[-1]:
            cleaned.append(point)
    if len(cleaned) > 2 and cleaned[0] != cleaned[-1]:
        cleaned.append(cleaned[0])
    return cleaned


def _ring_signed_area(ring: list) -> float:
    if len(ring) < 4:
        return 0
    return sum(
        ring[i].x() * ring[i + 1].y() - ring[i + 1].x() * ring[i].y()
        for i in range(len(ring) - 1)
    )


def build_predicate(
    scientific_name: str,
    country: str | list[str],
    basis: str | list[str],
    geometry_wkt: str,
    year_predicates: list | None = None,
    months: list | None = None,
) -> dict:
    parts = [
        {"type": "equals", "key": "HAS_COORDINATE",       "value": "true"},
        {"type": "equals", "key": "HAS_GEOSPATIAL_ISSUE",  "value": "false"},
    ]
    if year_predicates:
        parts.extend(year_predicates)
    if scientific_name:
        parts.append(
            {"type": "equals", "key": "SCIENTIFIC_NAME", "value": scientific_name}
        )
    if country:
        if isinstance(country, list):
            parts.append({"type": "in", "key": "COUNTRY", "values": country})
        else:
            parts.append({"type": "equals", "key": "COUNTRY", "value": country})
    if basis:
        if isinstance(basis, list):
            parts.append({"type": "in", "key": "BASIS_OF_RECORD", "values": basis})
        else:
            parts.append({"type": "equals", "key": "BASIS_OF_RECORD", "value": basis})
    if geometry_wkt:
        parts.append({"type": "within", "geometry": geometry_wkt})
    if months:
        parts.append({"type": "in", "key": "MONTH", "values": [str(m) for m in months]})

    return {"type": "and", "predicates": parts}
