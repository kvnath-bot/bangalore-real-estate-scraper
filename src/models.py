"""
Data models for Bangalore Real Estate Project Scraper and Karnataka RERA Raw Registry.
"""

import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote_plus
from pydantic import BaseModel, Field, model_validator


# Phase / wing / block markers that K-RERA appends to a registration but no map
# has ever heard of: "GODREJ FLORENNE PHASE II" is not a place, "GODREJ FLORENNE"
# is. 17.4% of Bangalore-region names carry this noise. Module level, because
# pydantic turns underscore-prefixed class attributes into private attrs.
UNIT_SUFFIX_RE = re.compile(
    r"[\s,\-]*\b(phase|ph|wing|block|tower|twr|annexe|annex|part|stage)\b[\s\-]*[\w&,\s]*$",
    re.IGNORECASE,
)
PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)")


class KRERARawProject(BaseModel):
    """Represents a raw project entry scraped directly from Karnataka RERA portal."""
    rera_number: str = Field(..., description="Official Karnataka RERA registration number")
    project_name: str = Field(..., description="Project name as registered with K-RERA")
    promoter_name: str = Field(..., description="Promoter / Developer registered entity name")
    ack_number: str = Field(default="", description="Application / Acknowledgement number")
    district: str = Field(default="Bengaluru Urban", description="District extracted from RERA code")
    portal_url: str = Field(default="https://rera.karnataka.gov.in/viewAllProjects?language=en")
    status: str = Field(default="Approved by K-RERA")
    discovered_date: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    enrichment_status: str = Field(default="Pending", description="Enriched & Synced (Bangalore) / Non-Bangalore (...)")
    latitude: str = Field(default="", description="Geocoded latitude of the project (blank when unresolved)")
    longitude: str = Field(default="", description="Geocoded longitude of the project (blank when unresolved)")
    map_pin_link: str = Field(default="", description="Google Maps link - a coordinate pin when geocoded, else a name search")

    @model_validator(mode="after")
    def _derive_district(self):
        """
        District is DERIVED from the RERA number, never taken on trust.

        The bundled master registry stores "Other Karnataka" for all 4,090
        /1251/ registrations, which are Bengaluru Urban - the largest group of
        Bangalore projects. Because the registry loader passed the stored value
        straight through, every one of them was treated as out of scope: not
        enriched, not geocoded, and mislabelled in the sheet. Deriving it here
        fixes the loader, the sheet writes and the geocoding stage at once.

        A RERA number whose code is not recognised yields "Other Karnataka",
        and in that case an explicitly supplied district is kept - the caller
        may know something the registration number does not encode.
        """
        derived = self.get_district_from_rera(self.rera_number)
        if derived != "Other Karnataka" and self.district != derived:
            object.__setattr__(self, "district", derived)
        return self

    @classmethod
    def get_district_from_rera(cls, rera_no: str) -> str:
        """Determines Karnataka district from RERA ID code."""
        if "/1251/" in rera_no:
            return "Bengaluru Urban"
        elif "/1250/" in rera_no:
            return "Bengaluru Rural"
        elif "/1265/" in rera_no:
            return "Ramanagara (BMRDA)"
        elif "/1248/" in rera_no:
            return "Tumakuru (Outer Bengaluru)"
        elif "/1257/" in rera_no:
            return "Chikkaballapura (North Bengaluru Corridor)"
        elif "/1254/" in rera_no:
            return "Kolar"
        elif "/1261/" in rera_no:
            return "Mysuru"
        elif "/1256/" in rera_no:
            return "Dakshina Kannada / Mangaluru"
        return "Other Karnataka"

    def is_bangalore_region(self) -> bool:
        """Returns True if project belongs to Bengaluru metropolitan area."""
        return self.district in [
            "Bengaluru Urban",
            "Bengaluru Rural",
            "Ramanagara (BMRDA)",
            "Chikkaballapura (North Bengaluru Corridor)"
        ]

    def compute_default_enrichment_status(self) -> str:
        """Returns the appropriate enrichment status based on geography."""
        if self.is_bangalore_region():
            return "Enriched & Synced (Bangalore)"
        return f"Non-Bangalore ({self.district})"

    @classmethod
    def clean_project_name(cls, name: str) -> str:
        """
        Strips the registration-unit noise from a project name.

            'Purva Park Hill (Wing D)'            -> 'Purva Park Hill'
            'Sobha Rain Forest Phase 3 Wing 5'    -> 'Sobha Rain Forest'
            'Nikoo Homes 9, Alpine, Garden Ph-1'  -> 'Nikoo Homes 9, Alpine, Garden'
        """
        cleaned = PARENTHETICAL_RE.sub("", name or "").strip()
        previous = None
        while previous != cleaned:
            previous = cleaned
            cleaned = UNIT_SUFFIX_RE.sub("", cleaned).strip(" ,-")
        return cleaned or (name or "").strip()

    def _district_label(self) -> str:
        district = self.district.split("(")[0].strip()
        return "Bengaluru" if district in ("Other Karnataka", "") else district

    def geocode_query(self) -> str:
        """Free-text address handed to the geocoder for this registration."""
        return f"{self.project_name.strip()}, {self._district_label()}, Karnataka, India"

    def geocode_queries(self) -> List[str]:
        """
        Query variants to try, in order, until one resolves.

        A single phrasing gives up too easily: the registered name often carries
        phase/wing noise, and the district qualifier can itself narrow a search
        past the point where the geocoder finds anything. Each variant costs one
        lookup, which is affordable on a few-thousand-a-day free tier.
        """
        district = self._district_label()
        name = self.project_name.strip()
        cleaned = self.clean_project_name(name)

        variants = [f"{name}, {district}, Karnataka, India"]
        if cleaned and cleaned.lower() != name.lower():
            variants.append(f"{cleaned}, {district}, Karnataka, India")
        variants.append(f"{cleaned or name}, Bengaluru, Karnataka, India")

        seen, ordered = set(), []
        for v in variants:
            key = " ".join(v.lower().split())
            if key not in seen:
                seen.add(key)
                ordered.append(v)
        return ordered

    def build_map_pin_link(self) -> str:
        """
        Google Maps link for this project. Prefers an exact coordinate pin and
        degrades to a name search so every row stays clickable.
        """
        if self.latitude and self.longitude:
            return f"https://www.google.com/maps/search/?api=1&query={self.latitude},{self.longitude}"
        query = quote_plus(self.geocode_query())
        return f"https://www.google.com/maps/search/?api=1&query={query}"

    def to_sheet_row(self) -> List[str]:
        status_val = self.enrichment_status
        if status_val == "Pending":
            status_val = self.compute_default_enrichment_status()
        return [
            self.rera_number,
            self.project_name,
            self.promoter_name,
            self.ack_number,
            self.district,
            self.portal_url,
            self.status,
            self.discovered_date,
            status_val,
            self.latitude,
            self.longitude,
            self.map_pin_link or self.build_map_pin_link(),
        ]

    @classmethod
    def sheet_headers(cls) -> List[str]:
        return [
            "Karnataka RERA No.",
            "Registered Project Name",
            "Promoter / Developer Name",
            "Application / Ack No.",
            "District / Region",
            "RERA Portal URL",
            "K-RERA Status",
            "Discovered Date",
            "Enrichment Status",
            "Latitude",
            "Longitude",
            "Map Pin Link",
        ]


class RealEstateProject(BaseModel):
    """Represents an enriched real estate project record for the Bangalore_Projects database."""
    project_name: str = Field(..., description="Official commercial or marketing name of the project")
    builder_name: str = Field(..., description="Promoter / Real Estate Developer name")
    locality: str = Field(..., description="Micro-market or locality in Bangalore (e.g. Whitefield, Sarjapur, Hebbal)")
    zone: str = Field(default="Bangalore", description="Broader region: East, North, South, West, or Central Bangalore")
    property_type: str = Field(default="Apartment", description="Apartment, Villa, Row House, Plotted Development, Penthouse, etc.")
    configuration: str = Field(default="N/A", description="Available configurations (e.g., 2 & 3 BHK, 4 BHK Villa, 1200-2400 sq.ft plots)")
    price_range: str = Field(default="On Request", description="Pricing bracket or starting price (e.g., ₹85 L - 1.8 Cr, ₹7,200/sq.ft)")
    status: str = Field(default="Newly Launched", description="Status: Newly Launched, Pre-Launch, Under Construction, Ready to Move")
    rera_number: str = Field(default="Pending / Not Specified", description="Karnataka RERA registration number (PRM/KA/RERA/...)")
    possession_date: str = Field(default="TBA", description="Estimated possession timeline (e.g., Dec 2028, Q3 2027)")
    total_units_or_area: str = Field(default="N/A", description="Total project area in acres or total number of residential units")
    key_amenities: str = Field(default="", description="Key highlights, amenities or landmark proximity")
    source_url: str = Field(default="", description="Official link, RERA portal link, or developer page")
    source_engine: str = Field(default="AI Search Grounding", description="Scraper engine used (Gemini / Perplexity / K-RERA / Propsoch / 99Acres)")
    first_discovered: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    last_updated: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    @staticmethod
    def is_valid_rera(rera_number: str) -> bool:
        """
        True when a RERA string is a real registration ID rather than a
        placeholder like "Pending", "Not Specified" or "To be verified".
        """
        clean = "".join(filter(str.isalnum, (rera_number or "").lower()))
        if not clean or len(clean) <= 6:
            return False
        return not any(token in clean for token in ("pending", "not", "verified"))

    def rera_key(self) -> str:
        """Identity key based on the RERA registration, or "" when there isn't a real one."""
        if not self.is_valid_rera(self.rera_number):
            return ""
        return f"rera:{''.join(filter(str.isalnum, self.rera_number.lower()))}"

    def name_key(self) -> str:
        """Identity key based on project name + builder, always available."""
        clean_proj = "".join(filter(str.isalnum, self.project_name.lower()))
        clean_builder = "".join(filter(str.isalnum, self.builder_name.lower()))
        return f"name:{clean_proj}|{clean_builder}"

    def identity_keys(self) -> List[str]:
        """
        Every key this project can be recognised by. A record carrying a real
        RERA number is also indexed by name, so the same project discovered
        twice - once from a portal without a RERA number, once from K-RERA with
        one - still collapses into a single row.
        """
        keys = [self.name_key()]
        rera = self.rera_key()
        if rera:
            keys.insert(0, rera)
        return keys

    def deduplication_key(self) -> str:
        """Preferred single key for this project: RERA when real, else name + builder."""
        return self.rera_key() or self.name_key()

    def to_sheet_row(self) -> List[str]:
        return [
            self.project_name,
            self.builder_name,
            self.locality,
            self.zone,
            self.property_type,
            self.configuration,
            self.price_range,
            self.status,
            self.rera_number,
            self.possession_date,
            self.total_units_or_area,
            self.key_amenities,
            self.source_url,
            self.source_engine,
            self.first_discovered,
            self.last_updated,
        ]

    @classmethod
    def from_sheet_row(cls, row: List[str]) -> "RealEstateProject":
        """
        Rebuilds a project from a Bangalore_Projects sheet row, the inverse of
        to_sheet_row(). Short rows are tolerated - trailing blanks fall back to
        the field defaults, which is how Sheets returns partially filled rows.
        """
        def cell(idx: int) -> str:
            return row[idx].strip() if len(row) > idx and row[idx] else ""

        defaults = {
            "zone": "Bangalore",
            "property_type": "Apartment",
            "configuration": "N/A",
            "price_range": "On Request",
            "status": "Newly Launched",
            "rera_number": "Pending / Not Specified",
            "possession_date": "TBA",
            "total_units_or_area": "N/A",
            "source_engine": "AI Search Grounding",
        }
        order = [
            "project_name", "builder_name", "locality", "zone", "property_type",
            "configuration", "price_range", "status", "rera_number",
            "possession_date", "total_units_or_area", "key_amenities",
            "source_url", "source_engine", "first_discovered", "last_updated",
        ]
        values = {}
        for idx, field in enumerate(order):
            raw = cell(idx)
            if raw:
                values[field] = raw
            elif field in defaults:
                values[field] = defaults[field]
        values.setdefault("project_name", "")
        values.setdefault("builder_name", "")
        values.setdefault("locality", "")
        return cls(**values)

    @classmethod
    def sheet_headers(cls) -> List[str]:
        return [
            "Project Name",
            "Builder / Developer",
            "Locality",
            "Zone / Sub-Market",
            "Property Type",
            "Configurations (BHK)",
            "Price Range",
            "Project Status",
            "Karnataka RERA No.",
            "Possession Date",
            "Units / Land Parcel",
            "Key Amenities & Highlights",
            "Source URL",
            "Data Source",
            "First Discovered",
            "Last Updated",
        ]


class ScrapeRunSummary(BaseModel):
    """Execution summary for a scraping session."""
    run_timestamp: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    engine_used: str
    total_found: int = 0
    new_added: int = 0
    existing_updated: int = 0
    status: str = "SUCCESS"
    notes_or_errors: str = "Completed successfully"

    def to_log_row(self) -> List[str]:
        return [
            self.run_timestamp,
            self.engine_used,
            str(self.total_found),
            str(self.new_added),
            str(self.existing_updated),
            self.status,
            self.notes_or_errors,
        ]

    @classmethod
    def log_headers(cls) -> List[str]:
        return [
            "Run Timestamp",
            "Engine / Strategy",
            "Total Discovered",
            "New Projects Added",
            "Existing Projects Updated",
            "Run Status",
            "Notes / Diagnostics",
        ]
