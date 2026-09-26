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


if __name__ == "__main__":
    unittest.main()
