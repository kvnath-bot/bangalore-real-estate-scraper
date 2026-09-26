"""
Test suite for Bangalore Real Estate Scraper components.
Tests data models, deduplication logic, JSON parsing, and sheet formatting.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.config import GEOCODE_MAX_PER_RUN
from src.models import KRERARawProject, RealEstateProject, ScrapeRunSummary
from src.scrapers.gemini_scraper import GeminiRealEstateScraper
from src.scrapers.perplexity_scraper import PerplexityRealEstateScraper
from src.scrapers.aggregator import RealEstateAggregator


class TestRealEstateScraperComponents(unittest.TestCase):

    def test_project_model_creation(self):
        project = RealEstateProject(
            project_name="Prestige Park Grove",
            builder_name="Prestige Group",
            locality="Whitefield",
            zone="East Bangalore",
            property_type="Apartment & Villa",
            configuration="1, 2, 3 & 4 BHK",
            price_range="₹75 L - 2.5 Cr",
            status="Under Construction",
            rera_number="PRM/KA/RERA/1251/446/PR/100823/006141",
            possession_date="Dec 2027",
            total_units_or_area="71 Acres / 3627 Units",
            key_amenities="Clubhouse, Metro proximity, 80% open green space",
            source_url="https://prestigeconstructions.com",
            source_engine="Gemini Google Search Grounding"
        )
        self.assertEqual(project.project_name, "Prestige Park Grove")
        self.assertTrue(project.deduplication_key().startswith("rera:"))
        row = project.to_sheet_row()
        self.assertEqual(len(row), len(RealEstateProject.sheet_headers()))

    def test_deduplication_fallback_to_name(self):
        project = RealEstateProject(
            project_name="Sobha Neopolis",
            builder_name="Sobha Limited",
            locality="Panathur Road",
            rera_number="Pending"
        )
        key = project.deduplication_key()
        self.assertTrue(key.startswith("name:"))
        self.assertIn("sobhaneopolis", key)
        self.assertIn("sobhalimited", key)
        # The key is normalised: lowercased, with spaces and punctuation stripped.
        self.assertEqual(key, "name:sobhaneopolis|sobhalimited")
        self.assertNotIn(" ", key)

    def test_gemini_json_parser(self):
        sample_json_text = """
        ```json
        [
          {
            "project_name": "Brigade Sanctuary",
            "builder_name": "Brigade Group",
            "locality": "Sarjapur Road",
            "zone": "East Bangalore",
            "property_type": "Apartment",
            "configuration": "1, 3 & 4 BHK",
            "price_range": "₹92 L - 2.2 Cr",
            "status": "Newly Launched",
            "rera_number": "PRM/KA/RERA/1251/308/PR/141223/006479",
            "possession_date": "Dec 2028",
            "total_units_or_area": "14 Acres",
            "key_amenities": "Thermal pool, forest trail",
            "source_url": "https://brigadegroup.com"
          }
        ]
        ```
        """
        scraper = GeminiRealEstateScraper(api_key="")
        projects = scraper._parse_json_response(
            sample_json_text, "East Bangalore", "Gemini (gemini-3.8-flash)"
        )
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].project_name, "Brigade Sanctuary")
        self.assertEqual(projects[0].locality, "Sarjapur Road")
        self.assertEqual(projects[0].zone, "East Bangalore")
        self.assertEqual(projects[0].source_engine, "Gemini (gemini-3.8-flash)")

    def test_aggregator_merging(self):
        p1 = RealEstateProject(
            project_name="Godrej Athena",
            builder_name="Godrej Properties",
            locality="Indiranagar Extension",
            price_range="On Request",
            rera_number="Pending"
        )
        p2 = RealEstateProject(
            project_name="Godrej Athena",
            builder_name="Godrej Properties",
            locality="Indiranagar Extension",
            price_range="₹2.5 Cr onwards",
            rera_number="PRM/KA/RERA/1251/310/PR/230123/005655"
        )
        aggregator = RealEstateAggregator()
        merged = aggregator._deduplicate_and_merge([p1, p2])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].price_range, "₹2.5 Cr onwards")
        self.assertEqual(merged[0].rera_number, "PRM/KA/RERA/1251/310/PR/230123/005655")

    def test_aggregator_merging_is_order_independent(self):
        """The RERA-bearing record may arrive either first or second."""
        def pair():
            with_rera = RealEstateProject(
                project_name="Godrej Athena",
                builder_name="Godrej Properties",
                locality="Indiranagar Extension",
                price_range="₹2.5 Cr onwards",
                rera_number="PRM/KA/RERA/1251/310/PR/230123/005655",
            )
            without_rera = RealEstateProject(
                project_name="Godrej Athena",
                builder_name="Godrej Properties",
                locality="Indiranagar Extension",
                price_range="On Request",
                rera_number="Pending",
            )
            return with_rera, without_rera

        aggregator = RealEstateAggregator()
        with_rera, without_rera = pair()
        merged = aggregator._deduplicate_and_merge([with_rera, without_rera])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].rera_number, "PRM/KA/RERA/1251/310/PR/230123/005655")
        self.assertEqual(merged[0].price_range, "₹2.5 Cr onwards")

    def test_aggregator_keeps_genuinely_different_projects(self):
        """Dual-key matching must not collapse distinct projects together."""
        a = RealEstateProject(
            project_name="Godrej Athena",
            builder_name="Godrej Properties",
            locality="Indiranagar Extension",
            rera_number="PRM/KA/RERA/1251/310/PR/230123/005655",
        )
        b = RealEstateProject(
            project_name="Godrej Woodscapes",
            builder_name="Godrej Properties",
            locality="Budigere Cross",
            rera_number="PRM/KA/RERA/1251/309/PR/210101/003838",
        )
        c = RealEstateProject(
            project_name="Brigade Sanctuary",
            builder_name="Brigade Group",
            locality="Sarjapur Road",
            rera_number="Pending",
        )
        merged = RealEstateAggregator()._deduplicate_and_merge([a, b, c])
        self.assertEqual(len(merged), 3)

    def test_identity_keys_shape(self):
        pending = RealEstateProject(
            project_name="Sobha Neopolis",
            builder_name="Sobha Limited",
            locality="Panathur Road",
            rera_number="Pending",
        )
        registered = RealEstateProject(
            project_name="Sobha Neopolis",
            builder_name="Sobha Limited",
            locality="Panathur Road",
            rera_number="PRM/KA/RERA/1251/446/PR/100823/006141",
        )
        # A record without a real RERA number is known only by name...
        self.assertEqual(pending.identity_keys(), ["name:sobhaneopolis|sobhalimited"])
        # ...while a registered one is known by both, RERA taking precedence.
        self.assertEqual(
            registered.identity_keys(),
            [
                "rera:prmkarera1251446pr100823006141",
                "name:sobhaneopolis|sobhalimited",
            ],
        )
        self.assertEqual(registered.deduplication_key(), registered.rera_key())
        self.assertEqual(pending.deduplication_key(), pending.name_key())

    def test_is_valid_rera_rejects_placeholders(self):
        for placeholder in ("", "Pending", "Pending / Not Specified", "Not Specified",
                            "To be verified", "N/A", "TBA"):
            self.assertFalse(
                RealEstateProject.is_valid_rera(placeholder),
                f"{placeholder!r} should not count as a real RERA number",
            )
        self.assertTrue(
            RealEstateProject.is_valid_rera("PRM/KA/RERA/1251/446/PR/100823/006141")
        )


class TestKRERARawGeoColumns(unittest.TestCase):
    """Covers the Latitude / Longitude / Map Pin Link columns and geocode helpers."""

    def _raw(self, **overrides) -> KRERARawProject:
        payload = dict(
            rera_number="PRM/KA/RERA/1251/446/PR/100823/006141",
            project_name="Prestige Park Grove",
            promoter_name="Prestige Estates Projects Ltd",
            district="Bengaluru Urban",
        )
        payload.update(overrides)
        return KRERARawProject(**payload)

    def test_sheet_row_matches_headers(self):
        row = self._raw().to_sheet_row()
        self.assertEqual(len(row), len(KRERARawProject.sheet_headers()))
        self.assertEqual(
            KRERARawProject.sheet_headers()[-3:],
            ["Latitude", "Longitude", "Map Pin Link"],
        )

    def test_geocode_query_strips_district_annotation(self):
        raw = self._raw(district="Ramanagara (BMRDA)")
        self.assertEqual(
            raw.geocode_query(),
            "Prestige Park Grove, Ramanagara, Karnataka, India",
        )

    def test_geocode_query_falls_back_to_bengaluru(self):
        raw = self._raw(district="Other Karnataka")
        self.assertIn("Bengaluru, Karnataka, India", raw.geocode_query())

    def test_map_pin_uses_coordinates_when_available(self):
        raw = self._raw(latitude="12.940100", longitude="77.740900")
        self.assertEqual(
            raw.build_map_pin_link(),
            "https://www.google.com/maps/search/?api=1&query=12.940100,77.740900",
        )

    def test_map_pin_falls_back_to_name_search(self):
        link = self._raw().build_map_pin_link()
        self.assertTrue(link.startswith("https://www.google.com/maps/search/?api=1&query="))
        self.assertIn("Prestige+Park+Grove", link)
        self.assertNotIn(" ", link)

    def test_sheet_row_carries_coordinates_and_pin(self):
        row = self._raw(latitude="12.940100", longitude="77.740900").to_sheet_row()
        self.assertEqual(row[9], "12.940100")
        self.assertEqual(row[10], "77.740900")
        self.assertIn("12.940100,77.740900", row[11])


class TestGeocoder(unittest.TestCase):
    """Cache, per-run budget and region filtering - no network calls."""

    def _geocoder(self, tmpdir):
        from src.geocoder import Geocoder
        return Geocoder(cache_file=Path(tmpdir) / "cache.json")

    def test_cache_hit_does_not_consume_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = self._geocoder(tmp)
            g.cache["prestige park grove, bengaluru urban, karnataka, india"] = [12.9401, 77.7409]
            coords = g.geocode_address("Prestige Park Grove, Bengaluru Urban, Karnataka, India")
            self.assertEqual(coords, (12.9401, 77.7409))
            self.assertEqual(g.lookups_used, 0)

    def test_cached_miss_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = self._geocoder(tmp)
            g.cache["ghost project, bengaluru urban, karnataka, india"] = None
            self.assertIsNone(g.geocode_address("Ghost Project, Bengaluru Urban, Karnataka, India"))
            self.assertEqual(g.lookups_used, 0)

    def test_budget_exhaustion_returns_none_without_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = self._geocoder(tmp)
            g.lookups_used = GEOCODE_MAX_PER_RUN
            called = []
            g._lookup_nominatim = lambda addr: called.append(addr)
            self.assertIsNone(g.geocode_address("Some Uncached Project, Bengaluru"))
            self.assertEqual(called, [])

    def test_out_of_region_match_is_discarded_and_cached_as_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = self._geocoder(tmp)
            g.use_google = False
            g._lookup_nominatim = lambda addr: (28.6139, 77.2090)  # New Delhi
            self.assertIsNone(g.geocode_address("Confusingly Named Project, Bengaluru"))
            self.assertIsNone(g.cache["confusingly named project, bengaluru"])

    def test_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "cache.json"
            from src.geocoder import Geocoder
            g = Geocoder(cache_file=cache_file)
            g.use_google = False
            g._lookup_nominatim = lambda addr: (12.9401, 77.7409)
            g.geocode_address("Prestige Park Grove, Bengaluru")
            g.save_cache()
            reloaded = Geocoder(cache_file=cache_file)
            self.assertEqual(
                reloaded.geocode_address("Prestige Park Grove, Bengaluru"),
                (12.9401, 77.7409),
            )
            self.assertEqual(reloaded.lookups_used, 0)


class TestMapColumnRangeBatching(unittest.TestCase):
    """update_krera_map_columns must merge contiguous rows into single ranges."""

    def _manager(self):
        from src.gsheet_manager import GoogleSheetManager
        mgr = GoogleSheetManager.__new__(GoogleSheetManager)
        mgr.krera_raw_sheet = mock.MagicMock()
        return mgr

    def test_contiguous_rows_collapse_into_one_range(self):
        mgr = self._manager()
        written = mgr.update_krera_map_columns({
            2: ["12.1", "77.1", "l2"],
            3: ["12.2", "77.2", "l3"],
            4: ["12.3", "77.3", "l4"],
        })
        payload = mgr.krera_raw_sheet.batch_update.call_args[0][0]
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["range"], "J2:L4")
        self.assertEqual(written, 3)

    def test_gaps_produce_separate_ranges(self):
        mgr = self._manager()
        mgr.update_krera_map_columns({
            2: ["12.1", "77.1", "l2"],
            3: ["12.2", "77.2", "l3"],
            9: ["12.9", "77.9", "l9"],
        })
        payload = mgr.krera_raw_sheet.batch_update.call_args[0][0]
        self.assertEqual([r["range"] for r in payload], ["J2:L3", "J9:L9"])

    def test_empty_input_makes_no_api_call(self):
        mgr = self._manager()
        self.assertEqual(mgr.update_krera_map_columns({}), 0)
        mgr.krera_raw_sheet.batch_update.assert_not_called()


class TestSheetSharing(unittest.TestCase):
    def _manager(self):
        from src.gsheet_manager import GoogleSheetManager
        mgr = GoogleSheetManager.__new__(GoogleSheetManager)
        mgr.spreadsheet = mock.MagicMock()
        return mgr

    def test_shares_each_address_with_requested_role(self):
        mgr = self._manager()
        shared = mgr.share_with_emails(["a@gmail.com", "b@gmail.com"], role="reader", notify=False)
        self.assertEqual(shared, ["a@gmail.com", "b@gmail.com"])
        self.assertEqual(mgr.spreadsheet.share.call_count, 2)
        _, kwargs = mgr.spreadsheet.share.call_args
        self.assertEqual(kwargs["role"], "reader")
        self.assertEqual(kwargs["perm_type"], "user")

    def test_unsupported_role_falls_back_to_writer(self):
        mgr = self._manager()
        mgr.share_with_emails(["a@gmail.com"], role="admin")
        _, kwargs = mgr.spreadsheet.share.call_args
        self.assertEqual(kwargs["role"], "writer")

    def test_one_failure_does_not_block_the_rest(self):
        mgr = self._manager()
        mgr.spreadsheet.share.side_effect = [Exception("no such user"), None]
        shared = mgr.share_with_emails(["bad@gmail.com", "good@gmail.com"])
        self.assertEqual(shared, ["good@gmail.com"])

    def test_no_recipients_is_a_no_op(self):
        mgr = self._manager()
        self.assertEqual(mgr.share_with_emails([]), [])
        mgr.spreadsheet.share.assert_not_called()


class TestSheetSyncDeduplication(unittest.TestCase):
    """sync_projects must not re-append a project already present in the sheet."""

    def _manager(self, existing_rows):
        from src.gsheet_manager import GoogleSheetManager
        mgr = GoogleSheetManager.__new__(GoogleSheetManager)
        mgr.projects_sheet = mock.MagicMock()
        mgr.projects_sheet.get_all_values.return_value = (
            [RealEstateProject.sheet_headers()] + existing_rows
        )
        return mgr

    def _row(self, name, builder, rera):
        return RealEstateProject(
            project_name=name, builder_name=builder, locality="X", rera_number=rera
        ).to_sheet_row()

    def test_registered_sheet_row_matches_incoming_record_without_rera(self):
        """The regression: sheet has the RERA, this run found it without one."""
        mgr = self._manager([
            self._row("Godrej Athena", "Godrej Properties", "PRM/KA/RERA/1251/310/PR/230123/005655"),
        ])
        incoming = RealEstateProject(
            project_name="Godrej Athena",
            builder_name="Godrej Properties",
            locality="Indiranagar Extension",
            rera_number="Pending",
        )
        new_added, matched = mgr.sync_projects([incoming])
        self.assertEqual((new_added, matched), (0, 1))
        mgr.projects_sheet.append_rows.assert_not_called()

    def test_pending_sheet_row_matches_incoming_registered_record(self):
        """And the mirror case: sheet row is Pending, this run has the RERA."""
        mgr = self._manager([self._row("Godrej Athena", "Godrej Properties", "Pending")])
        incoming = RealEstateProject(
            project_name="Godrej Athena",
            builder_name="Godrej Properties",
            locality="Indiranagar Extension",
            rera_number="PRM/KA/RERA/1251/310/PR/230123/005655",
        )
        new_added, matched = mgr.sync_projects([incoming])
        self.assertEqual((new_added, matched), (0, 1))

    def test_genuinely_new_project_is_appended_once(self):
        mgr = self._manager([self._row("Godrej Athena", "Godrej Properties", "Pending")])
        incoming = RealEstateProject(
            project_name="Brigade Sanctuary",
            builder_name="Brigade Group",
            locality="Sarjapur Road",
            rera_number="PRM/KA/RERA/1251/308/PR/141223/006479",
        )
        new_added, matched = mgr.sync_projects([incoming])
        self.assertEqual((new_added, matched), (1, 0))
        appended = mgr.projects_sheet.append_rows.call_args[0][0]
        self.assertEqual(len(appended), 1)
        self.assertEqual(appended[0][0], "Brigade Sanctuary")

    def test_duplicate_within_one_batch_is_appended_once(self):
        mgr = self._manager([])
        a = RealEstateProject(
            project_name="Brigade Sanctuary", builder_name="Brigade Group",
            locality="Sarjapur Road", rera_number="PRM/KA/RERA/1251/308/PR/141223/006479",
        )
        b = RealEstateProject(
            project_name="Brigade Sanctuary", builder_name="Brigade Group",
            locality="Sarjapur Road", rera_number="Pending",
        )
        new_added, matched = mgr.sync_projects([a, b])
        self.assertEqual((new_added, matched), (1, 1))

    def test_blank_sheet_rows_are_ignored(self):
        mgr = self._manager([[], ["", "", ""]])
        incoming = RealEstateProject(
            project_name="Brigade Sanctuary", builder_name="Brigade Group",
            locality="Sarjapur Road", rera_number="Pending",
        )
        new_added, _ = mgr.sync_projects([incoming])
        self.assertEqual(new_added, 1)


if __name__ == "__main__":
    unittest.main()
