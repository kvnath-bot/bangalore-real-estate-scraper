"""
Geocoding helper for K-RERA raw projects.

Resolves a project name + district into latitude / longitude so every Bangalore
region registration can be dropped onto a map. Two backends are supported:

  1. Nominatim (OpenStreetMap) - free, no key, hard limit of 1 request/second.
  2. Google Geocoding API   - used automatically when GOOGLE_MAPS_API_KEY is set.

Results (including misses) are cached on disk so repeated runs never re-query the
same project, and each run only spends GEOCODE_MAX_PER_RUN lookups. That keeps
the daily GitHub Actions job inside its time budget while the cache fills up
incrementally across runs.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

from src.config import (
    GEOCODE_CACHE_FILE,
    GEOCODE_ENABLED,
    GEOCODE_MAX_PER_RUN,
    GEOCODE_USER_AGENT,
    GOOGLE_MAPS_API_KEY,
    NOMINATIM_ENDPOINT,
)

logger = logging.getLogger("geocoder")

GOOGLE_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"

# Nominatim's usage policy: absolute maximum of 1 request per second.
NOMINATIM_DELAY_SECONDS = 1.1
GOOGLE_DELAY_SECONDS = 0.05

# Bounding box around the Bengaluru metropolitan region (BMRDA extent).
# Anything resolved outside this box is treated as a bad match and discarded.
BLR_MIN_LAT, BLR_MAX_LAT = 12.20, 13.60
BLR_MIN_LNG, BLR_MAX_LNG = 76.90, 78.20


class Geocoder:
    """Disk-cached geocoder with a per-run lookup budget."""

    def __init__(self, cache_file: Optional[Path] = None):
        self.cache_file = Path(cache_file or GEOCODE_CACHE_FILE)
        self.cache: Dict[str, Optional[list]] = self._load_cache()
        self.lookups_used = 0
        self.hits = 0
        self.misses = 0
        self.use_google = bool(GOOGLE_MAPS_API_KEY)
        if self.use_google:
            logger.info("[Geocoder] Using Google Geocoding API backend.")
        else:
            logger.info("[Geocoder] Using free Nominatim (OpenStreetMap) backend at ~1 req/sec.")

    # ------------------------------------------------------------------ cache
    def _load_cache(self) -> Dict[str, Optional[list]]:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info(f"[Geocoder] Loaded {len(data)} cached geocode results from {self.cache_file.name}.")
                return data
            except Exception as e:
                logger.warning(f"[Geocoder] Could not read cache {self.cache_file}: {e}")
        return {}

    def save_cache(self):
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
            logger.info(f"[Geocoder] Saved {len(self.cache)} geocode results to {self.cache_file.name}.")
        except Exception as e:
            logger.warning(f"[Geocoder] Could not write cache {self.cache_file}: {e}")

    @property
    def budget_remaining(self) -> int:
        return max(0, GEOCODE_MAX_PER_RUN - self.lookups_used)

    # -------------------------------------------------------------- public API
    def geocode_address(self, address: str) -> Optional[Tuple[float, float]]:
        """
        Returns (latitude, longitude) for a free-text address, or None when the
        address cannot be resolved inside the Bengaluru region.

        Cached answers - including cached failures - never consume the run budget.
        """
        if not GEOCODE_ENABLED or not address or not address.strip():
            return None

        key = " ".join(address.lower().split())
        if key in self.cache:
            cached = self.cache[key]
            return (cached[0], cached[1]) if cached else None

        if self.budget_remaining <= 0:
            return None

        self.lookups_used += 1
        coords = self._lookup_google(address) if self.use_google else self._lookup_nominatim(address)

        if coords and not self._within_bangalore(coords):
            logger.debug(f"[Geocoder] Discarded out-of-region match for '{address}': {coords}")
            coords = None

        self.cache[key] = [coords[0], coords[1]] if coords else None
        if coords:
            self.hits += 1
        else:
            self.misses += 1
        return coords

    # --------------------------------------------------------------- backends
    def _lookup_nominatim(self, address: str) -> Optional[Tuple[float, float]]:
        try:
            resp = requests.get(
                NOMINATIM_ENDPOINT,
                params={
                    "q": address,
                    "format": "json",
                    "limit": 1,
                    "countrycodes": "in",
                },
                headers={"User-Agent": GEOCODE_USER_AGENT},
                timeout=20,
            )
            time.sleep(NOMINATIM_DELAY_SECONDS)
            if resp.status_code != 200:
                logger.warning(f"[Geocoder] Nominatim returned HTTP {resp.status_code} for '{address}'.")
                return None
            results = resp.json()
            if not results:
                return None
            return (float(results[0]["lat"]), float(results[0]["lon"]))
        except Exception as e:
            logger.warning(f"[Geocoder] Nominatim lookup failed for '{address}': {e}")
            time.sleep(NOMINATIM_DELAY_SECONDS)
            return None

    def _lookup_google(self, address: str) -> Optional[Tuple[float, float]]:
        try:
            resp = requests.get(
                GOOGLE_ENDPOINT,
                params={"address": address, "key": GOOGLE_MAPS_API_KEY, "region": "in"},
                timeout=20,
            )
            time.sleep(GOOGLE_DELAY_SECONDS)
            payload = resp.json()
            status = payload.get("status")
            if status == "ZERO_RESULTS":
                return None
            if status != "OK":
                logger.warning(f"[Geocoder] Google Geocoding status '{status}' for '{address}'.")
                return None
            loc = payload["results"][0]["geometry"]["location"]
            return (float(loc["lat"]), float(loc["lng"]))
        except Exception as e:
            logger.warning(f"[Geocoder] Google lookup failed for '{address}': {e}")
            return None

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _within_bangalore(coords: Tuple[float, float]) -> bool:
        lat, lng = coords
        return BLR_MIN_LAT <= lat <= BLR_MAX_LAT and BLR_MIN_LNG <= lng <= BLR_MAX_LNG
