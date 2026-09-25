"""
Direct Zero-Cost Web Scraper for Bangalore Real Estate Projects.
Requires ZERO API keys. Scrapes live property launch announcements, portal listings,
and K-RERA filings using public web search endpoints and HTML parsing.
"""

import json
import logging
import re
import urllib.parse
from typing import List
import requests
from bs4 import BeautifulSoup
from src.config import TOP_BANGALORE_BUILDERS
from src.models import RealEstateProject

logger = logging.getLogger("scraper.direct")


class DirectWebScraper:
    """
    Scrapes live web search results for Bangalore real estate projects
    without needing any paid AI credits or API keys.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def scrape_corridor(self, zone_name: str, localities: List[str]) -> List[RealEstateProject]:
        """Scrape live search results for a specific corridor in Bangalore."""
        projects: List[RealEstateProject] = []
        logger.info(f"[Direct Scraper] Searching live web listings for {zone_name}...")

        # Search queries targeting major portals & launches
        query_localities = " OR ".join([f'"{loc}"' for loc in localities[:3]])
        query = f'Bangalore new project launch {zone_name} ({query_localities}) site:magicbricks.com OR site:99acres.com OR site:housing.com'
        
        try:
            results = self._search_duckduckgo_lite(query)
            for item in results:
                project = self._extract_project_from_snippet(item, zone_name, localities)
                if project:
                    projects.append(project)
        except Exception as e:
            logger.warning(f"[Direct Scraper] Search failed for {zone_name}: {e}")

        # Also search for top builders in this zone
        for builder in TOP_BANGALORE_BUILDERS[:4]:
            try:
                b_query = f'"{builder}" Bangalore "{localities[0]}" new launch RERA'
                b_results = self._search_duckduckgo_lite(b_query)
                for item in b_results[:2]:
                    project = self._extract_project_from_snippet(item, zone_name, localities, default_builder=builder)
                    if project:
                        projects.append(project)
            except Exception:
                pass

        logger.info(f"[Direct Scraper] Extracted {len(projects)} projects from live web for {zone_name}.")
        return projects

    def _search_duckduckgo_lite(self, query: str) -> List[dict]:
        """Search DuckDuckGo HTML / Lite without API keys."""
        items: List[dict] = []
        encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        
        resp = self.session.get(url, timeout=15)
        if resp.status_code != 200:
            return items

        soup = BeautifulSoup(resp.text, "html.parser")
        results = soup.find_all("div", class_="result")

        for r in results[:10]:
            title_tag = r.find("a", class_="result__snippet") or r.find("a", class_="result__url")
            link_tag = r.find("a", class_="result__url")
            body_tag = r.find("a", class_="result__snippet") or r.find("div", class_="result__snippet")

            title = title_tag.get_text(strip=True) if title_tag else ""
            href = link_tag.get("href", "") if link_tag else ""
            snippet = body_tag.get_text(strip=True) if body_tag else ""

            # Unwrap DDG redirect url if present
            if "uddg=" in href:
                match = re.search(r"uddg=([^&]+)", href)
                if match:
                    href = urllib.parse.unquote(match.group(1))

            if title or snippet:
                items.append({
                    "title": title,
                    "link": href,
                    "snippet": snippet
                })

        return items

    def _extract_project_from_snippet(
        self,
        item: dict,
        zone_name: str,
        localities: List[str],
        default_builder: str = ""
    ) -> RealEstateProject:
        """Parse title and snippet into RealEstateProject model."""
        text = f"{item.get('title', '')} {item.get('snippet', '')}"
        link = item.get("link", "")

        # Try to identify builder
        detected_builder = default_builder
        if not detected_builder:
            for b in TOP_BANGALORE_BUILDERS:
                if b.lower() in text.lower():
                    detected_builder = b
                    break
        if not detected_builder:
            detected_builder = "Reputed Developer"

        # Try to identify project name
        # Look for patterns like "Prestige [Name]", "Sobha [Name]", "Brigade [Name]"
        project_name = ""
        builder_match = re.search(
            rf"({detected_builder}[\s\w\-]+?(?:Apartments|Residency|Park|Heights|Enclave|City|Greens|Villas|Neopolis|Sanctuary|Somerville|Elm|Palm|Grove|Court|Meadows|Woods|Hills))",
            text,
            re.IGNORECASE
        )
        if builder_match:
            project_name = builder_match.group(1).strip()
        else:
            # Fallback to extracting first clean title words
            clean_title = re.sub(r"(Price|Floor Plan|Location|Reviews|RERA|Bangalore|Magicbricks|99acres|Housing).*$", "", item.get("title", ""), flags=re.IGNORECASE)
            clean_title = clean_title.strip(" -|,")
            if len(clean_title) > 5 and len(clean_title) < 50:
                project_name = clean_title

        if not project_name:
            return None

        # Detect locality
        detected_locality = localities[0]
        for loc in localities:
            if loc.lower() in text.lower():
                detected_locality = loc
                break

        # Detect BHK configuration
        bhk_match = re.search(r"(\d(?:\s*,\s*\d)*\s*BHK|\d\s*BHK)", text, re.IGNORECASE)
        config = bhk_match.group(1) if bhk_match else "2 & 3 BHK"

        # Detect Price
        price_match = re.search(r"(₹\s*[\d\.]+\s*(?:Cr|Lakh|L)|Rs\.?\s*[\d\.]+\s*(?:Cr|Lakh|L)|[\d\.]+\s*Cr onwards)", text, re.IGNORECASE)
        price = price_match.group(1) if price_match else "On Request"

        # Detect RERA
        rera_match = re.search(r"(PRM/KA/RERA/[\w/]+)", text, re.IGNORECASE)
        rera_id = rera_match.group(1) if rera_match else "Available on Request"

        return RealEstateProject(
            project_name=project_name,
            builder_name=detected_builder,
            locality=detected_locality,
            zone=zone_name,
            property_type="Apartment" if "villa" not in text.lower() else "Villa",
            configuration=config,
            price_range=price,
            status="Newly Launched",
            rera_number=rera_id,
            possession_date="TBA",
            total_units_or_area="N/A",
            key_amenities="Modern amenities, gated security",
            source_url=link,
            source_engine="Live Web Scraper (Zero-Cost)"
        )
