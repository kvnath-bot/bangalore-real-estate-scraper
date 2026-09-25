"""
Test suite for Bangalore Real Estate Scraper components.
Tests data models, deduplication logic, JSON parsing, and sheet formatting.
"""

import unittest
from src.models import RealEstateProject, ScrapeRunSummary
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
        self.assertIn("sobhawithoutspace", key.replace(" ", "") or key)

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
        projects = scraper._parse_json_response(sample_json_text, "East Bangalore")
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].project_name, "Brigade Sanctuary")
        self.assertEqual(projects[0].locality, "Sarjapur Road")

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


if __name__ == "__main__":
    unittest.main()
