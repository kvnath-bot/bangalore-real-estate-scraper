"""
One-off cleanup for duplicate rows already sitting in the tracker spreadsheet.

Duplicates accumulated because the old deduplication keyed a project by EITHER
its RERA number OR its name+builder, never both, so the same project discovered
once with a registration number and once without became two rows. The pipeline
no longer does that (see RealEstateProject.identity_keys), but rows written
before the fix are still there. This script collapses them.

It is deliberately conservative:

  * Dry run by default. Nothing is written or deleted without --apply.
  * Always writes a timestamped JSON backup of every row before touching
    anything, so a bad run can be reconstructed.
  * Merging reuses RealEstateAggregator._deduplicate_and_merge - the exact same
    logic the live pipeline uses - so the cleanup cannot disagree with it.
  * The surviving row is the earliest one (lowest row number), which preserves
    the original First Discovered date.
  * Any cluster that does not collapse to a single record is reported and
    skipped rather than guessed at.

Usage:

    # See what would change - reads only, writes nothing
    python scripts/dedupe_sheet.py

    # Same, but for the raw K-RERA registry instead
    python scripts/dedupe_sheet.py --worksheet KRERA_Raw_Projects

    # Actually merge and delete
    python scripts/dedupe_sheet.py --apply

    # Backup only, no analysis
    python scripts/dedupe_sheet.py --backup-only
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.gsheet_manager import (  # noqa: E402
    KRERA_RAW_WORKSHEET_NAME,
    PROJECTS_WORKSHEET_NAME,
    GoogleSheetManager,
)
from src.models import RealEstateProject  # noqa: E402
from src.scrapers.aggregator import RealEstateAggregator  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("dedupe")

BACKUP_DIR = ROOT_DIR / "backups"


# --------------------------------------------------------------------------- #
# Clustering
# --------------------------------------------------------------------------- #
class _DisjointSet:
    """Union-find, so rows linked through a shared key end up in one cluster."""

    def __init__(self):
        self.parent: Dict[int, int] = {}

    def find(self, item: int) -> int:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: int, b: int):
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            # Keep the smaller row number as the root: it is the survivor.
            if root_b < root_a:
                root_a, root_b = root_b, root_a
            self.parent[root_b] = root_a


def cluster_project_rows(rows: List[Tuple[int, List[str]]]) -> List[List[int]]:
    """
    Groups Bangalore_Projects rows that refer to the same project.

    Two rows belong together when they share ANY identity key - a RERA number or
    a name+builder pair - which is exactly the relation the old keying missed.
    """
    dsu = _DisjointSet()
    key_owner: Dict[str, int] = {}

    for row_num, row in rows:
        project = RealEstateProject.from_sheet_row(row)
        dsu.find(row_num)
        for key in project.identity_keys():
            if key in key_owner:
                dsu.union(key_owner[key], row_num)
            else:
                key_owner[key] = row_num

    grouped: Dict[int, List[int]] = {}
    for row_num, _ in rows:
        grouped.setdefault(dsu.find(row_num), []).append(row_num)

    return [sorted(members) for members in grouped.values() if len(members) > 1]


def cluster_raw_rows(rows: List[Tuple[int, List[str]]]) -> List[List[int]]:
    """
    Groups KRERA_Raw_Projects rows by RERA registration number (column A).
    That sheet has one row per registration, so an exact match is a duplicate.
    """
    by_rera: Dict[str, List[int]] = {}
    for row_num, row in rows:
        rera = (row[0].strip() if row else "")
        if not rera:
            continue
        by_rera.setdefault(rera.lower(), []).append(row_num)
    return [sorted(members) for members in by_rera.values() if len(members) > 1]


# --------------------------------------------------------------------------- #
# Merging
# --------------------------------------------------------------------------- #
def merge_project_cluster(
    cluster: List[int], row_map: Dict[int, List[str]]
) -> Tuple[RealEstateProject, List[str]]:
    """
    Collapses a cluster into one record using the pipeline's own merge rules.

    Returns the merged project and a human-readable list of what it gained from
    the rows being removed.
    """
    ordered = [RealEstateProject.from_sheet_row(row_map[r]) for r in cluster]
    survivor_before = ordered[0].model_dump()

    merged_list = RealEstateAggregator._deduplicate_and_merge(
        RealEstateAggregator.__new__(RealEstateAggregator), ordered
    )
    if len(merged_list) != 1:
        raise ValueError(
            f"cluster {cluster} did not collapse to one record "
            f"(got {len(merged_list)}); skipping to stay safe"
        )
    merged = merged_list[0]

    # Keep the earliest discovery date and the latest update stamp across the
    # whole cluster, which the pairwise merge does not guarantee on its own.
    discovered = [p.first_discovered for p in ordered if p.first_discovered]
    updated = [p.last_updated for p in ordered if p.last_updated]
    if discovered:
        merged.first_discovered = min(discovered)
    if updated:
        merged.last_updated = max(updated)

    after = merged.model_dump()
    changes = [
        f"{field}: {survivor_before[field]!r} -> {after[field]!r}"
        for field in after
        if survivor_before.get(field) != after[field]
    ]
    return merged, changes


# --------------------------------------------------------------------------- #
# Sheet operations
# --------------------------------------------------------------------------- #
def write_backup(worksheet_name: str, values: List[List[str]]) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"{worksheet_name}-{stamp}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "worksheet": worksheet_name,
                "captured_at": datetime.now().isoformat(timespec="seconds"),
                "row_count": len(values),
                "values": values,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    logger.info(f"Backup of {len(values)} rows written to {path}")
    return path


def delete_rows(worksheet, row_numbers: List[int]):
    """
    Deletes the given 1-based sheet rows in one API call.

    Rows are merged into contiguous blocks and submitted in DESCENDING order so
    that earlier deletions never shift the indices of later ones.
    """
    if not row_numbers:
        return

    blocks: List[Tuple[int, int]] = []
    for row in sorted(row_numbers):
        if blocks and row == blocks[-1][1] + 1:
            blocks[-1] = (blocks[-1][0], row)
        else:
            blocks.append((row, row))

    requests = [
        {
            "deleteDimension": {
                "range": {
                    "sheetId": worksheet.id,
                    "dimension": "ROWS",
                    "startIndex": start - 1,  # API is 0-based, end-exclusive
                    "endIndex": end,
                }
            }
        }
        for start, end in reversed(blocks)
    ]
    logger.info(f"Deleting {len(row_numbers)} rows in {len(requests)} block(s)...")
    worksheet.spreadsheet.batch_update({"requests": requests})


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collapse duplicate rows already present in the tracker spreadsheet."
    )
    parser.add_argument(
        "--worksheet",
        default=PROJECTS_WORKSHEET_NAME,
        choices=[PROJECTS_WORKSHEET_NAME, KRERA_RAW_WORKSHEET_NAME],
        help=f"Worksheet to clean (default: {PROJECTS_WORKSHEET_NAME})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually merge and delete. Without this the script only reports.",
    )
    parser.add_argument(
        "--backup-only",
        action="store_true",
        help="Write the backup and exit without analysing anything.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the backup. Refused together with --apply.",
    )
    args = parser.parse_args()

    if args.apply and args.no_backup:
        logger.error("--no-backup cannot be combined with --apply. Refusing to run.")
        return 2

    gsheet = GoogleSheetManager()
    if not gsheet.client or not gsheet.spreadsheet:
        logger.error(
            "No Google Sheets credentials available. Set GCP_SERVICE_ACCOUNT_KEY or "
            "provide a service_account.json file."
        )
        return 1

    try:
        worksheet = gsheet.spreadsheet.worksheet(args.worksheet)
    except Exception as e:
        logger.error(f"Could not open worksheet '{args.worksheet}': {e}")
        return 1

    all_values = worksheet.get_all_values()
    if len(all_values) <= 1:
        logger.info(f"'{args.worksheet}' has no data rows. Nothing to do.")
        return 0

    if not args.no_backup:
        write_backup(args.worksheet, all_values)
    if args.backup_only:
        logger.info("--backup-only given; stopping here.")
        return 0

    data_rows = [
        (idx, row)
        for idx, row in enumerate(all_values[1:], start=2)
        if row and any(cell.strip() for cell in row)
    ]
    row_map = {idx: row for idx, row in data_rows}
    logger.info(f"Read {len(data_rows)} data rows from '{args.worksheet}'.")

    is_projects = args.worksheet == PROJECTS_WORKSHEET_NAME
    clusters = (cluster_project_rows if is_projects else cluster_raw_rows)(data_rows)

    if not clusters:
        logger.info("No duplicates found. Nothing to do.")
        return 0

    doomed: List[int] = []
    survivor_updates: List[Tuple[int, List[str]]] = []
    skipped = 0

    print("\n" + "=" * 78)
    print(f"  DUPLICATE CLUSTERS IN '{args.worksheet}'")
    print("=" * 78)

    for cluster in clusters:
        survivor, duplicates = cluster[0], cluster[1:]
        label = row_map[survivor][0] if row_map[survivor] else "(blank)"
        print(f"\n[{label}]")
        print(f"  keep   row {survivor}")
        for row_num in duplicates:
            print(f"  remove row {row_num}")

        if is_projects:
            try:
                merged, changes = merge_project_cluster(cluster, row_map)
            except ValueError as e:
                logger.warning(f"  !! {e}")
                skipped += 1
                continue
            if changes:
                print("  survivor gains:")
                for change in changes:
                    print(f"    - {change}")
            else:
                print("  survivor already has the richest values; no field changes")
            survivor_updates.append((survivor, merged.to_sheet_row()))

        doomed.extend(duplicates)

    print("\n" + "-" * 78)
    print(f"  clusters found ......... {len(clusters)}")
    print(f"  clusters skipped ....... {skipped}")
    print(f"  rows to delete ......... {len(doomed)}")
    print(f"  rows after cleanup ..... {len(data_rows) - len(doomed)}")
    print("-" * 78)

    if not args.apply:
        print("\nDRY RUN - nothing was changed. Re-run with --apply to perform it.\n")
        return 0

    # Update survivors BEFORE deleting, while their row numbers are still valid.
    if survivor_updates:
        logger.info(f"Updating {len(survivor_updates)} surviving rows...")
        last_col = chr(ord("A") + len(RealEstateProject.sheet_headers()) - 1)
        payload = [
            {"range": f"A{row_num}:{last_col}{row_num}", "values": [values]}
            for row_num, values in survivor_updates
        ]
        for i in range(0, len(payload), 100):
            worksheet.batch_update(payload[i:i + 100], value_input_option="USER_ENTERED")

    delete_rows(worksheet, doomed)

    logger.info(
        f"Cleanup complete: {len(doomed)} duplicate rows removed from "
        f"'{args.worksheet}', {len(survivor_updates)} survivors enriched."
    )
    print(f"\nSheet: {gsheet.sheet_url}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
