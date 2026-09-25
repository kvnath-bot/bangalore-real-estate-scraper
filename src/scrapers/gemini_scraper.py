"""
Gemini search-grounded and market intelligence scraper for Bangalore real estate projects.
Uses Google GenAI SDK (client.models.generate_content) with multi-model fallback (gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-flash).
Gracefully handles free-tier 429 quota limits by automatically falling back to standard generation.
"""

import json
import logging
import re
from typing import List
from src.config import GEMINI_API_KEY
from src.models import RealEstateProject

logger = logging.getLogger("scraper.gemini")

CANDIDATE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]

SYSTEM_PROMPT = """
You are a senior real estate market analyst specialized in the Bangalore (Bengaluru), India property market.
Identify verified newly launched, recently announced, pre-launch, and K-RERA registered residential & commercial projects in Bangalore.

You MUST return strictly a valid JSON array of objects without markdown formatting or code blocks.
Each object must contain the following fields:
- "project_name": string (official project name, e.g. "Prestige Somerville")
- "builder_name": string (e.g. "Prestige Group", "Sobha", "Brigade", "Godrej", "Assetz")
- "locality": string (e.g. "Whitefield", "Sarjapur Road", "Hebbal", "Devanahalli")
- "zone": string ("East Bangalore", "North Bangalore", "South Bangalore", "West Bangalore", or "Central Bangalore")
- "property_type": string ("Apartment", "Villa", "Row House", "Plotted Development", "Commercial")
- "configuration": string (e.g. "2, 3 & 4 BHK", "3 & 4 BHK Luxury Apartments", "Plots: 1200-2400 sq.ft")
- "price_range": string (e.g. "₹85 L - 1.9 Cr", "₹2.2 Cr onwards", "₹7,500/sq.ft")
- "status": string ("Newly Launched", "Pre-Launch", "Under Construction", "Ready to Move")
- "rera_number": string (e.g. "PRM/KA/RERA/1251/...", or "Pending / Applied")
- "possession_date": string (e.g. "Dec 2028", "Q4 2027")
- "total_units_or_area": string (e.g. "6.5 Acres / 300 Units")
- "key_amenities": string (e.g. "Lake view, 50,000 sq ft clubhouse, close to metro")
- "source_url": string (source link or developer website)
"""


class GeminiRealEstateScraper:
    def __init__(self, api_key: str = GEMINI_API_KEY):
        self.api_key = api_key
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
            logger.warning("Gemini API key is not configured.")
            return []

        localities_str = ", ".join(localities)
        prompt = f"""
Find newly launched, recently announced, or newly K-RERA registered real estate projects in {zone_name} (especially in {localities_str}), Bangalore.
Search for developer launches (such as Prestige, Sobha, Brigade, Godrej, Assetz, Puravankara, Rohan, Birla, etc.), RERA registrations, and top property portal announcements.

Extract at least 6 to 10 distinct, verified real estate projects in this corridor with their launch details, RERA numbers, pricing, and possession timelines.
Return strictly a JSON array of objects conforming to the system prompt specification.
"""
        # Try candidate models
        for model_name in CANDIDATE_MODELS:
            # Attempt 1: With Google Search Tool Grounding
            projects = self._try_generate(model_name, prompt, zone_name, with_search=True)
            if projects:
                return projects

            # Attempt 2: If Search Grounding hit quota (429), try standard model generation
            logger.info(f"Retrying {model_name} without search grounding tool to bypass 429 quota limits...")
            projects = self._try_generate(model_name, prompt, zone_name, with_search=False)
            if projects:
                return projects

        return []

    def _try_generate(self, model_name: str, prompt: str, zone_name: str, with_search: bool) -> List[RealEstateProject]:
        """Calls client.models.generate_content with or without search grounding."""
        try:
            from google.genai import types

            config_args = {"temperature": 0.2}
            if with_search:
                config_args["tools"] = [types.Tool(google_search=types.GoogleSearch())]

            config = types.GenerateContentConfig(**config_args)
            
            logger.info(f"Calling Gemini {model_name} (search_grounding={with_search}) for {zone_name}...")
            response = self.client.models.generate_content(
                model=model_name,
                contents=f"{SYSTEM_PROMPT}\n\nTask: {prompt}",
                config=config,
            )
            raw_text = response.text or ""
            return self._parse_json_response(raw_text, zone_name, f"Gemini ({model_name})")

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower() or "resource_exhausted" in err_str.lower():
                logger.warning(f"Gemini {model_name} (search={with_search}) hit quota limit: {err_str[:120]}")
            else:
                logger.error(f"Gemini error with {model_name}: {e}")
            return []

    def _parse_json_response(self, text: str, default_zone: str, engine_label: str) -> List[RealEstateProject]:
        """Safely parse LLM output into RealEstateProject objects."""
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
                        builder_name=item.get("builder_name", "Reputed Developer").strip(),
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
                        source_engine=engine_label
                    )
                    projects.append(project)
        except Exception as e:
            logger.warning(f"Failed to parse JSON from Gemini output: {e}\nRaw output sample: {text[:200]}")

        return projects
