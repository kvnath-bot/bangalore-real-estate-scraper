"""
FastAPI Webhook & Status Service for Render Free Tier Hosting.
Allows triggering the Bangalore Real Estate Scraper via HTTP or external free cron pingers (e.g., cron-job.org).
"""

import json
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from src.config import CRON_SECRET, PORT
from src.main import run_pipeline

app = FastAPI(
    title="Bangalore Real Estate Scraper API",
    description="Automated zero-cost real estate project intelligence pipeline for Bangalore.",
    version="1.0.0"
)

LATEST_BACKUP = Path(__file__).resolve().parent / "scraped_projects_latest.json"


@app.get("/")
def health_check():
    """Health check endpoint showing service status and cached statistics."""
    stats = {"status": "online", "message": "Bangalore Real Estate Scraper is running."}
    if LATEST_BACKUP.exists():
        try:
            with open(LATEST_BACKUP, "r", encoding="utf-8") as f:
                data = json.load(f)
                stats["cached_projects_count"] = len(data)
                stats["latest_sample"] = [p.get("project_name") for p in data[:5]]
        except Exception:
            pass
    return stats


@app.post("/scrape")
def trigger_scrape(
    background_tasks: BackgroundTasks,
    authorization: str = Header(None)
):
    """
    Webhook endpoint to trigger a scraping run.
    Secured by optional CRON_SECRET if configured.
    """
    if CRON_SECRET:
        expected = f"Bearer {CRON_SECRET}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Unauthorized: Invalid cron token")

    # Run pipeline in background so HTTP request doesn't timeout
    background_tasks.add_task(run_pipeline)
    return JSONResponse(
        content={
            "status": "QUEUED",
            "message": "Bangalore Real Estate Scraper triggered successfully in the background."
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)
