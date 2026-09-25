"""
Perplexity Sonar search-grounded scraper for Bangalore real estate projects.
Uses Perplexity's live web search API (sonar model) for real-time citations and launch tracking.
"""

import json
import logging
import re
from typing import List
import requests
from src.config import PERPLEXITY_API_KEY
from src.models import RealEstateProject

logger = logging.getLogger("scraper.perplexity")

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"

SYSTEM_PROMPT = """
You are a senior real estate research analyst specialized in Bangalore (Bengaluru) property developments.
Search the live web for the latest real estate project launches, pre-launches, K-RERA filings, and ongoing projects across Bangalore.
Return only a valid JSON array of objects without code blocks or markdown commentary.
Each object must have:
- "project_name": string
- "builder_name": string
- "locality": string (e.g., Whitefield, Sarjapur, Devanahalli, Kanakapura Road)
- "zone": string ("East Bangalore", "North Bangalore", "South Bangalore", "West Bangalore", or "Central Bangalore")
- "property_type": string (Apartment, Villa, Plotted Development, Penthouse)
- "configuration": string (e.g., 2 & 3 BHK, 4 BHK Villa, 30x40 Plots)
- "price_range": string (e.g., ₹90 L - 2.1 Cr, ₹7,800/sq.ft)
- "status": string ("Newly Launched", "Pre-Launch", "Under Construction", "Ready to Move")
- "rera_number": string (Karnataka RERA number PRM/KA/RERA/..., or "Pending")
- "possession_date": string (e.g., Dec 2028, 2027)
- "total_units_or_area": string (e.g., 400 Units / 8.5 Acres)
- "key_amenities": string (Highlights and key amenities)
- "source_url": string (source link or developer website)
"""


class PerplexityRealEstateScraper:
    def __init__(self, api_key: str = PERPLEXITY_API_KEY, model: str = "sonar"):
        self.api_key = api_key
        self.model = model

    def scrape_corridor(self, zone_name: str, localities: List[str]) -> List[RealEstateProject]:
        """Query Perplexity Sonar with search grounding for a specific Bangalore zone."""
        if not self.api_key:
            logger.warning("Perplexity API key is not configured.")
            return []

        localities_str = ", ".join(localities)
        user_prompt = f"""
Find new real estate project launches, newly announced residential projects, and recent K-RERA registrations in {zone_name} (localities: {localities_str}), Bangalore.
Focus on top builders (Prestige, Sobha, Brigade, Godrej, Assetz, Puravankara, Rohan, Total Environment, Birla, etc.) launched in the last 3 to 6 months.

Extract at least 5 to 8 distinct real estate projects with verified pricing, builder, RERA ID, and location details.
Return strictly a valid JSON array conforming to the system prompt.
"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2,
        }

        try:
            logger.info(f"Querying Perplexity API for {zone_name}...")
            resp = requests.post(PERPLEXITY_API_URL, json=payload, headers=headers, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                raw_text = data["choices"][0]["message"]["content"]
                citations = data.get("citations", [])
                default_url = citations[0] if citations else ""
                return self._parse_json_response(raw_text, zone_name, default_url)
            else:
                logger.error(f"Perplexity API failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Error querying Perplexity API for {zone_name}: {e}")

        return []

    def _parse_json_response(self, text: str, default_zone: str, default_url: str) -> List[RealEstateProject]:
        projects: List[RealEstateProject] = []
        if not text:
            return projects

        clean_text = text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        elif clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()

        match = re.search(r"\[.*\]", clean_text, re.DOTALL)
        if match:
            clean_text = match.group(0)

        try:
            items = json.loads(clean_text)
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict) or "project_name" not in item:
                        continue
                    project = RealEstateProject(
                        project_name=item.get("project_name", "").strip(),
                        builder_name=item.get("builder_name", "Unknown Developer").strip(),
                        locality=item.get("locality", "Bangalore").strip(),
                        zone=item.get("zone", default_zone).strip(),
                        property_type=item.get("property_type", "Apartment").strip(),
                        configuration=item.get("configuration", "N/A").strip(),
                        price_range=item.get("price_range", "On Request").strip(),
                        status=item.get("status", "Newly Launched").strip(),
                        rera_number=item.get("rera_number", "Pending / Applied").strip(),
                        possession_date=item.get("possession_date", "TBA").strip(),
                        total_units_or_area=item.get("total_units_or_area", "N/A").strip(),
                        key_amenities=item.get("key_amenities", "").strip(),
                        source_url=item.get("source_url") or default_url,
                        source_engine="Perplexity Sonar Web Search"
                    )
                    projects.append(project)
        except Exception as e:
            logger.warning(f"Failed to parse JSON from Perplexity output: {e}\nRaw output sample: {text[:200]}")

        return projects
