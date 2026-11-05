"""Run with QGIS's Python:  python -m unittest discover -s tests -t ..

(predicate.py imports qgis, so a plain system Python will not work.)
"""
import importlib.util
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "gbif_downloader_pkg", os.path.join(_ROOT, "__init__.py"),
    submodule_search_locations=[_ROOT],
)
_pkg = importlib.util.module_from_spec(_spec)
sys.modules["gbif_downloader_pkg"] = _pkg
_spec.loader.exec_module(_pkg)

from qgis.core import QgsApplication  # noqa: E402

_app = QgsApplication([], False)
_app.initQgis()

from gbif_downloader_pkg import compat  # noqa: E402,F401
from gbif_downloader_pkg.gbif_api import COL_CHECKLIST_KEY  # noqa: E402
from gbif_downloader_pkg.tab_action.predicate import build_predicate  # noqa: E402
from gbif_downloader_pkg.tab_action.scientific_name_filter import Taxon  # noqa: E402


def _find(parts, key):
    return [p for p in parts if p.get("key") == key]


class BuildPredicateTests(unittest.TestCase):
    def _parts(self, **kw):
        pred = build_predicate(
            taxa=kw.pop("taxa", []), country=kw.pop("country", ""),
            basis=kw.pop("basis", ""), geometry_wkt=kw.pop("geometry_wkt", ""), **kw)
        self.assertEqual(pred["type"], "and")
        return pred["predicates"]

    def test_base_filters_always_present(self):
        keys = {p.get("key") for p in self._parts()}
        self.assertTrue({"HAS_COORDINATE", "HAS_GEOSPATIAL_ISSUE", "OCCURRENCE_STATUS"} <= keys)

    def test_single_keyed_taxon_uses_equals_with_checklist(self):
        (p,) = _find(self._parts(taxa=[Taxon("Puma concolor", "4QHKG")]), "TAXON_KEY")
        self.assertEqual(p["type"], "equals")
        self.assertEqual(p["value"], "4QHKG")
        self.assertEqual(p["checklistKey"], COL_CHECKLIST_KEY)

    def test_multiple_keyed_taxa_use_in(self):
        parts = self._parts(taxa=[Taxon("a", "1"), Taxon("b", "2")])
        (p,) = _find(parts, "TAXON_KEY")
        self.assertEqual(p["type"], "in")
        self.assertEqual(p["values"], ["1", "2"])

    def test_unkeyed_taxon_falls_back_to_scientific_name(self):
        (p,) = _find(self._parts(taxa=[Taxon("Foo bar", "")]), "SCIENTIFIC_NAME")
        self.assertEqual(p["value"], "Foo bar")

    def test_mixed_taxa_combined_with_or(self):
        parts = self._parts(taxa=[Taxon("a", "1"), Taxon("Foo bar", "")])
        ors = [p for p in parts if p.get("type") == "or"]
        self.assertEqual(len(ors), 1)
        self.assertEqual(len(ors[0]["predicates"]), 2)

    def test_country_and_basis_list_vs_scalar(self):
        parts = self._parts(country=["KE", "TZ"], basis="HUMAN_OBSERVATION")
        self.assertEqual(_find(parts, "COUNTRY")[0]["type"], "in")
        self.assertEqual(_find(parts, "BASIS_OF_RECORD")[0]["type"], "equals")


if __name__ == "__main__":
    unittest.main()
