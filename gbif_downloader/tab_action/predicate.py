from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
)

_WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")


def geom_to_wkt(geom: QgsGeometry, canvas_crs) -> str:
    if canvas_crs != _WGS84:
        g = QgsGeometry(geom)
        g.transform(QgsCoordinateTransform(canvas_crs, _WGS84, QgsProject.instance()))
        return g.asWkt()
    return geom.asWkt()


def build_predicate(
    species: str,
    country: str,
    year_from: int,
    year_to: int,
    basis: str,
    geometry_wkt: str,
) -> dict:
    parts = [
        {"type": "equals", "key": "HAS_COORDINATE",       "value": "true"},
        {"type": "equals", "key": "HAS_GEOSPATIAL_ISSUE",  "value": "false"},
        {"type": "greaterThanOrEquals", "key": "YEAR", "value": str(year_from)},
        {"type": "lessThanOrEquals",    "key": "YEAR", "value": str(year_to)},
    ]
    if species:
        parts.append({"type": "equals", "key": "SCIENTIFIC_NAME", "value": species})
    if country:
        parts.append({"type": "equals", "key": "COUNTRY", "value": country})
    if basis:
        parts.append({"type": "equals", "key": "BASIS_OF_RECORD", "value": basis})
    if geometry_wkt:
        parts.append({"type": "within", "geometry": geometry_wkt})

    return {"type": "and", "predicates": parts}
