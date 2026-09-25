"""
Main execution pipeline for Bangalore Real Estate Scraper & K-RERA Two-Stage Syncer.
Workflow:
1. Scrapes all 8,900+ raw project registrations from https://rera.karnataka.gov.in/viewAllProjects?language=en
2. Syncs raw records into the 'KRERA_Raw_Projects' Google Sheet.
3. Enriches Bangalore metropolitan projects with micro-markets, builder brands, configurations & amenities.
4. Integrates with Propsoch and 99Acres portal listings and Gemini market intelligence.
5. Syncs the enriched dataset into the main 'Bangalore_Projects' Google Sheet.
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
    GOOGLE_SHEET_NAME,
    PERPLEXITY_API_KEY,
    SEARCH_STRATEGY,
)
from src.enricher import ProjectEnricher
from src.gsheet_manager import GoogleSheetManager
from src.models import ScrapeRunSummary
from src.scrapers.aggregator import RealEstateAggregator
from src.scrapers.krera_scraper import KRERAParser

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("main")


def run_pipeline() -> dict:
    """Executes the two-stage K-RERA and portal scraping and synchronization pipeline."""
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
    for raw_p in raw_krera_projects:
        if raw_p.is_bangalore_region():
            enriched = enricher.enrich_raw_project(raw_p)
            if enriched:
                enriched_rera_projects.append(enriched)

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
            summary = ScrapeRunSummary(
                engine_used="K-RERA Portal + Propsoch + 99Acres + Gemini",
                total_found=total_bangalore_projects,
                new_added=new_added,
                existing_updated=existing_updated,
                status=sync_status,
                notes_or_errors=f"K-RERA Raw: {total_raw_krera} ({raw_added_count} new). Bangalore Enriched: {new_added} new, {existing_updated} updated."
            )
            gsheet.log_run(summary)
            if gsheet.sheet_url:
                logger.info(f"📊 Google Sheet Live URL: {gsheet.sheet_url}")
        except Exception as e:
            logger.error(f"Google Sheet synchronization failed: {e}", exc_info=True)
            sync_status = "PARTIAL_FAILURE"
    else:
        logger.warning("Google Sheet not connected. Results saved to local JSON backup.")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("==================================================================")
    logger.info(f"✅ Pipeline Completed in {elapsed:.1f}s")
    logger.info(f"   • Total K-RERA Raw Scraped: {total_raw_krera}")
    logger.info(f"   • New K-RERA Raw Added: {raw_added_count}")
    logger.info(f"   • Total Bangalore Projects: {total_bangalore_projects}")
    logger.info(f"   • Brand New Added to Bangalore_Projects: {new_added}")
    logger.info(f"   • Existing Rows Updated: {existing_updated}")
    logger.info("==================================================================")

    return {
        "status": sync_status,
        "total_raw_krera": total_raw_krera,
        "raw_added": raw_added_count,
        "total_bangalore_projects": total_bangalore_projects,
        "new_added": new_added,
        "existing_updated": existing_updated,
        "elapsed_seconds": elapsed,
        "sheet_url": gsheet.sheet_url if gsheet.client else None
    }


if __name__ == "__main__":
    result = run_pipeline()
    if result.get("status") == "FAILED":
        sys.exit(1)
    sys.exit(0)
