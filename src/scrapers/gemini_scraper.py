"""
Gemini 3.8 Flash search-grounded scraper for Bangalore real estate projects.
Leverages Google Search grounding for real-time, live web discoveries with zero cost on Google AI Studio free tier.
"""

import json
import logging
import re
from typing import List
from src.config import GEMINI_API_KEY, GEMINI_MODEL
from src.models import RealEstateProject

logger = logging.getLogger("scraper.gemini")

SYSTEM_PROMPT = """
You are a specialized real estate market intelligence analyst focusing on the Bangalore (Bengaluru), India property market.
Your task is to search live web data for recent residential and commercial real estate projects, new launches, pre-launches, RERA registered projects, and major builder announcements across Bangalore.

Always return a strictly valid JSON array of objects without markdown formatting or code blocks.
Each object must contain the following fields:
- "project_name": string (official project name, e.g. "Prestige Somerville")
- "builder_name": string (e.g. "Prestige Group", "Sobha", "Brigade")
- "locality": string (e.g. "Whitefield", "Sarjapur Road", "Hebbal", "Devanahalli")
- "zone": string ("East Bangalore", "North Bangalore", "South Bangalore", "West Bangalore", or "Central Bangalore")
- "property_type": string ("Apartment", "Villa", "Row House", "Plotted Development", "Commercial")
- "configuration": string (e.g. "2, 3 & 4 BHK", "3 & 4 BHK Luxury Apartments", "Plots: 1200-2400 sq.ft")
- "price_range": string (e.g. "₹85 L - 1.9 Cr", "₹2.2 Cr onwards", "₹7,500/sq.ft")
- "status": string ("Newly Launched", "Pre-Launch", "Under Construction", "Ready to Move")
- "rera_number": string (e.g. "PRM/KA/RERA/1251/...", or "Pending / Applied" if not found)
- "possession_date": string (e.g. "Dec 2028", "Q4 2027", "Ready")
- "total_units_or_area": string (e.g. "6.5 Acres / 300 Units", "12 Acres")
- "key_amenities": string (e.g. "Lake view, 50,000 sq ft clubhouse, close to metro")
- "source_url": string (source link or developer website)
"""


class GeminiRealEstateScraper:
    def __init__(self, api_key: str = GEMINI_API_KEY, model: str = GEMINI_MODEL):
        self.api_key = api_key
        self.model = model
        self.client = None
        if self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Could not initialize google-genai client: {e}")

    def scrape_corridor(self, zone_name: str, localities: List[str]) -> List[RealEstateProject]:
        """Scrape new launches and project approvals for a specific Bangalore zone."""
        if not self.client:
            logger.error("Gemini API key is not configured or client initialization failed.")
            return []

        localities_str = ", ".join(localities)
        prompt = f"""
Find newly launched, recently announced, or newly K-RERA registered real estate projects in {zone_name} (especially in {localities_str}), Bangalore.
Search for official developer launches (such as Prestige, Sobha, Brigade, Godrej, Assetz, Puravankara, Rohan, Birla, etc.), RERA registrations, and top property portal announcements.

Extract at least 5 to 10 distinct, verified real estate projects in this corridor with their latest launch details, RERA numbers, pricing, and possession timelines.
Return strictly a JSON array of objects conforming to the system prompt specification.
"""
        try:
            logger.info(f"Querying Gemini Search Grounding for {zone_name}...")
            # Use interactions.create with Google Search grounding tool
            interaction = self.client.interactions.create(
                model=self.model,
                input=f"{SYSTEM_PROMPT}\n\nTask: {prompt}",
                tools=[{"type": "google_search"}]
            )
            raw_text = interaction.output_text or ""
            return self._parse_json_response(raw_text, zone_name)
        except Exception as e:
            logger.error(f"Error executing Gemini search grounding for {zone_name}: {e}")
            # Try REST API fallback if SDK throws error
            return self._rest_fallback(prompt, zone_name)

    def _rest_fallback(self, prompt: str, zone_name: str) -> List[RealEstateProject]:
        """Fallback via standard Gemini REST generateContent API if interaction endpoint is unavailable."""
        import requests
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\nTask: {prompt}"}]}],
            "tools": [{"google_search": {}}]
        }
        try:
            logger.info(f"Attempting REST generateContent fallback for {zone_name}...")
            resp = requests.post(url, json=payload, timeout=45)
            if resp.status_code == 200:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return self._parse_json_response(text, zone_name)
            else:
                logger.error(f"REST fallback failed with status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"REST fallback error: {e}")
        return []

    def _parse_json_response(self, text: str, default_zone: str) -> List[RealEstateProject]:
        """Safely parse LLM output into RealEstateProject objects."""
        projects: List[RealEstateProject] = []
        if not text:
            return projects

        # Strip markdown fences if present
        clean_text = text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        elif clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()

        # Locate first '[' and last ']'
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
                        source_url=item.get("source_url", "").strip(),
                        source_engine="Gemini Google Search Grounding"
                    )
                    projects.append(project)
        except Exception as e:
            logger.warning(f"Failed to parse JSON from Gemini output: {e}\nRaw output sample: {text[:200]}")

        return projects
