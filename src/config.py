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

# --- Geocoding / Map Pin Settings ---
# Master switch for the geocoding stage.
GEOCODE_ENABLED = os.getenv("GEOCODE_ENABLED", "true").strip().lower() in ("1", "true", "yes")

# Which geocoding backend to use: "locationiq", "geoapify", "google" or
# "nominatim". Leave blank to auto-detect from whichever API key is set.
GEOCODE_BACKEND = os.getenv("GEOCODE_BACKEND", "").strip().lower()

# Free-tier geocoders. Both are email-signup only - no credit card, no billing
# account - and sustain thousands of lookups a day, unlike the public Nominatim
# endpoint whose usage policy forbids bulk geocoding.
LOCATIONIQ_API_KEY = os.getenv("LOCATIONIQ_API_KEY", "").strip()
GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY", "").strip()

# Optional Google Geocoding API key. Fastest, but REQUIRES a billing account on
# the Cloud project, so it is deliberately ranked below the free-tier providers.
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()

# When the Google Geocoding API finds nothing, retry through the Places Text
# Search API. Geocoding resolves ADDRESSES; Places resolves POIs, which is what
# a project name actually is - this is what lifts villa and small-project
# coverage off the floor. Places costs more per call than Geocoding, so it runs
# only on the misses. Needs the Places API enabled on the same Cloud project.
GOOGLE_PLACES_FALLBACK = os.getenv("GOOGLE_PLACES_FALLBACK", "true").strip().lower() in ("1", "true", "yes")

# Free OpenStreetMap geocoder. Its usage policy requires an identifying User-Agent.
NOMINATIM_ENDPOINT = os.getenv("NOMINATIM_ENDPOINT", "https://nominatim.openstreetmap.org/search").strip()
GEOCODE_USER_AGENT = os.getenv(
    "GEOCODE_USER_AGENT",
    "bangalore-real-estate-scraper/1.0 (github.com/kvnath-bot/bangalore-real-estate-scraper)",
).strip()

# Lookups spent per run. 0 means "use the chosen backend's own ceiling", which
# is small for public Nominatim (policy) and a few thousand for the free-tier
# providers. Set a number to override. The sheet carries progress between runs.
GEOCODE_MAX_PER_RUN = int(os.getenv("GEOCODE_MAX_PER_RUN", "0"))
GEOCODE_CACHE_FILE = Path(os.getenv("GEOCODE_CACHE_FILE", str(ROOT_DIR / "src" / "data" / "geocode_cache.json")))

# Wall-clock ceiling for the geocoding stage, in seconds. The GitHub Actions job
# is capped at 90 minutes; stopping well inside that leaves room to write results
# and finish the run. A run that is killed mid-stage loses whatever it has not
# written, so this matters more than the lookup count.
GEOCODE_TIME_BUDGET_SECONDS = int(os.getenv("GEOCODE_TIME_BUDGET_SECONDS", "3000"))

# Write coordinates to the sheet every N rows instead of once at the end, so a
# timeout or crash costs at most this many lookups.
GEOCODE_FLUSH_EVERY = int(os.getenv("GEOCODE_FLUSH_EVERY", "250"))

# --- Google Sheet Sharing ---
# Comma-separated Gmail / Workspace addresses granted access after each run.
SHARE_WITH_EMAILS = [
    e.strip() for e in os.getenv("SHARE_WITH_EMAILS", "").split(",") if e.strip()
]
# Role granted to those addresses: "reader", "commenter" or "writer".
SHARE_ROLE = os.getenv("SHARE_ROLE", "writer").strip().lower()
# Email the recipients a Drive notification when access is first granted.
SHARE_NOTIFY = os.getenv("SHARE_NOTIFY", "false").strip().lower() in ("1", "true", "yes")

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
