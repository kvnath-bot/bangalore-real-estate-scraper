"""
Listing data: the price / configuration / possession layer the registry lacks.

K-RERA publishes none of this, and the pipeline's enricher only ever wrote
placeholders for it ("On Request / RERA Verified", "2, 3 & 4 BHK" on every
row). This module owns the one place real values live:

  * the Listing_Data worksheet, keyed by RERA number, filled by agents as they
    research projects, and seeded once from src/data/listing_seed.csv;
  * the parsers that turn what people type ("1.2 Cr", "2, 3 & 4 BHK") into
    numbers the map can filter on;
  * a strict property-type guess from the registered name, for rows nobody
    has entered yet - with "Unknown" as an honest answer.

A row is only ever ADDED by the seed; anything an agent has entered is never
overwritten. Provenance (source URL, who, when) is part of the row.
"""

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

LISTING_HEADERS = [
    "Karnataka RERA No.",
    "Property Type",
    "BHK Options",
    "Starting Price (Rs Lakh)",
    "Possession",
    "Sale Status",
    "Source URL",
    "Entered By",
    "Entered On",
    "Notes",
]

PROPERTY_TYPES = ["Apartment", "Villa", "Row House / Townhouse", "Plots", "Commercial", "Unknown"]
SALE_STATUSES = ["Available", "Sold Out", "Not Launched", "Unknown"]

SEED_FILE = Path(__file__).resolve().parent / "data" / "listing_seed.csv"

# Deliberately stricter than the enricher's keyword list, which files "Brigade
# Meadows" and "Sobha Dream Acres" (both apartments) under plots because of the
# words "meadows" and "acres". A wrong type is worse than Unknown.
_TYPE_RULES = [
    ("Row House / Townhouse", re.compile(r"row\s*house|rowhouse|row\s*villa|town\s*house|townhome|twin\s*house", re.I)),
    ("Villa", re.compile(r"\bvillas?\b|villament|\bbungalows?\b", re.I)),
    ("Plots", re.compile(r"\bplots?\b|\bplotted\b|\blayout\b|\bsites?\b|badavane", re.I)),
    ("Commercial", re.compile(r"commercial|\bmall\b|\boffice|tech\s*park|\bplaza\b|\bretail\b|\bit park\b", re.I)),
    ("Apartment", re.compile(r"apartment|\bflats?\b|residenc|\bheights\b|\btowers?\b|\bhomes\b", re.I)),
]

_BHK_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:&\s*)?(?=\s*(?:,|&|and|/|-|to|\s|bhk|$))", re.I)
_CR_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(cr|crore|crores)\b", re.I)
_LAKH_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(l|lac|lacs|lakh|lakhs)\b", re.I)


def type_from_name(project_name: str) -> str:
    """Best-effort property type from the registered name; 'Unknown' when the name says nothing."""
    name = project_name or ""
    for label, pattern in _TYPE_RULES:
        if pattern.search(name):
            return label
    return "Unknown"


def parse_bhk(text: str) -> List[int]:
    """
    '2, 3 & 4 BHK' -> [2, 3, 4]; '3.5 BHK' -> [3]; 'Studio' -> [1]; '' -> [].
    Whole bedrooms only - a 2.5 BHK filters as a 2.
    """
    if not text:
        return []
    t = text.lower()
    found = set()
    if "studio" in t or re.search(r"\b1\s*rk\b", t):
        found.add(1)
    for m in re.finditer(r"(\d+)(?:\.\d+)?\s*(?:&|,|/|and|to|-|\s)*", t):
        n = int(m.group(1))
        if 1 <= n <= 9:
            found.add(n)
    # a plain "2-4 BHK" range means every size between
    rng = re.search(r"(\d)\s*(?:-|to)\s*(\d)\s*bhk", t)
    if rng:
        a, b = int(rng.group(1)), int(rng.group(2))
        if 1 <= a <= b <= 9:
            found.update(range(a, b + 1))
    return sorted(found)


def parse_price_lakh(text: str) -> Optional[float]:
    """
    Normalises a typed price to rupees-lakh.
      '1.2 Cr' -> 120.0   '85 L' -> 85.0   '85 lakh' -> 85.0
      '1,20,00,000' -> 120.0 (rupees)   '120' -> 120.0 (assumed lakh)
    Returns None when nothing numeric is there.
    """
    if not text:
        return None
    t = text.strip()
    m = _CR_RE.search(t)
    if m:
        return round(float(m.group(1).replace(",", ".")) * 100, 2)
    m = _LAKH_RE.search(t)
    if m:
        return round(float(m.group(1).replace(",", ".")), 2)
    digits = re.sub(r"[^\d.]", "", t)
    if not digits or digits == ".":
        return None
    try:
        value = float(digits)
    except ValueError:
        return None
    if value >= 1_000_000:          # typed in rupees
        return round(value / 100_000, 2)
    return round(value, 2)          # typed in lakh


def normalise_type(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return ""
    for label in PROPERTY_TYPES:
        if t == label.lower():
            return label
    if "villa" in t: return "Villa"
    if "row" in t or "town" in t: return "Row House / Townhouse"
    if "plot" in t or "site" in t or "layout" in t: return "Plots"
    if "commercial" in t or "office" in t or "retail" in t: return "Commercial"
    if "apart" in t or "flat" in t: return "Apartment"
    return "Unknown"


def load_listing_rows(rows: Iterable[List[str]]) -> Dict[str, Dict]:
    """
    Turns Listing_Data rows (header excluded) into {rera: record}, normalised.
    Later rows win, so an agent correcting an entry can append a new line.
    """
    def cell(row, i):
        return row[i].strip() if len(row) > i and row[i] else ""

    out: Dict[str, Dict] = {}
    for row in rows:
        rera = cell(row, 0)
        if not rera:
            continue
        out[rera] = {
            "rera": rera,
            "type": normalise_type(cell(row, 1)),
            "bhk": parse_bhk(cell(row, 2)),
            "bhk_text": cell(row, 2),
            "price_lakh": parse_price_lakh(cell(row, 3)),
            "price_text": cell(row, 3),
            "possession": cell(row, 4),
            "sale_status": cell(row, 5),
            "source": cell(row, 6),
            "entered_by": cell(row, 7),
            "entered_on": cell(row, 8),
            "notes": cell(row, 9),
        }
    return out


def read_seed(path: Path = SEED_FILE) -> List[List[str]]:
    """Reads the seed CSV as sheet rows (header excluded). Missing file -> []."""
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = [r for r in reader if any(c.strip() for c in r)]
    if rows and [c.strip() for c in rows[0]] == LISTING_HEADERS:
        rows = rows[1:]
    return [r + [""] * (len(LISTING_HEADERS) - len(r)) for r in rows]


def rows_to_add(existing_reras: Iterable[str], seed_rows: List[List[str]]) -> List[List[str]]:
    """
    Seed rows whose RERA number is not already in the sheet. Existing rows
    are never touched: an agent's entry always outranks the seed.
    """
    have = {r.strip() for r in existing_reras if r and r.strip()}
    fresh, seen = [], set()
    for row in seed_rows:
        rera = (row[0] if row else "").strip()
        if not rera or rera in have or rera in seen:
            continue
        seen.add(rera)
        fresh.append(row[: len(LISTING_HEADERS)])
    return fresh


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")
