"""
Geocoding helper for K-RERA raw projects.

Resolves a project name + district into latitude / longitude so every Bangalore
region registration can be dropped onto a map. Four interchangeable backends are
supported, picked automatically from whichever API key is present:

  ==============  =========  ==========  ==================================
  backend         key?       card?       notes
  ==============  =========  ==========  ==================================
  locationiq      yes        no          free tier, email signup only
  geoapify        yes        no          free tier, email signup only
  google          yes        YES         needs a billing account
  nominatim       no         no          default; ~1 req/sec, NOT for bulk
  ==============  =========  ==========  ==================================

Nominatim is the public OpenStreetMap endpoint. It is donated infrastructure and
its usage policy forbids bulk geocoding, so its per-run budget is deliberately
small. To work through a large backlog quickly, use a keyed backend instead - or
point NOMINATIM_ENDPOINT at your own self-hosted instance, where no such limit
applies.

Results (including misses) are cached on disk so repeated runs never re-query the
same project, and each run stops after its lookup budget is spent. That keeps the
daily GitHub Actions job inside its time budget while the cache fills up
incrementally across runs.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

from src.config import (
    GEOAPIFY_API_KEY,
    GEOCODE_BACKEND,
    GEOCODE_CACHE_FILE,
    GEOCODE_ENABLED,
    GEOCODE_MAX_PER_RUN,
    GEOCODE_USER_AGENT,
    GOOGLE_MAPS_API_KEY,
    LOCATIONIQ_API_KEY,
    NOMINATIM_ENDPOINT,
)

logger = logging.getLogger("geocoder")

BACKEND_NOMINATIM = "nominatim"
BACKEND_GOOGLE = "google"
BACKEND_LOCATIONIQ = "locationiq"
BACKEND_GEOAPIFY = "geoapify"

GOOGLE_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"
LOCATIONIQ_ENDPOINT = "https://us1.locationiq.com/v1/search"
GEOAPIFY_ENDPOINT = "https://api.geoapify.com/v1/geocode/search"

# Per-backend pacing and default per-run budget.
#
# The budgets sit below each provider's published free daily allowance so a
# single run cannot exhaust it, and the delays respect their rate limits. Verify
# the current published limits before raising these - free tiers change.
BACKEND_SETTINGS: Dict[str, Dict[str, float]] = {
    # Public OSM endpoint: hard policy limit of 1 req/sec, bulk use disallowed.
    BACKEND_NOMINATIM: {"delay": 1.1, "budget": 400},
    # Free tier is ~5k/day but only 1 req/sec - pacing at 0.55s (~1.8/s) earned
    # an HTTP 429 after just 79 lookups on a live run.
    BACKEND_LOCATIONIQ: {"delay": 1.05, "budget": 4500},
    # Free tier is on the order of 3k/day.
    BACKEND_GEOAPIFY: {"delay": 0.25, "budget": 2800},
    # Billable; the ceiling here is just a sanity cap, not a free allowance.
    BACKEND_GOOGLE: {"delay": 0.05, "budget": 10000},
}

# How many times to back off and retry a "slow down" 429 before giving up on the
# run. A daily-quota 429 is never retried.
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BACKOFF_SECONDS = [5, 15, 40]

# Bounding box around the Bengaluru metropolitan region (BMRDA extent).
# Anything resolved outside this box is treated as a bad match and discarded.
BLR_MIN_LAT, BLR_MAX_LAT = 12.20, 13.60
BLR_MIN_LNG, BLR_MAX_LNG = 76.90, 78.20


def resolve_backend() -> str:
    """
    Picks the geocoding backend.

    An explicit GEOCODE_BACKEND always wins. Otherwise the keyless public
    endpoint is the last resort, and a keyed provider is preferred because it can
    actually sustain a backlog. Free-tier providers are preferred over Google so
    that simply having a Maps key lying around never silently starts billing.
    """
    if GEOCODE_BACKEND:
        if GEOCODE_BACKEND not in BACKEND_SETTINGS:
            logger.warning(
                f"[Geocoder] Unknown GEOCODE_BACKEND '{GEOCODE_BACKEND}'; "
                f"falling back to auto-detection."
            )
        else:
            return GEOCODE_BACKEND

    if LOCATIONIQ_API_KEY:
        return BACKEND_LOCATIONIQ
    if GEOAPIFY_API_KEY:
        return BACKEND_GEOAPIFY
    if GOOGLE_MAPS_API_KEY:
        return BACKEND_GOOGLE
    return BACKEND_NOMINATIM


class Geocoder:
    """Disk-cached geocoder with a per-run lookup budget and pluggable backends."""

    def __init__(self, cache_file: Optional[Path] = None, backend: Optional[str] = None):
        self.cache_file = Path(cache_file or GEOCODE_CACHE_FILE)
        self.cache: Dict[str, Optional[list]] = self._load_cache()
        self.lookups_used = 0
        self.hits = 0
        self.misses = 0
        self.aborted = False

        self.backend = backend or resolve_backend()
        settings = BACKEND_SETTINGS.get(self.backend, BACKEND_SETTINGS[BACKEND_NOMINATIM])
        self.delay = float(settings["delay"])
        # GEOCODE_MAX_PER_RUN of 0 (the default) means "use the backend's own
        # sensible ceiling", so switching providers does not also require
        # remembering to retune the budget.
        self.max_lookups = GEOCODE_MAX_PER_RUN or int(settings["budget"])

        # Resolved by NAME, not bound here, so the backend method is looked up
        # at call time - otherwise overriding _lookup_nominatim on an instance
        # (as the tests do) would be silently ignored and hit the network.
        self._lookup_method = {
            BACKEND_NOMINATIM: "_lookup_nominatim",
            BACKEND_GOOGLE: "_lookup_google",
            BACKEND_LOCATIONIQ: "_lookup_locationiq",
            BACKEND_GEOAPIFY: "_lookup_geoapify",
        }[self.backend]

        logger.info(
            f"[Geocoder] Backend '{self.backend}' "
            f"({self.delay:g}s between calls, up to {self.max_lookups} lookups this run)."
        )
        if self.backend == BACKEND_NOMINATIM:
            logger.info(
                "[Geocoder] Using the public OpenStreetMap endpoint. Its usage policy "
                "forbids bulk geocoding, so the budget is kept small - set "
                "LOCATIONIQ_API_KEY or GEOAPIFY_API_KEY (free, no card) to drain a "
                "backlog faster, or NOMINATIM_ENDPOINT to your own instance."
            )

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
        if self.aborted:
            return 0
        return max(0, self.max_lookups - self.lookups_used)

    def _abort(self, reason: str):
        """
        Stops geocoding for the rest of this run.

        Used for conditions that will not improve by retrying - a rejected key,
        an unenabled API, an exhausted daily quota. Without this, a dead key
        burns the entire budget emitting one identical warning per row, which is
        exactly what a live run did: 102 REQUEST_DENIED warnings in 12 seconds
        before it was cancelled by hand.
        """
        if not self.aborted:
            self.aborted = True
            logger.error(f"[Geocoder] {reason} Geocoding stops for this run.")

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
        coords = self._lookup(address)

        if coords and not self._within_bangalore(coords):
            logger.debug(f"[Geocoder] Discarded out-of-region match for '{address}': {coords}")
            coords = None

        if self.aborted and not coords:
            # The lookup failed because of a key/quota problem, not because this
            # project has no coordinates. Caching it as a miss would permanently
            # skip the row once the key is fixed, so leave it uncached.
            return None

        self.cache[key] = [coords[0], coords[1]] if coords else None
        if coords:
            self.hits += 1
        else:
            self.misses += 1
        return coords

    def _lookup(self, address: str) -> Optional[Tuple[float, float]]:
        """Dispatches to the active backend, resolved by name at call time."""
        return getattr(self, self._lookup_method)(address)

    # --------------------------------------------------------------- backends
    def _get(self, url: str, params: dict, headers: Optional[dict] = None):
        """
        Shared request, pacing and error policy. Returns the parsed body, or None
        when there is no usable result.

        A 429 is retried with backoff unless it names a DAILY limit: providers use
        the same status for "too fast, slow down" and "you are out of quota until
        tomorrow", and only the second is worth ending the run over. Treating both
        as fatal cost a live run 4,421 of its 4,500 lookups.
        """
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                resp = requests.get(url, params=params, headers=headers or {}, timeout=20)
                time.sleep(self.delay)

                if resp.status_code in (401, 403):
                    self._abort(
                        f"{self.backend} rejected the API key (HTTP {resp.status_code}) - "
                        f"check the key is correct and the service is enabled."
                    )
                    return None

                if resp.status_code == 429:
                    body = (resp.text or "")[:200]
                    if "day" in body.lower() or "daily" in body.lower():
                        self._abort(
                            f"{self.backend} daily quota is exhausted ({body.strip()}). "
                            f"Remaining rows will be picked up on the next run."
                        )
                        return None
                    if attempt < RATE_LIMIT_RETRIES:
                        backoff = RATE_LIMIT_BACKOFF_SECONDS[attempt]
                        logger.info(
                            f"[Geocoder] {self.backend} asked us to slow down "
                            f"(HTTP 429); waiting {backoff}s and retrying."
                        )
                        time.sleep(backoff)
                        continue
                    self._abort(
                        f"{self.backend} still rate-limiting after "
                        f"{RATE_LIMIT_RETRIES} backoffs. Remaining rows will be "
                        f"retried on the next run."
                    )
                    return None

                # LocationIQ and Nominatim answer 404 for "nothing matched", which
                # is an ordinary miss rather than a failure worth warning about.
                if resp.status_code == 404:
                    return None

                if resp.status_code != 200:
                    logger.warning(f"[Geocoder] {self.backend} returned HTTP {resp.status_code}.")
                    return None

                return resp.json()
            except Exception as e:
                logger.warning(f"[Geocoder] {self.backend} request failed: {e}")
                time.sleep(self.delay)
                return None
        return None

    def _lookup_nominatim(self, address: str) -> Optional[Tuple[float, float]]:
        payload = self._get(
            NOMINATIM_ENDPOINT,
            {"q": address, "format": "json", "limit": 1, "countrycodes": "in"},
            {"User-Agent": GEOCODE_USER_AGENT},
        )
        return self._first_latlon_list(payload)

    def _lookup_locationiq(self, address: str) -> Optional[Tuple[float, float]]:
        # LocationIQ mirrors the Nominatim response shape.
        payload = self._get(
            LOCATIONIQ_ENDPOINT,
            {
                "key": LOCATIONIQ_API_KEY,
                "q": address,
                "format": "json",
                "limit": 1,
                "countrycodes": "in",
            },
        )
        return self._first_latlon_list(payload)

    def _lookup_geoapify(self, address: str) -> Optional[Tuple[float, float]]:
        payload = self._get(
            GEOAPIFY_ENDPOINT,
            {
                "text": address,
                "apiKey": GEOAPIFY_API_KEY,
                "limit": 1,
                "filter": "countrycode:in",
            },
        )
        if not isinstance(payload, dict):
            return None
        features = payload.get("features") or []
        if not features:
            return None
        props = features[0].get("properties") or {}
        try:
            return (float(props["lat"]), float(props["lon"]))
        except (KeyError, TypeError, ValueError):
            return None

    def _lookup_google(self, address: str) -> Optional[Tuple[float, float]]:
        payload = self._get(
            GOOGLE_ENDPOINT,
            {"address": address, "key": GOOGLE_MAPS_API_KEY, "region": "in"},
        )
        if not isinstance(payload, dict):
            return None
        status = payload.get("status")
        if status == "ZERO_RESULTS":
            return None
        if status in ("REQUEST_DENIED", "OVER_QUERY_LIMIT", "OVER_DAILY_LIMIT", "INVALID_REQUEST"):
            # REQUEST_DENIED almost always means the Geocoding API is not enabled
            # on the project, or the project has no billing account. Retrying
            # 5,000 times cannot fix either.
            self._abort(
                f"Google Geocoding returned '{status}' - "
                f"{payload.get('error_message', 'check the key, API enablement and billing.')}"
            )
            return None
        if status != "OK":
            logger.warning(f"[Geocoder] Google Geocoding status '{status}' for '{address}'.")
            return None
        try:
            loc = payload["results"][0]["geometry"]["location"]
            return (float(loc["lat"]), float(loc["lng"]))
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _first_latlon_list(payload) -> Optional[Tuple[float, float]]:
        """Parses the Nominatim-style `[{"lat": "...", "lon": "..."}]` response."""
        if not isinstance(payload, list) or not payload:
            return None
        try:
            return (float(payload[0]["lat"]), float(payload[0]["lon"]))
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _within_bangalore(coords: Tuple[float, float]) -> bool:
        lat, lng = coords
        return BLR_MIN_LAT <= lat <= BLR_MAX_LAT and BLR_MIN_LNG <= lng <= BLR_MAX_LNG
