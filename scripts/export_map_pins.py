"""
Exports every located project as GeoJSON for the static map page in site/.

The daily workflow runs this after the pipeline and deploys site/ to GitHub
Pages, so the map refreshes itself after every run: no My Maps reimport, no
2,000-row layer cap, and nothing for a person to do.

Only rows with BOTH a latitude and a longitude are exported. Rows the geocoder
could not place are counted in the meta block but never drawn - a guess is not
a pin.

Usage:
    python scripts/export_map_pins.py                 # -> site/pins.geojson
    python scripts/export_map_pins.py --out /tmp/p.geojson
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.gsheet_manager import GoogleSheetManager  # noqa: E402
from src.models import KRERARawProject  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("export_map_pins")

DEFAULT_OUT = ROOT_DIR / "site" / "pins.geojson"


def _cell(row: List[str], idx: int) -> str:
    return row[idx].strip() if len(row) > idx and row[idx] else ""


def build_geojson(rows: List[List[str]], generated_at: datetime) -> Dict:
    """
    Turns KRERA_Raw_Projects rows (header excluded) into a FeatureCollection.

    Pure, so it can be tested without a sheet. Column positions follow
    KRERARawProject.sheet_headers(): A rera, B name, C promoter, E district,
    J latitude, K longitude, L map link, M geocode status.
    """
    features = []
    in_region_total = 0
    districts: Dict[str, int] = {}

    for row in rows:
        rera = _cell(row, 0)
        if not rera:
            continue
        try:
            raw = KRERARawProject(
                rera_number=rera,
                project_name=_cell(row, 1) or rera,
                promoter_name=_cell(row, 2),
                district=_cell(row, 4) or "Other Karnataka",
            )
        except Exception:
            continue
        if not raw.is_bangalore_region():
            continue
        in_region_total += 1

        lat, lng = _cell(row, 9), _cell(row, 10)
        if not lat or not lng:
            continue
        try:
            lat_f, lng_f = float(lat), float(lng)
        except ValueError:
            continue

        districts[raw.district] = districts.get(raw.district, 0) + 1
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lng_f, 6), round(lat_f, 6)]},
            "properties": {
                "name": raw.project_name,
                "promoter": raw.promoter_name,
                "district": raw.district,
                "rera": rera,
                "link": _cell(row, 11),
                "status": _cell(row, 12),
            },
        })

    return {
        "type": "FeatureCollection",
        "meta": {
            "generated_at": generated_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "located": len(features),
            "in_region_total": in_region_total,
            "unlocated": in_region_total - len(features),
            "districts": districts,
        },
        "features": features,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export located projects as GeoJSON for the map page.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"Output path (default: {DEFAULT_OUT})")
    args = parser.parse_args()

    gsheet = GoogleSheetManager()
    if not gsheet.client or not gsheet.krera_raw_sheet:
        logger.error("No Google Sheets credentials or KRERA_Raw_Projects worksheet available.")
        return 1

    all_rows = gsheet.krera_raw_sheet.get_all_values()
    collection = build_geojson(all_rows[1:], datetime.now(timezone.utc))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    m = collection["meta"]
    logger.info(
        f"Wrote {m['located']} pins to {args.out} "
        f"({m['unlocated']} of {m['in_region_total']} Bengaluru-region rows still unlocated)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
