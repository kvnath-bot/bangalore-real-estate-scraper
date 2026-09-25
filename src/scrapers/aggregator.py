"""
Aggregator and deduplicator for Bangalore real estate scrapers.
Coordinates Gemini Search, Perplexity Sonar, and Direct Web Scraping into a resilient pipeline.
"""

import logging
from typing import Dict, List
from src.config import (
    BANGALORE_ZONES,
    GEMINI_API_KEY,
    PERPLEXITY_API_KEY,
    SEARCH_STRATEGY,
)
from src.models import RealEstateProject
from src.scrapers.direct_scraper import DirectWebScraper
from src.scrapers.gemini_scraper import GeminiRealEstateScraper
from src.scrapers.perplexity_scraper import PerplexityRealEstateScraper

logger = logging.getLogger("scraper.aggregator")


class RealEstateAggregator:
    def __init__(self):
        self.gemini_scraper = GeminiRealEstateScraper() if GEMINI_API_KEY else None
        self.perplexity_scraper = PerplexityRealEstateScraper() if PERPLEXITY_API_KEY else None
        self.direct_scraper = DirectWebScraper()
        self.strategy = SEARCH_STRATEGY

    def run_full_scan(self) -> List[RealEstateProject]:
        """
        Runs comprehensive scan across all Bangalore zones.
        Combines AI and direct web scraping, deduplicates, and merges attributes.
        """
        all_projects: List[RealEstateProject] = []
        logger.info(f"Starting real estate scan with strategy '{self.strategy}' across {len(BANGALORE_ZONES)} zones...")

        for zone_name, localities in BANGALORE_ZONES.items():
            logger.info(f"--- Scanning Zone: {zone_name} ({', '.join(localities[:3])}...) ---")
            zone_results: List[RealEstateProject] = []

            # 1. Strategy: Gemini Primary
            if self.strategy in ("gemini", "hybrid") and self.gemini_scraper:
                try:
                    gemini_results = self.gemini_scraper.scrape_corridor(zone_name, localities)
                    if gemini_results:
                        logger.info(f"Gemini found {len(gemini_results)} projects in {zone_name}.")
                        zone_results.extend(gemini_results)
                except Exception as e:
                    logger.error(f"Gemini scraper failed for {zone_name}: {e}")

            # 2. Strategy: Perplexity Fallback / Supplemental
            if (self.strategy == "perplexity" or (self.strategy == "hybrid" and len(zone_results) < 4)) and self.perplexity_scraper:
                try:
                    perplexity_results = self.perplexity_scraper.scrape_corridor(zone_name, localities)
                    if perplexity_results:
                        logger.info(f"Perplexity found {len(perplexity_results)} projects in {zone_name}.")
                        zone_results.extend(perplexity_results)
                except Exception as e:
                    logger.error(f"Perplexity scraper failed for {zone_name}: {e}")

            # 3. Direct Web Scraper (Zero-Cost, No API key needed) - runs if AI yielded few results
            if len(zone_results) < 5:
                logger.info(f"Supplementing {zone_name} with Direct Zero-Cost Web Scraper...")
                try:
                    direct_results = self.direct_scraper.scrape_corridor(zone_name, localities)
                    zone_results.extend(direct_results)
                except Exception as e:
                    logger.error(f"Direct scraper error for {zone_name}: {e}")

            all_projects.extend(zone_results)

        # In-memory deduplication and merging
        unique_projects = self._deduplicate_and_merge(all_projects)
        logger.info(f"Scan complete. Discovered {len(all_projects)} raw records -> {len(unique_projects)} unique projects.")
        return unique_projects

    def _deduplicate_and_merge(self, projects: List[RealEstateProject]) -> List[RealEstateProject]:
        """Merge duplicates into single richer project record."""
        seen: Dict[str, RealEstateProject] = {}

        for p in projects:
            key = p.deduplication_key()
            if key not in seen:
                seen[key] = p
            else:
                existing = seen[key]
                if ("pending" in existing.rera_number.lower() or not existing.rera_number) and p.rera_number and "pending" not in p.rera_number.lower():
                    existing.rera_number = p.rera_number
                if (existing.price_range == "On Request" or not existing.price_range) and p.price_range != "On Request":
                    existing.price_range = p.price_range
                if (existing.possession_date == "TBA" or not existing.possession_date) and p.possession_date != "TBA":
                    existing.possession_date = p.possession_date
                if not existing.source_url and p.source_url:
                    existing.source_url = p.source_url
                if len(p.key_amenities) > len(existing.key_amenities):
                    existing.key_amenities = p.key_amenities
                existing.last_updated = p.last_updated

        return list(seen.values())
