"""
RERA Data Enrichment Engine for Bangalore Real Estate Projects.
Takes raw records from KRERA_Raw_Projects, determines micro-markets, builders,
property types, and prepares enriched records for Bangalore_Projects database.
"""

import logging
import re
from typing import Dict, List, Optional
from src.config import BANGALORE_ZONES, TOP_BANGALORE_BUILDERS
from src.models import KRERARawProject, RealEstateProject

logger = logging.getLogger("enricher")

# Map promoter legal entity names to standard developer brands
PROMOTER_BRAND_MAP = {
    "PRESTIGE": "Prestige Group",
    "SOBHA": "Sobha Limited",
    "BRIGADE": "Brigade Group",
    "GODREJ": "Godrej Properties",
    "PURAVANKARA": "Puravankara Limited",
    "PROVIDENT": "Provident Housing",
    "SATTVA": "Salarpuria Sattva",
    "SHIRASA": "Salarpuria Sattva",
    "ASSETZ": "Assetz Property Group",
    "ROHAN": "Rohan Builders",
    "TOTAL ENVIRONMENT": "Total Environment",
    "BIRLA": "Birla Estates",
    "MAHINDRA": "Mahindra Lifespaces",
    "LODHA": "Lodha",
    "CENTURY": "Century Real Estate",
    "CONCORDE": "Concorde Group",
    "SHRIRAM": "Shriram Properties",
    "ARVIND": "Arvind SmartSpaces",
    "BHARTIYA": "Bhartiya City",
    "SUMADHURA": "Sumadhura Group",
    "VASWANI": "Vaswani Group",
    "SALARPURIA": "Salarpuria Sattva",
    "DS-MAX": "DS-MAX Properties",
    "MANA": "Mana Projects",
    "SPLENDID": "Splendid Properties",
}


class ProjectEnricher:
    """Enriches raw K-RERA project entries into comprehensive Bangalore_Projects records."""

    def enrich_raw_project(self, raw: KRERARawProject) -> Optional[RealEstateProject]:
        """Enriches a single KRERARawProject into a RealEstateProject."""
        if not raw.is_bangalore_region():
            return None

        # Clean project name
        proj_name = raw.project_name.title().strip()
        promoter_upper = raw.promoter_name.upper()

        # 1. Identify Builder Brand
        builder_brand = "Reputed Developer"
        for key, brand in PROMOTER_BRAND_MAP.items():
            if key in promoter_upper or key in proj_name.upper():
                builder_brand = brand
                break
        if builder_brand == "Reputed Developer" and raw.promoter_name:
            builder_brand = raw.promoter_name.title().strip()

        # 2. Identify Locality & Zone
        locality, zone = self._detect_locality_and_zone(proj_name, raw.district)

        # 3. Detect Property Type
        prop_type = self._detect_property_type(proj_name)

        # 4. Format RERA registration number and details
        return RealEstateProject(
            project_name=proj_name,
            builder_name=builder_brand,
            locality=locality,
            zone=zone,
            property_type=prop_type,
            configuration="2, 3 & 4 BHK" if prop_type == "Apartment" else ("Plots: 1200-2400 sq.ft" if "Plot" in prop_type else "3 & 4 BHK Villa"),
            price_range="On Request / RERA Verified",
            status="Approved by K-RERA",
            rera_number=raw.rera_number,
            possession_date="As per RERA Filing",
            total_units_or_area="RERA Registered",
            key_amenities=f"Official K-RERA Approved Project ({raw.district})",
            source_url=f"https://rera.karnataka.gov.in/viewAllProjects?language=en",
            source_engine="K-RERA Government Registry (Enriched)"
        )

    def _detect_locality_and_zone(self, project_name: str, district: str) -> (str, str):
        """Detects micro-market locality and zone based on text clues or district."""
        name_lower = project_name.lower()

        # Check against all known Bangalore zones and localities
        for z_name, locs in BANGALORE_ZONES.items():
            for loc in locs:
                if loc.lower() in name_lower:
                    return loc, z_name

        # Common localities not in main list
        extra_localities = {
            "yelahanka": ("Yelahanka", "North Bangalore"),
            "chikkajala": ("Chikkajala", "North Bangalore"),
            "bagalur": ("Bagalur", "North Bangalore"),
            "varthur": ("Varthur", "East Bangalore"),
            "panathur": ("Panathur", "East Bangalore"),
            "gunjur": ("Gunjur", "East Bangalore"),
            "kadugodi": ("Kadugodi", "East Bangalore"),
            "choodasandra": ("Choodasandra", "East Bangalore"),
            "begur": ("Begur Road", "South Bangalore"),
            "harlur": ("Harlur Road", "South Bangalore"),
            "jigani": ("Jigani / Anekal", "South Bangalore"),
            "rr nagar": ("Rajarajeshwari Nagar", "West Bangalore"),
            "kengeri": ("Kengeri", "West Bangalore"),
            "tumkur": ("Tumkur Road", "West Bangalore"),
        }
        for keyword, (loc, z) in extra_localities.items():
            if keyword in name_lower:
                return loc, z

        # Fallback based on district
        if district == "Bengaluru Rural":
            return "Devanahalli / Airport Corridor", "North Bangalore"
        elif district == "Ramanagara (BMRDA)":
            return "Bidadi / Mysore Road Corridor", "West Bangalore"
        elif district == "Chikkaballapura (North Bengaluru Corridor)":
            return "North Bangalore Ext / Chikkaballapura", "North Bangalore"

        return "Bengaluru Urban", "East Bangalore"

    def _detect_property_type(self, project_name: str) -> str:
        """Determines property type from name."""
        name_lower = project_name.lower()
        if any(w in name_lower for w in ["villa", "villas", "retreat", "homestead"]):
            return "Luxury Villa"
        elif any(w in name_lower for w in ["layout", "plots", "plotted", "meadows", "enclave", "gardens", "acres", "county", "township", "estates"]):
            return "Plotted Development"
        elif any(w in name_lower for w in ["commercial", "mall", "tower", "arcade", "business", "tech park"]):
            return "Commercial / Mixed"
        elif any(w in name_lower for w in ["row house", "rowhouse", "duplex"]):
            return "Row House"
        return "Apartment"
