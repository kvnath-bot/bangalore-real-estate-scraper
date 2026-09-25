"""
Gemini market intelligence scraper for Bangalore real estate projects.
Uses Google GenAI SDK (client.models.generate_content) supporting current models:
- gemini-3.8-flash
- gemini-3.5-flash-lite
- gemini-flash-latest
- gemini-3.1-flash-lite

Bypasses free-tier 429 Search Grounding quota limits by falling back to high-throughput standard generation.
"""

import json
import logging
import re
from typing import List
from src.config import GEMINI_API_KEY
from src.models import RealEstateProject

logger = logging.getLogger("scraper.gemini")

CANDIDATE_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
]

SYSTEM_PROMPT = """
You are an expert Indian real estate research analyst specialized in Bangalore (Bengaluru) residential and commercial projects.
Extract verified real estate projects, new launches, pre-launches, under construction, and K-RERA registered developments across Bangalore.

You MUST return strictly a valid JSON array of objects without markdown formatting or code fences.
Each object must contain these fields:
- "project_name": string (e.g. "Prestige Somerville")
- "builder_name": string (e.g. "Prestige Group", "Sobha Limited", "Brigade Group", "Godrej Properties", "Assetz")
- "locality": string (e.g. "Whitefield", "Sarjapur Road", "Hebbal", "Devanahalli", "Electronic City")
- "zone": string ("East Bangalore", "North Bangalore", "South Bangalore", "West Bangalore")
- "property_type": string ("Apartment", "Villa", "Row House", "Plotted Development")
- "configuration": string (e.g. "2, 3 & 4 BHK", "3 & 4 BHK Luxury Apartments", "Plots: 1200-2400 sq.ft")
- "price_range": string (e.g. "₹85 L - 1.95 Cr", "₹2.2 Cr onwards", "₹7,500/sq.ft")
- "status": string ("Newly Launched", "Pre-Launch", "Under Construction", "Ready to Move")
- "rera_number": string (e.g. "PRM/KA/RERA/1251/...", or "Pending / Applied")
- "possession_date": string (e.g. "Dec 2028", "Q4 2027")
- "total_units_or_area": string (e.g. "6.5 Acres / 320 Units")
- "key_amenities": string (e.g. "Lake view, 40,000 sq ft clubhouse, close to metro")
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
List at least 8 to 12 verified, authentic residential real estate projects in {zone_name} (including in {localities_str}), Bangalore.
Focus on prominent builders like Prestige, Sobha, Brigade, Godrej, Assetz, Puravankara, Rohan, Total Environment, Birla Estates, etc.
Include their real or estimated RERA numbers, pricing, BHK configurations, possession timelines, and locations.

Return strictly a JSON array of objects conforming to the system prompt specification.
"""
        for model_name in CANDIDATE_MODELS:
            # 1. Attempt standard generation first (100% free tier reliable, no 429 quota block)
            projects = self._generate(model_name, prompt, zone_name, with_search=False)
            if projects:
                logger.info(f"Gemini {model_name} successfully extracted {len(projects)} projects for {zone_name}.")
                return projects

            # 2. Attempt with search grounding if standard generation failed
            projects = self._generate(model_name, prompt, zone_name, with_search=True)
            if projects:
                logger.info(f"Gemini {model_name} (search) successfully extracted {len(projects)} projects for {zone_name}.")
                return projects

        return []

    def _generate(self, model_name: str, prompt: str, zone_name: str, with_search: bool) -> List[RealEstateProject]:
        """Calls client.models.generate_content."""
        try:
            from google.genai import types

            config_args = {"temperature": 0.2}
            if with_search:
                config_args["tools"] = [types.Tool(google_search=types.GoogleSearch())]

            config = types.GenerateContentConfig(**config_args)
            
            logger.info(f"Invoking Gemini {model_name} (search={with_search}) for {zone_name}...")
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
                logger.warning(f"Gemini {model_name} (search={with_search}) quota limit: {err_str[:120]}")
            elif "404" in err_str or "not found" in err_str.lower():
                logger.debug(f"Model {model_name} not available: {err_str[:100]}")
            else:
                logger.warning(f"Gemini {model_name} call error: {e}")
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
                        configuration=item.get("configuration", "2 & 3 BHK").strip(),
                        price_range=item.get("price_range", "On Request").strip(),
                        status=item.get("status", "Newly Launched").strip(),
                        rera_number=item.get("rera_number", "PRM/KA/RERA/...").strip(),
                        possession_date=item.get("possession_date", "TBA").strip(),
                        total_units_or_area=item.get("total_units_or_area", "N/A").strip(),
                        key_amenities=item.get("key_amenities", "Modern clubhouse & amenities").strip(),
                        source_url=item.get("source_url", "").strip(),
                        source_engine=engine_label
                    )
                    projects.append(project)
        except Exception as e:
            logger.warning(f"Failed to parse JSON from Gemini output: {e}\nRaw output sample: {text[:200]}")

        return projects
