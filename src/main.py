"""
Main execution entry point for Bangalore Real Estate Scraper & Google Sheet Syncer.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import (
    GEMINI_API_KEY,
    GOOGLE_SHEET_NAME,
    PERPLEXITY_API_KEY,
    SEARCH_STRATEGY,
)
from src.gsheet_manager import GoogleSheetManager
from src.models import ScrapeRunSummary
from src.scrapers.aggregator import RealEstateAggregator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("main")


def run_pipeline() -> dict:
    """Executes the complete scraping and synchronization workflow."""
    start_time = datetime.now()
    logger.info("==================================================================")
    logger.info("  🚀 Starting Bangalore Real Estate Automated Daily Scraper")
    logger.info("==================================================================")
    logger.info(f"Time: {start_time.strftime('%Y-%m-%d %H:%M:%S IST')}")
    logger.info(f"Target Sheet: '{GOOGLE_SHEET_NAME}'")
    logger.info(f"Active AI Strategy: '{SEARCH_STRATEGY}'")
    logger.info(f"Gemini API Configured: {'Yes' if GEMINI_API_KEY else 'No'}")
    logger.info(f"Perplexity API Configured: {'Yes' if PERPLEXITY_API_KEY else 'No'}")

    if not GEMINI_API_KEY and not PERPLEXITY_API_KEY:
        logger.error("❌ No AI Search API key configured! Please set GEMINI_API_KEY or PERPLEXITY_API_KEY in .env.")
        return {"status": "FAILED", "reason": "No AI API keys configured"}

    # 1. Initialize Scraper Aggregator
    aggregator = RealEstateAggregator()

    # 2. Execute scraping across Bangalore micro-markets
    try:
        discovered_projects = aggregator.run_full_scan()
    except Exception as e:
        logger.error(f"Scraper encountered critical error: {e}", exc_info=True)
        return {"status": "FAILED", "error": str(e)}

    total_discovered = len(discovered_projects)
    logger.info(f"Total verified unique projects collected: {total_discovered}")

    # 3. Always save local cache backup
    backup_file = ROOT_DIR / "scraped_projects_latest.json"
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump([p.model_dump() for p in discovered_projects], f, indent=2, ensure_ascii=False)
    logger.info(f"Saved local backup snapshot to: {backup_file.name}")

    # 4. Sync with Google Sheets
    gsheet = GoogleSheetManager()
    new_added = 0
    existing_updated = 0
    sync_status = "SUCCESS"
    notes = "Run completed successfully"

    if gsheet.client and gsheet.projects_sheet:
        try:
            new_added, existing_updated = gsheet.sync_projects(discovered_projects)
            summary = ScrapeRunSummary(
                engine_used=SEARCH_STRATEGY,
                total_found=total_discovered,
                new_added=new_added,
                existing_updated=existing_updated,
                status=sync_status,
                notes_or_errors=f"Added {new_added} new launches, updated {existing_updated} rows."
            )
            gsheet.log_run(summary)
            if gsheet.sheet_url:
                logger.info(f"📊 Google Sheet Live URL: {gsheet.sheet_url}")
        except Exception as e:
            logger.error(f"Google Sheet synchronization failed: {e}", exc_info=True)
            sync_status = "PARTIAL_FAILURE"
            notes = f"Sync error: {str(e)}"
    else:
        logger.warning("Google Sheet not connected. Results saved to local JSON backup.")
        sync_status = "LOCAL_ONLY"
        notes = "Google Sheet credentials not provided; saved to local JSON"

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("==================================================================")
    logger.info(f"✅ Pipeline Completed in {elapsed:.1f}s")
    logger.info(f"   • Total Discovered: {total_discovered}")
    logger.info(f"   • Brand New Added: {new_added}")
    logger.info(f"   • Existing Updated: {existing_updated}")
    logger.info("==================================================================")

    return {
        "status": sync_status,
        "total_discovered": total_discovered,
        "new_added": new_added,
        "existing_updated": existing_updated,
        "elapsed_seconds": elapsed,
        "sheet_url": gsheet.sheet_url if gsheet.client else None,
        "notes": notes
    }


if __name__ == "__main__":
    result = run_pipeline()
    if result.get("status") == "FAILED":
        sys.exit(1)
    sys.exit(0)
