"""
Main execution pipeline for Bangalore Real Estate Scraper & K-RERA Two-Stage Syncer.
Workflow:
1. Scrapes all 8,900+ raw project registrations from https://rera.karnataka.gov.in/viewAllProjects?language=en
2. Syncs raw records into the 'KRERA_Raw_Projects' Google Sheet.
3. Enriches Bangalore metropolitan projects with micro-markets, builder brands, configurations & amenities.
4. Integrates with Propsoch and 99Acres portal listings and Gemini market intelligence.
5. Syncs the enriched dataset into the main 'Bangalore_Projects' Google Sheet.
6. Updates 'Enrichment Status' column in 'KRERA_Raw_Projects' to reflect enriched/synced status.
7. Geocodes Bangalore-region registrations and writes Latitude / Longitude / Map Pin Link.
8. Shares the spreadsheet with the configured SHARE_WITH_EMAILS recipients.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import (
    GEMINI_API_KEY,
    GEOCODE_ENABLED,
    GOOGLE_SHEET_NAME,
    PERPLEXITY_API_KEY,
    SEARCH_STRATEGY,
    SHARE_WITH_EMAILS,
)
from src.geocoder import Geocoder
from src.enricher import ProjectEnricher
from src.gsheet_manager import GoogleSheetManager
from src.models import KRERARawProject, ScrapeRunSummary
from src.scrapers.aggregator import RealEstateAggregator
from src.scrapers.krera_scraper import KRERAParser

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("main")


def run_geocoding_stage(gsheet: GoogleSheetManager) -> int:
    """
    Resolves coordinates for KRERA_Raw_Projects rows that do not have them yet
    and writes Latitude / Longitude / Map Pin Link back in batched ranges.

    Only Bangalore-region rows are sent to the geocoder - the rest of Karnataka
    is out of scope for this tracker. Every row still receives a map pin link:
    an exact coordinate pin when geocoding succeeded, otherwise a Google Maps
    name search, so no cell is left dead.

    Lookups are capped at GEOCODE_MAX_PER_RUN per run and cached on disk, so a
    large backlog drains over consecutive daily runs instead of one long job.
    """
    pending = gsheet.get_krera_rows_needing_coordinates()
    if not pending:
        logger.info("[Geocoder] Every row already has coordinates. Nothing to do.")
        return 0

    geocoder = Geocoder()
    row_values = {}
    attempted = 0

    for entry in pending:
        raw = KRERARawProject(
            rera_number=entry["rera_number"],
            project_name=entry["project_name"] or entry["rera_number"],
            promoter_name="",
            district=entry["district"] or KRERARawProject.get_district_from_rera(entry["rera_number"]),
        )

        latitude = ""
        longitude = ""
        if raw.is_bangalore_region():
            before = geocoder.lookups_used
            coords = geocoder.geocode_address(raw.geocode_query())
            attempted += geocoder.lookups_used - before
            if coords:
                latitude = f"{coords[0]:.6f}"
                longitude = f"{coords[1]:.6f}"

        raw.latitude = latitude
        raw.longitude = longitude
        link = raw.build_map_pin_link()

        # Skip rows where nothing useful changed: no coordinates found and the
        # row already carries a search link from a previous run.
        if not latitude and not raw.is_bangalore_region():
            continue

        row_values[entry["row"]] = [latitude, longitude, link]

        if attempted and attempted % 50 == 0:
            logger.info(
                f"[Geocoder] {attempted} lookups attempted "
                f"({geocoder.hits} resolved, {geocoder.misses} unresolved, "
                f"{geocoder.budget_remaining} of this run's budget left)."
            )

    geocoder.save_cache()
    logger.info(
        f"[Geocoder] Lookups this run: {geocoder.lookups_used}/{geocoder.max_lookups} "
        f"via '{geocoder.backend}' "
        f"| resolved: {geocoder.hits} | unresolved: {geocoder.misses} "
        f"| rows still awaiting coordinates: {max(0, len(pending) - geocoder.hits)}"
    )

    return gsheet.update_krera_map_columns(row_values)


def run_pipeline() -> dict:
    """Executes the two-stage K-RERA and portal scraping, enrichment, and synchronization pipeline."""
    start_time = datetime.now()
    logger.info("==================================================================")
    logger.info("  🚀 Starting Bangalore Real Estate Automated K-RERA & Portal Scraper")
    logger.info("==================================================================")
    logger.info(f"Time: {start_time.strftime('%Y-%m-%d %H:%M:%S IST')}")
    logger.info(f"Target Sheet: '{GOOGLE_SHEET_NAME}'")
    logger.info(f"Active AI Strategy: '{SEARCH_STRATEGY}'")

    gsheet = GoogleSheetManager()

    # --------------------------------------------------------------------------
    # STAGE 1: Scrape All Raw K-RERA Records & Sync to 'KRERA_Raw_Projects' Sheet
    # --------------------------------------------------------------------------
    logger.info("------------------------------------------------------------------")
    logger.info(" [STAGE 1] Fetching all raw projects from Karnataka RERA Portal...")
    logger.info("------------------------------------------------------------------")
    krera_parser = KRERAParser()
    raw_krera_projects = krera_parser.fetch_all_raw_projects()
    total_raw_krera = len(raw_krera_projects)

    raw_added_count = 0
    if gsheet.client and gsheet.krera_raw_sheet:
        raw_added_count = gsheet.sync_krera_raw_projects(raw_krera_projects)

    # --------------------------------------------------------------------------
    # STAGE 2: Enrich Bangalore RERA Projects & Integrate Propsoch / 99Acres / AI
    # --------------------------------------------------------------------------
    logger.info("------------------------------------------------------------------")
    logger.info(" [STAGE 2] Enriching Bangalore RERA records & Aggregating Portals...")
    logger.info("------------------------------------------------------------------")
    enricher = ProjectEnricher()
    enriched_rera_projects = []
    rera_status_map = {}

    for raw_p in raw_krera_projects:
        clean_rera = raw_p.rera_number.strip()
        if raw_p.is_bangalore_region():
            enriched = enricher.enrich_raw_project(raw_p)
            if enriched:
                enriched_rera_projects.append(enriched)
                rera_status_map[clean_rera] = "Enriched & Synced (Bangalore)"
            else:
                rera_status_map[clean_rera] = "Pending"
        else:
            rera_status_map[clean_rera] = f"Non-Bangalore ({raw_p.district})"

    logger.info(f"[Enricher] Prepared {len(enriched_rera_projects)} enriched Bangalore projects from K-RERA.")

    # Aggregate with Propsoch, 99Acres, and Gemini intelligence
    aggregator = RealEstateAggregator()
    try:
        portal_and_ai_projects = aggregator.run_full_scan()
    except Exception as e:
        logger.error(f"Portal/AI scan encountered error: {e}")
        portal_and_ai_projects = []

    # Combine all enriched projects and deduplicate
    all_combined = portal_and_ai_projects + enriched_rera_projects
    final_unique_projects = aggregator._deduplicate_and_merge(all_combined)
    total_bangalore_projects = len(final_unique_projects)
    logger.info(f"[Pipeline] Final unique Bangalore projects to sync: {total_bangalore_projects}")

    # Save local backup
    backup_file = ROOT_DIR / "scraped_projects_latest.json"
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump([p.model_dump() for p in final_unique_projects], f, indent=2, ensure_ascii=False)

    # --------------------------------------------------------------------------
    # STAGE 3: Sync Enriched Projects to 'Bangalore_Projects' Google Sheet
    # --------------------------------------------------------------------------
    logger.info("------------------------------------------------------------------")
    logger.info(" [STAGE 3] Syncing Enriched Projects to 'Bangalore_Projects' Sheet...")
    logger.info("------------------------------------------------------------------")
    new_added = 0
    existing_updated = 0
    sync_status = "SUCCESS"

    if gsheet.client and gsheet.projects_sheet:
        try:
            new_added, existing_updated = gsheet.sync_projects(final_unique_projects)

            # Update Enrichment Status in KRERA_Raw_Projects sheet
            if gsheet.krera_raw_sheet and rera_status_map:
                gsheet.update_krera_enrichment_statuses(rera_status_map)

            summary = ScrapeRunSummary(
                engine_used="K-RERA Portal + Propsoch + 99Acres + Gemini",
                total_found=total_bangalore_projects,
                new_added=new_added,
                existing_updated=existing_updated,
                status=sync_status,
                notes_or_errors=f"K-RERA Raw: {total_raw_krera} ({raw_added_count} new). Bangalore Enriched: {new_added} new, {existing_updated} matched."
            )
            gsheet.log_run(summary)
            if gsheet.sheet_url:
                logger.info(f"📊 Google Sheet Live URL: {gsheet.sheet_url}")
        except Exception as e:
            logger.error(f"Google Sheet synchronization failed: {e}", exc_info=True)
            sync_status = "PARTIAL_FAILURE"
    else:
        logger.warning("Google Sheet not connected. Results saved to local JSON backup.")

    # --------------------------------------------------------------------------
    # STAGE 4: Geocode Bangalore Registrations & Write Map Pin Links
    # --------------------------------------------------------------------------
    geocoded_count = 0
    if GEOCODE_ENABLED and gsheet.client and gsheet.krera_raw_sheet:
        logger.info("------------------------------------------------------------------")
        logger.info(" [STAGE 4] Geocoding K-RERA projects & building map pin links...")
        logger.info("------------------------------------------------------------------")
        try:
            geocoded_count = run_geocoding_stage(gsheet)
        except Exception as e:
            logger.error(f"Geocoding stage failed: {e}", exc_info=True)
    elif not GEOCODE_ENABLED:
        logger.info("[STAGE 4] Geocoding disabled via GEOCODE_ENABLED=false. Skipping.")

    # --------------------------------------------------------------------------
    # STAGE 5: Share the Spreadsheet with the Configured Recipients
    # --------------------------------------------------------------------------
    shared_with = []
    if gsheet.client and SHARE_WITH_EMAILS:
        logger.info("------------------------------------------------------------------")
        logger.info(f" [STAGE 5] Sharing spreadsheet with {len(SHARE_WITH_EMAILS)} recipient(s)...")
        logger.info("------------------------------------------------------------------")
        shared_with = gsheet.share_with_emails()

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("==================================================================")
    logger.info(f"✅ Pipeline Completed in {elapsed:.1f}s")
    logger.info(f"   • Total K-RERA Raw Scraped: {total_raw_krera}")
    logger.info(f"   • New K-RERA Raw Added: {raw_added_count}")
    logger.info(f"   • Total Bangalore Projects: {total_bangalore_projects}")
    logger.info(f"   • Brand New Added to Bangalore_Projects: {new_added}")
    logger.info(f"   • Existing Rows Matched: {existing_updated}")
    logger.info(f"   • Rows Geocoded This Run: {geocoded_count}")
    logger.info(f"   • Shared With: {', '.join(shared_with) if shared_with else 'nobody new'}")
    logger.info("==================================================================")

    return {
        "status": sync_status,
        "total_raw_krera": total_raw_krera,
        "raw_added": raw_added_count,
        "total_bangalore_projects": total_bangalore_projects,
        "new_added": new_added,
        "existing_updated": existing_updated,
        "geocoded": geocoded_count,
        "shared_with": shared_with,
        "elapsed_seconds": elapsed,
        "sheet_url": gsheet.sheet_url if gsheet.client else None
    }


if __name__ == "__main__":
    result = run_pipeline()
    if result.get("status") == "FAILED":
        sys.exit(1)
    sys.exit(0)
