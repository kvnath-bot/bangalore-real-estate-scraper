"""
Data models for Bangalore Real Estate Project Scraper and Karnataka RERA Raw Registry.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


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
    enrichment_status: str = Field(default="Pending", description="Pending / Enriched & Synced")

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

    def to_sheet_row(self) -> List[str]:
        return [
            self.rera_number,
            self.project_name,
            self.promoter_name,
            self.ack_number,
            self.district,
            self.portal_url,
            self.status,
            self.discovered_date,
            self.enrichment_status,
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

    def deduplication_key(self) -> str:
        """Unique key to identify duplicates."""
        clean_rera = "".join(filter(str.isalnum, self.rera_number.lower()))
        if clean_rera and "pending" not in clean_rera and "not" not in clean_rera and "verified" not in clean_rera and len(clean_rera) > 6:
            return f"rera:{clean_rera}"
        
        clean_proj = "".join(filter(str.isalnum, self.project_name.lower()))
        clean_builder = "".join(filter(str.isalnum, self.builder_name.lower()))
        return f"name:{clean_proj}|{clean_builder}"

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
