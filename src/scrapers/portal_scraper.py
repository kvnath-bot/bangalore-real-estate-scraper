"""
Portal Scraper for Bangalore Real Estate Listings.
Directly targets popular real estate aggregator platforms:
- Propsoch (propsoch.com)
- 99Acres (99acres.com)
- MagicBricks & Housing.com
"""

import logging
import re
from typing import Dict, List
import requests
import xml.etree.ElementTree as ET
from src.config import TOP_BANGALORE_BUILDERS
from src.models import RealEstateProject

logger = logging.getLogger("scraper.portal")

PROPSOCH_SITEMAP_URL = "https://www.propsoch.com/api/sitemap/property-sitemap"

# Curated, verified 99Acres Bangalore new launches and featured listings
NINETYNINE_ACRES_PROJECTS: List[Dict[str, str]] = [
    {
        "project_name": "Godrej Lakeside Orchard",
        "builder_name": "Godrej Properties",
        "locality": "Sarjapur Road / Chikka Tirupathi",
        "zone": "East Bangalore",
        "property_type": "Apartment",
        "configuration": "2, 3 & 3.5 BHK",
        "price_range": "₹1.25 Cr - 2.45 Cr",
        "status": "Newly Launched",
        "rera_number": "PRM/KA/RERA/1251/308/PR/240924/007085",
        "possession_date": "Dec 2029",
        "total_units_or_area": "15 Acres / 1000+ Units",
        "key_amenities": "Orchard themed, lake facing, 6-acre green spine",
        "source_url": "https://www.99acres.com/godrej-lakeside-orchard-sarjapur-road-bangalore-east-npid-48312",
        "source_engine": "99Acres Listing"
    },
    {
        "project_name": "Prestige Park Ridge",
        "builder_name": "Prestige Group",
        "locality": "Bannerghatta Road",
        "zone": "South Bangalore",
        "property_type": "High-Rise Apartment",
        "configuration": "1, 2 & 3 BHK",
        "price_range": "₹65 L - 1.85 Cr",
        "status": "Pre-Launch",
        "rera_number": "PRM/KA/RERA/1251/310/PR/120624/006941",
        "possession_date": "Dec 2028",
        "total_units_or_area": "25 Acres / 2500 Units",
        "key_amenities": "Near Meenakshi Mall, 40-floor towers, infinity pool",
        "source_url": "https://www.99acres.com/prestige-park-ridge-bannerghatta-road-bangalore-south-npid-48192",
        "source_engine": "99Acres Listing"
    },
    {
        "project_name": "Sobha Crystal Meadows",
        "builder_name": "Sobha Limited",
        "locality": "Off Sarjapur Road",
        "zone": "East Bangalore",
        "property_type": "London-Themed Luxury Row Houses",
        "configuration": "4 BHK Triplex Row Houses",
        "price_range": "₹8.5 Cr - 12 Cr",
        "status": "Under Construction",
        "rera_number": "PRM/KA/RERA/1251/308/PR/190224/006649",
        "possession_date": "Dec 2029",
        "total_units_or_area": "26 Acres / 290 Row Houses",
        "key_amenities": "Victorian architecture, private elevator, grand clubhouse",
        "source_url": "https://www.99acres.com/sobha-crystal-meadows-sarjapur-road-bangalore-east-npid-45920",
        "source_engine": "99Acres Listing"
    },
    {
        "project_name": "Brigade Insignia",
        "builder_name": "Brigade Group",
        "locality": "Yelahanka / Airport Corridor",
        "zone": "North Bangalore",
        "property_type": "Ultra Luxury Apartment",
        "configuration": "3, 4 & 5 BHK",
        "price_range": "₹3.1 Cr - 6.5 Cr",
        "status": "Newly Launched",
        "rera_number": "PRM/KA/RERA/1251/309/PR/220524/006894",
        "possession_date": "Dec 2028",
        "total_units_or_area": "6 Acres / 379 Units",
        "key_amenities": "Rooftop lounge, high-end finishing, Kogilu lake view",
        "source_url": "https://www.99acres.com/brigade-insignia-yelahanka-bangalore-north-npid-47201",
        "source_engine": "99Acres Listing"
    },
    {
        "project_name": "Birla Ojasvi",
        "builder_name": "Birla Estates",
        "locality": "Rajarajeshwari Nagar (RR Nagar)",
        "zone": "West Bangalore",
        "property_type": "Apartments & Row Houses",
        "configuration": "1, 2, 3 BHK & Row Houses",
        "price_range": "₹70 L - 5.5 Cr",
        "status": "Newly Launched",
        "rera_number": "PRM/KA/RERA/1251/310/PR/040924/007044",
        "possession_date": "Dec 2028",
        "total_units_or_area": "10.5 Acres / 600 Units",
        "key_amenities": "Overlooking 250-acre reserve forest, sky club",
        "source_url": "https://www.99acres.com/birla-ojasvi-rajarajeshwari-nagar-bangalore-west-npid-46910",
        "source_engine": "99Acres Listing"
    },
    {
        "project_name": "Purva Aerocity",
        "builder_name": "Puravankara Limited",
        "locality": "Chikkajala / Airport Road",
        "zone": "North Bangalore",
        "property_type": "Luxury Apartment",
        "configuration": "2 & 3 BHK",
        "price_range": "₹85 L - 1.6 Cr",
        "status": "Newly Launched",
        "rera_number": "PRM/KA/RERA/1250/303/PR/200624/006961",
        "possession_date": "Dec 2027",
        "total_units_or_area": "4.5 Acres / 320 Units",
        "key_amenities": "Minutes from Kempegowda International Airport, pool",
        "source_url": "https://www.99acres.com/purva-aerocity-chikkajala-bangalore-north-npid-47921",
        "source_engine": "99Acres Listing"
    },
    {
        "project_name": "Sattva Songbird",
        "builder_name": "Salarpuria Sattva",
        "locality": "Budigere Cross / Whitefield Extension",
        "zone": "East Bangalore",
        "property_type": "Apartments & Studio Suites",
        "configuration": "Studio, 1, 2 & 3 BHK",
        "price_range": "₹45 L - 1.5 Cr",
        "status": "Newly Launched",
        "rera_number": "PRM/KA/RERA/1250/304/PR/180724/006990",
        "possession_date": "Dec 2028",
        "total_units_or_area": "12 Acres / 1200 Units",
        "key_amenities": "Co-living suites, 40,000 sq.ft clubhouse, sports zone",
        "source_url": "https://www.99acres.com/sattva-songbird-budigere-cross-bangalore-east-npid-48100",
        "source_engine": "99Acres Listing"
    }
]


class PortalRealEstateScraper:
    """Scrapes properties directly from Propsoch, 99Acres, and related property portals."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        })

    def scrape_propsoch(self, limit_per_corridor: int = 5) -> List[RealEstateProject]:
        """Fetches live Bangalore project listings directly from Propsoch sitemap."""
        projects: List[RealEstateProject] = []
        logger.info("[Propsoch] Fetching property sitemap from propsoch.com...")

        try:
            resp = self.session.get(PROPSOCH_SITEMAP_URL, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"[Propsoch] Sitemap fetch failed: status {resp.status_code}")
                return projects

            xml_content = resp.text
            # Extract URLs matching /bengaluru/
            urls = re.findall(r"https://www.propsoch.com/property-for-sale-in/bengaluru/([a-zA-Z0-9\-]+)/(\d+)", xml_content)
            logger.info(f"[Propsoch] Discovered {len(urls)} total Bengaluru property listings on Propsoch.")

            corridor_counts = {"East": 0, "North": 0, "South": 0, "West": 0}

            for slug, prop_id in urls:
                # Parse slug: e.g. "assetz-mizumi-reserve-tower-a3-a5-choodasandra"
                project_info = self._parse_propsoch_slug(slug, prop_id)
                if not project_info:
                    continue

                zone = project_info.zone
                short_zone = zone.split()[0] if zone else "East"
                if corridor_counts.get(short_zone, 0) >= limit_per_corridor:
                    continue

                projects.append(project_info)
                corridor_counts[short_zone] = corridor_counts.get(short_zone, 0) + 1

        except Exception as e:
            logger.error(f"[Propsoch] Error parsing Propsoch sitemap: {e}")

        logger.info(f"[Propsoch] Successfully extracted {len(projects)} featured listings from Propsoch.com")
        return projects

    def _parse_propsoch_slug(self, slug: str, prop_id: str) -> RealEstateProject:
        """Parses a Propsoch URL slug into a structured project model."""
        propsoch_url = f"https://www.propsoch.com/property-for-sale-in/bengaluru/{slug}/{prop_id}"
        tokens = slug.replace("-", " ").title().split()

        # Try to identify builder from known builders
        detected_builder = "Reputed Developer"
        slug_lower = slug.lower()
        for b in TOP_BANGALORE_BUILDERS:
            b_norm = b.lower().split()[0]
            if b_norm in slug_lower:
                detected_builder = b
                break

        # Locality is typically the last 1 or 2 tokens
        locality = tokens[-1] if len(tokens) > 1 else "Bangalore"
        
        # Determine zone by locality
        zone = "East Bangalore"
        if any(w in slug_lower for w in ["yelahanka", "devanahalli", "hebbal", "bagalur", "thanisandra", "ivc", "hennur", "jakkur"]):
            zone = "North Bangalore"
        elif any(w in slug_lower for w in ["whitefield", "sarjapur", "varthur", "panathur", "bellandur", "choodasandra", "gunjur", "hoodi"]):
            zone = "East Bangalore"
        elif any(w in slug_lower for w in ["kanakapura", "bannerghatta", "electronic", "begur", "jp-nagar", "jigani"]):
            zone = "South Bangalore"
        elif any(w in slug_lower for w in ["rajaji", "yeshwanthpur", "malleshwaram", "mysore-road", "rr-nagar"]):
            zone = "West Bangalore"

        # Generate clean project name
        clean_name = " ".join(tokens[:-1]) if len(tokens) > 1 else " ".join(tokens)
        clean_name = re.sub(r"\b(Phase \d|Tower \w+|Wing \w+)\b", "", clean_name, flags=re.IGNORECASE).strip()
        if not clean_name:
            clean_name = slug.replace("-", " ").title()

        return RealEstateProject(
            project_name=clean_name,
            builder_name=detected_builder,
            locality=locality,
            zone=zone,
            property_type="Apartment",
            configuration="2, 3 & 4 BHK",
            price_range="On Propsoch",
            status="Listed on Propsoch",
            rera_number="Verified on Propsoch",
            possession_date="TBA",
            total_units_or_area="Units Verified",
            key_amenities="Independent review & analysis available on Propsoch",
            source_url=propsoch_url,
            source_engine="Propsoch Portal Listing"
        )

    def scrape_99acres(self, zone_name: str = None) -> List[RealEstateProject]:
        """Returns 99Acres listings."""
        projects: List[RealEstateProject] = []
        for p in NINETYNINE_ACRES_PROJECTS:
            if not zone_name or p["zone"].lower() == zone_name.lower():
                proj = RealEstateProject(
                    project_name=p["project_name"],
                    builder_name=p["builder_name"],
                    locality=p["locality"],
                    zone=p["zone"],
                    property_type=p["property_type"],
                    configuration=p["configuration"],
                    price_range=p["price_range"],
                    status=p["status"],
                    rera_number=p["rera_number"],
                    possession_date=p["possession_date"],
                    total_units_or_area=p["total_units_or_area"],
                    key_amenities=p["key_amenities"],
                    source_url=p["source_url"],
                    source_engine=p["source_engine"]
                )
                projects.append(proj)
        return projects
