"""
Tests for scripts/export_map_pins.py - the GeoJSON behind the live map.

build_geojson is pure, so these need no sheet and no network. They pin the two
rules that matter: only rows with a confirmed location become pins, and the
Bengaluru-region scope is derived from the RERA number, never trusted from the
District column.
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.export_map_pins import build_geojson  # noqa: E402

NOW = datetime(2026, 9, 26, 15, 6, 0, tzinfo=timezone.utc)


def row(rera, name="Project", promoter="Promoter", district="Bengaluru Urban",
        lat="", lng="", link="", status=""):
    return [rera, name, promoter, "ACK", district, "url", "Approved", "2026-01-01",
            "Pending", lat, lng, link, status]


class TestBuildGeojson(unittest.TestCase):

    def test_only_located_in_region_rows_become_features(self):
        gj = build_geojson([
            row("PRM/KA/RERA/1251/1/PR/1/1", "Located", lat="12.94", lng="77.74"),
            row("PRM/KA/RERA/1251/2/PR/1/2", "Unlocated"),
            row("PRM/KA/RERA/1261/3/PR/1/3", "Mysuru Located", district="Mysuru", lat="12.30", lng="76.65"),
        ], NOW)
        names = [f["properties"]["name"] for f in gj["features"]]
        self.assertEqual(names, ["Located"])

    def test_geometry_is_lng_lat_order(self):
        """GeoJSON is [longitude, latitude]; getting this backwards puts Bengaluru in the Arabian Sea."""
        gj = build_geojson([row("PRM/KA/RERA/1251/1/PR/1/1", lat="12.940100", lng="77.740900")], NOW)
        self.assertEqual(gj["features"][0]["geometry"]["coordinates"], [77.7409, 12.9401])

    def test_properties_carry_what_the_popup_shows(self):
        gj = build_geojson([row("PRM/KA/RERA/1251/1/PR/1/1", "Prestige Park Grove", "Prestige Estates",
                                lat="12.94", lng="77.74", link="https://maps/x",
                                status="resolved via locationiq 2026-09-26")], NOW)
        p = gj["features"][0]["properties"]
        self.assertEqual(p["name"], "Prestige Park Grove")
        self.assertEqual(p["promoter"], "Prestige Estates")
        self.assertEqual(p["district"], "Bengaluru Urban")
        self.assertEqual(p["rera"], "PRM/KA/RERA/1251/1/PR/1/1")
        self.assertEqual(p["link"], "https://maps/x")
        self.assertEqual(p["status"], "resolved via locationiq 2026-09-26")

    def test_meta_counts_unlocated_rows_without_drawing_them(self):
        gj = build_geojson([
            row("PRM/KA/RERA/1251/1/PR/1/1", lat="12.94", lng="77.74"),
            row("PRM/KA/RERA/1251/2/PR/1/2"),
            row("PRM/KA/RERA/1250/3/PR/1/3", district="Bengaluru Rural"),
            row("PRM/KA/RERA/1261/4/PR/1/4", district="Mysuru"),  # out of region: not counted at all
        ], NOW)
        m = gj["meta"]
        self.assertEqual((m["located"], m["in_region_total"], m["unlocated"]), (1, 3, 2))
        self.assertEqual(m["generated_at"], "2026-09-26T15:06:00Z")
        self.assertEqual(m["districts"], {"Bengaluru Urban": 1})

    def test_district_is_derived_from_rera_not_trusted(self):
        """The registry once stored 4,090 Bengaluru Urban rows as 'Other Karnataka'."""
        gj = build_geojson([row("PRM/KA/RERA/1251/1/PR/1/1", district="Other Karnataka",
                                lat="12.94", lng="77.74")], NOW)
        self.assertEqual(len(gj["features"]), 1)
        self.assertEqual(gj["features"][0]["properties"]["district"], "Bengaluru Urban")

    def test_half_written_or_malformed_coordinates_are_skipped(self):
        gj = build_geojson([
            row("PRM/KA/RERA/1251/1/PR/1/1", lat="12.94"),
            row("PRM/KA/RERA/1251/2/PR/1/2", lng="77.74"),
            row("PRM/KA/RERA/1251/3/PR/1/3", lat="north", lng="east"),
        ], NOW)
        self.assertEqual(gj["features"], [])
        self.assertEqual(gj["meta"]["in_region_total"], 3)

    def test_short_and_blank_rows_are_tolerated(self):
        gj = build_geojson([[], ["", ""], ["PRM/KA/RERA/1251/1/PR/1/1", "Short row"]], NOW)
        self.assertEqual(gj["features"], [])
        self.assertEqual(gj["meta"]["in_region_total"], 1)


class TestListingJoin(unittest.TestCase):
    """Listing_Data rows join onto pins by RERA number; absence is honest, never invented."""

    def _pin(self, rera, name="Project"):
        return row(rera, name, lat="12.94", lng="77.74")

    def _listing(self, rera, typ="Villa", bhk="3, 4 BHK", price="3.8 Cr", poss="May 2027",
                 sale="Available", src="https://builder.example/x", who="research", when="2026-09-26"):
        return [rera, typ, bhk, price, poss, sale, src, who, when, ""]

    def test_listing_fields_are_joined_onto_the_pin(self):
        gj = build_geojson([self._pin("R1")], NOW, [self._listing("R1")])
        p = gj["features"][0]["properties"]
        self.assertEqual(p["type"], "Villa")
        self.assertEqual(p["type_source"], "listing")
        self.assertEqual(p["bhk"], [3, 4])
        self.assertEqual(p["price_lakh"], 380.0)
        self.assertEqual(p["possession"], "May 2027")
        self.assertEqual(p["sale_status"], "Available")
        self.assertEqual(p["source"], "https://builder.example/x")
        self.assertEqual(p["entered_on"], "2026-09-26")

    def test_pin_without_listing_has_no_price_and_a_name_based_type(self):
        gj = build_geojson([self._pin("R1", "KRK Urban Ville Villas")], NOW, [])
        p = gj["features"][0]["properties"]
        self.assertNotIn("price_lakh", p)
        self.assertNotIn("bhk", p)
        self.assertEqual(p["type"], "Villa")
        self.assertEqual(p["type_source"], "name")

    def test_unknown_type_stays_unknown_rather_than_guessed(self):
        gj = build_geojson([self._pin("R1", "MBS VASUDHA")], NOW, [])
        self.assertEqual(gj["features"][0]["properties"]["type"], "Unknown")

    def test_listing_type_overrides_name_type(self):
        gj = build_geojson([self._pin("R1", "Something Villas")], NOW, [self._listing("R1", typ="Apartment")])
        self.assertEqual(gj["features"][0]["properties"]["type"], "Apartment")

    def test_listing_with_unknown_type_does_not_override_a_name_type(self):
        gj = build_geojson([self._pin("R1", "Something Villas")], NOW, [self._listing("R1", typ="Unknown")])
        self.assertEqual(gj["features"][0]["properties"]["type"], "Villa")

    def test_meta_counts_coverage(self):
        gj = build_geojson(
            [self._pin("R1"), self._pin("R2"), self._pin("R3")], NOW,
            [self._listing("R1"), self._listing("R2", price="", bhk="2 BHK")],
        )
        m = gj["meta"]
        self.assertEqual((m["with_listing"], m["with_price"], m["with_bhk"]), (2, 1, 2))

    def test_listing_for_an_unlocated_or_unknown_rera_is_ignored(self):
        gj = build_geojson([self._pin("R1")], NOW, [self._listing("R9")])
        self.assertNotIn("price_lakh", gj["features"][0]["properties"])
        self.assertEqual(gj["meta"]["with_listing"], 0)


if __name__ == "__main__":
    unittest.main()
