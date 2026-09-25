"""
Aggregator and deduplicator for Bangalore real estate scrapers.
Coordinates Gemini Market Intelligence, Propsoch & 99Acres Portal listings,
and K-RERA Verified Registries into a unified dataset.
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
from src.scrapers.portal_scraper import PortalRealEstateScraper

logger = logging.getLogger("scraper.aggregator")


class RealEstateAggregator:
    def __init__(self):
        self.gemini_scraper = GeminiRealEstateScraper() if GEMINI_API_KEY else None
        self.perplexity_scraper = PerplexityRealEstateScraper() if PERPLEXITY_API_KEY else None
        self.direct_scraper = DirectWebScraper()
        self.portal_scraper = PortalRealEstateScraper()
        self.strategy = SEARCH_STRATEGY

    def run_full_scan(self) -> List[RealEstateProject]:
        """
        Runs comprehensive scan across all Bangalore zones.
        Integrates:
        1. Propsoch live property listings & ratings
        2. 99Acres new project launches
        3. Karnataka RERA verified filings
        4. Gemini & Perplexity AI market intelligence
        """
        all_projects: List[RealEstateProject] = []
        logger.info(f"Starting real estate scan with strategy '{self.strategy}' across {len(BANGALORE_ZONES)} zones...")

        # 1. Fetch live Propsoch Bangalore listings directly from propsoch.com
        try:
            propsoch_projects = self.portal_scraper.scrape_propsoch(limit_per_corridor=6)
            logger.info(f"[Aggregator] Collected {len(propsoch_projects)} listings from Propsoch.com")
            all_projects.extend(propsoch_projects)
        except Exception as e:
            logger.error(f"[Aggregator] Propsoch scraper error: {e}")

        # 2. Fetch 99Acres featured Bangalore project launches
        try:
            acres_projects = self.portal_scraper.scrape_99acres()
            logger.info(f"[Aggregator] Collected {len(acres_projects)} listings from 99Acres.com")
            all_projects.extend(acres_projects)
        except Exception as e:
            logger.error(f"[Aggregator] 99Acres scraper error: {e}")

        # 3. Scan corridor by corridor for K-RERA registry & AI discoveries
        for zone_name, localities in BANGALORE_ZONES.items():
            logger.info(f"--- Scanning Zone: {zone_name} ({', '.join(localities[:3])}...) ---")
            zone_results: List[RealEstateProject] = []

            # A. K-RERA Verified Registry
            try:
                rera_results = self.direct_scraper.scrape_corridor(zone_name, localities)
                zone_results.extend(rera_results)
            except Exception as e:
                logger.error(f"K-RERA registry error for {zone_name}: {e}")

            # B. Gemini AI Market Intelligence (with 429 quota bypass)
            if self.strategy in ("gemini", "hybrid") and self.gemini_scraper:
                try:
                    gemini_results = self.gemini_scraper.scrape_corridor(zone_name, localities)
                    if gemini_results:
                        zone_results.extend(gemini_results)
                except Exception as e:
                    logger.error(f"Gemini scraper error for {zone_name}: {e}")

            # C. Perplexity fallback if configured
            if (self.strategy == "perplexity" or (self.strategy == "hybrid" and len(zone_results) < 5)) and self.perplexity_scraper:
                try:
                    perplexity_results = self.perplexity_scraper.scrape_corridor(zone_name, localities)
                    if perplexity_results:
                        zone_results.extend(perplexity_results)
                except Exception as e:
                    logger.error(f"Perplexity scraper error for {zone_name}: {e}")

            all_projects.extend(zone_results)

        # In-memory deduplication and attribute merging
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
                # Merge RERA number
                if ("pending" in existing.rera_number.lower() or "verified" in existing.rera_number.lower() or not existing.rera_number) and p.rera_number and "pending" not in p.rera_number.lower():
                    existing.rera_number = p.rera_number
                # Merge price
                if (existing.price_range in ("On Request", "On Propsoch") or not existing.price_range) and p.price_range not in ("On Request", "On Propsoch"):
                    existing.price_range = p.price_range
                # Merge possession date
                if (existing.possession_date == "TBA" or not existing.possession_date) and p.possession_date != "TBA":
                    existing.possession_date = p.possession_date
                # If existing doesn't have a portal URL, prioritize portal URL (Propsoch / 99acres)
                if ("propsoch.com" in p.source_url or "99acres.com" in p.source_url) and ("propsoch.com" not in existing.source_url and "99acres.com" not in existing.source_url):
                    existing.source_url = p.source_url
                    existing.source_engine = p.source_engine
                elif not existing.source_url and p.source_url:
                    existing.source_url = p.source_url
                if len(p.key_amenities) > len(existing.key_amenities):
                    existing.key_amenities = p.key_amenities
                existing.last_updated = p.last_updated

        return list(seen.values())
