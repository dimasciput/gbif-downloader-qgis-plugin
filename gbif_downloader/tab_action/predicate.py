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
