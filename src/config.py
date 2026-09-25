"""
Configuration settings for the Bangalore Real Estate Scraper.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# --- AI API Keys & Strategy ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "").strip()
SEARCH_STRATEGY = os.getenv("SEARCH_STRATEGY", "hybrid").lower().strip()

# Default Gemini model
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

# --- Google Sheets Settings ---
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Bangalore Real Estate Projects Tracker").strip()
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "").strip()

# Google Cloud Service Account
# Priority 1: Raw JSON string in env var (GitHub Actions / Cloud)
GCP_SERVICE_ACCOUNT_KEY = os.getenv("GCP_SERVICE_ACCOUNT_KEY", "").strip()
# Priority 2: File path on disk
GCP_SERVICE_ACCOUNT_FILE = os.getenv("GCP_SERVICE_ACCOUNT_FILE", "service_account.json").strip()

# --- Server / Trigger Settings ---
PORT = int(os.getenv("PORT", "8000"))
CRON_SECRET = os.getenv("CRON_SECRET", "").strip()

# --- Bangalore Micro-Markets & Real Estate Hubs for Targeted Grounded Search ---
BANGALORE_ZONES = {
    "East Bangalore": [
        "Whitefield", "Sarjapur Road", "Varthur", "Bellandur", 
        "Marathahalli", "Kadugodi", "Hoodi", "Panathur"
    ],
    "North Bangalore": [
        "Devanahalli", "Hebbal", "Thanisandra Main Road", "Yelahanka", 
        "Hennur Road", "Bagalur / Aerospace SEZ", "Jakkur", "Doddaballapur Road"
    ],
    "South Bangalore": [
        "Electronic City", "Kanakapura Road", "Bannerghatta Road", 
        "Begur Road", "JP Nagar", "Harlur Road", "Chandapura - Anekal"
    ],
    "West Bangalore": [
        "Rajajinagar", "Yeshwanthpur", "Malleshwaram", 
        "Tumkur Road", "Mysore Road", "Kengeri"
    ]
}

# Major tier-1 and tier-2 builders active in Bengaluru
TOP_BANGALORE_BUILDERS = [
    "Prestige Group", "Sobha Limited", "Brigade Group", "Godrej Properties",
    "Puravankara / Provident", "Total Environment", "Assetz Property Group",
    "Rohan Builders", "Shriram Properties", "Salarpuria Sattva",
    "Mahindra Lifespaces", "Birla Estates", "Lodha", "Century Real Estate"
]
