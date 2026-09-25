"""
Google Sheets Manager for Bangalore Real Estate Tracker.
Handles authentication, sheet creation, KRERA_Raw_Projects sync, deduplication,
batch appending, and daily execution logging with Google Sheets write-rate limit protection.
"""

import json
import logging
import os
import time
from typing import Dict, List, Set, Tuple
import gspread
from google.oauth2.service_account import Credentials
from src.config import (
    GCP_SERVICE_ACCOUNT_FILE,
    GCP_SERVICE_ACCOUNT_KEY,
    GOOGLE_SHEET_NAME,
    SPREADSHEET_ID,
)
from src.models import KRERARawProject, RealEstateProject, ScrapeRunSummary

logger = logging.getLogger("gsheet.manager")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

PROJECTS_WORKSHEET_NAME = "Bangalore_Projects"
KRERA_RAW_WORKSHEET_NAME = "KRERA_Raw_Projects"
LOGS_WORKSHEET_NAME = "Scrape_Run_Logs"
BATCH_CHUNK_SIZE = 1000


class GoogleSheetManager:
    def __init__(self):
        self.client = self._authenticate()
        self.spreadsheet = None
        self.projects_sheet = None
        self.krera_raw_sheet = None
        self.logs_sheet = None

        if self.client:
            self._initialize_sheets()

    def _authenticate(self) -> gspread.Client:
        """Authenticate using service account key from env variable or local json file."""
        try:
            if GCP_SERVICE_ACCOUNT_KEY:
                logger.info("Authenticating via GCP_SERVICE_ACCOUNT_KEY environment variable...")
                creds_dict = json.loads(GCP_SERVICE_ACCOUNT_KEY)
                creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
                return gspread.authorize(creds)

            if os.path.exists(GCP_SERVICE_ACCOUNT_FILE):
                logger.info(f"Authenticating via service account file: {GCP_SERVICE_ACCOUNT_FILE}...")
                creds = Credentials.from_service_account_file(GCP_SERVICE_ACCOUNT_FILE, scopes=SCOPES)
                return gspread.authorize(creds)

            logger.warning("No Google Service Account credentials found. Running in dry-run mode.")
            return None
        except Exception as e:
            logger.error(f"Failed to authenticate with Google Sheets API: {e}")
            return None

    def _initialize_sheets(self):
        """Open or create the Google Spreadsheet and required worksheets."""
        if not self.client:
            return

        try:
            if SPREADSHEET_ID:
                self.spreadsheet = self.client.open_by_key(SPREADSHEET_ID)
                logger.info(f"Opened spreadsheet by ID: {self.spreadsheet.title}")
            else:
                try:
                    self.spreadsheet = self.client.open(GOOGLE_SHEET_NAME)
                    logger.info(f"Opened existing spreadsheet: {GOOGLE_SHEET_NAME}")
                except gspread.SpreadsheetNotFound:
                    logger.info(f"Spreadsheet '{GOOGLE_SHEET_NAME}' not found. Creating a new one...")
                    self.spreadsheet = self.client.create(GOOGLE_SHEET_NAME)
                    logger.info(f"Created new spreadsheet '{GOOGLE_SHEET_NAME}'! URL: {self.spreadsheet.url}")

            # 1. Main 'Bangalore_Projects' Sheet
            try:
                self.projects_sheet = self.spreadsheet.worksheet(PROJECTS_WORKSHEET_NAME)
            except gspread.WorksheetNotFound:
                logger.info(f"Creating worksheet '{PROJECTS_WORKSHEET_NAME}'...")
                self.projects_sheet = self.spreadsheet.add_worksheet(
                    title=PROJECTS_WORKSHEET_NAME, rows=10000, cols=20
                )
            existing_headers = self.projects_sheet.row_values(1)
            if not existing_headers:
                headers = RealEstateProject.sheet_headers()
                self.projects_sheet.append_row(headers)
                self._format_header_row(self.projects_sheet)

            # 2. 'KRERA_Raw_Projects' Sheet
            try:
                self.krera_raw_sheet = self.spreadsheet.worksheet(KRERA_RAW_WORKSHEET_NAME)
            except gspread.WorksheetNotFound:
                logger.info(f"Creating worksheet '{KRERA_RAW_WORKSHEET_NAME}'...")
                self.krera_raw_sheet = self.spreadsheet.add_worksheet(
                    title=KRERA_RAW_WORKSHEET_NAME, rows=15000, cols=15
                )
            raw_headers = self.krera_raw_sheet.row_values(1)
            if not raw_headers:
                headers = KRERARawProject.sheet_headers()
                self.krera_raw_sheet.append_row(headers)
                self._format_header_row(self.krera_raw_sheet)

            # 3. 'Scrape_Run_Logs' Sheet
            try:
                self.logs_sheet = self.spreadsheet.worksheet(LOGS_WORKSHEET_NAME)
            except gspread.WorksheetNotFound:
                logger.info(f"Creating worksheet '{LOGS_WORKSHEET_NAME}'...")
                self.logs_sheet = self.spreadsheet.add_worksheet(
                    title=LOGS_WORKSHEET_NAME, rows=500, cols=10
                )
            log_headers = self.logs_sheet.row_values(1)
            if not log_headers:
                headers = ScrapeRunSummary.log_headers()
                self.logs_sheet.append_row(headers)
                self._format_header_row(self.logs_sheet)

        except Exception as e:
            logger.error(f"Error initializing Google Sheets: {e}")

    def _format_header_row(self, worksheet: gspread.Worksheet):
        """Format header row: freeze top row."""
        try:
            worksheet.freeze(rows=1)
        except Exception:
            pass

    def sync_krera_raw_projects(self, raw_projects: List[KRERARawProject]) -> int:
        """
        Synchronizes all scraped K-RERA raw projects into 'KRERA_Raw_Projects' sheet.
        Deduplicates by RERA registration number and appends in rate-limited chunks.
        """
        if not self.krera_raw_sheet:
            logger.warning("KRERA_Raw_Projects sheet not ready.")
            return 0

        logger.info("[GSheet Manager] Reading existing RERA numbers from KRERA_Raw_Projects...")
        try:
            existing_rera_col = self.krera_raw_sheet.col_values(1)
            existing_reras: Set[str] = set([r.strip() for r in existing_rera_col if r])
        except Exception as e:
            logger.warning(f"Could not read existing RERA column: {e}")
            existing_reras = set()

        new_rows: List[List[str]] = []
        for p in raw_projects:
            if p.rera_number.strip() not in existing_reras:
                new_rows.append(p.to_sheet_row())
                existing_reras.add(p.rera_number.strip())

        new_count = len(new_rows)
        logger.info(f"[GSheet Manager] Found {new_count} new K-RERA registrations to append to KRERA_Raw_Projects.")

        if new_rows:
            for i in range(0, len(new_rows), BATCH_CHUNK_SIZE):
                chunk = new_rows[i:i + BATCH_CHUNK_SIZE]
                chunk_num = i // BATCH_CHUNK_SIZE + 1
                total_chunks = (len(new_rows) + BATCH_CHUNK_SIZE - 1) // BATCH_CHUNK_SIZE
                logger.info(f"Writing chunk {chunk_num}/{total_chunks} ({len(chunk)} rows) to KRERA_Raw_Projects...")
                try:
                    self.krera_raw_sheet.append_rows(chunk, value_input_option="USER_ENTERED")
                    time.sleep(1.5)  # Rate limit safety delay
                except Exception as e:
                    logger.error(f"Error appending chunk {chunk_num}: {e}")
                    time.sleep(5.0)

        return new_count

    def sync_projects(self, scraped_projects: List[RealEstateProject]) -> Tuple[int, int]:
        """
        Synchronizes scraped & enriched projects with Bangalore_Projects sheet.
        Deduplicates against existing rows and batch appends new records.
        """
        if not self.projects_sheet:
            logger.warning("No active Google Sheet. Skipping remote sync.")
            return (0, 0)

        logger.info("Reading existing records from Bangalore_Projects for deduplication...")
        all_rows = self.projects_sheet.get_all_values()
        data_rows = all_rows[1:] if len(all_rows) > 1 else []

        existing_keys: Dict[str, int] = {}
        for idx, row in enumerate(data_rows, start=2):
            if not row or not row[0]:
                continue
            proj_name = row[0]
            builder_name = row[1] if len(row) > 1 else ""
            rera_no = row[8] if len(row) > 8 else ""

            clean_rera = "".join(filter(str.isalnum, rera_no.lower()))
            if clean_rera and "pending" not in clean_rera and "not" not in clean_rera and "verified" not in clean_rera and len(clean_rera) > 6:
                existing_keys[f"rera:{clean_rera}"] = idx
            else:
                clean_p = "".join(filter(str.isalnum, proj_name.lower()))
                clean_b = "".join(filter(str.isalnum, builder_name.lower()))
                existing_keys[f"name:{clean_p}|{clean_b}"] = idx

        new_rows_to_append: List[List[str]] = []
        updated_count = 0

        for project in scraped_projects:
            key = project.deduplication_key()
            if key not in existing_keys:
                new_rows_to_append.append(project.to_sheet_row())
                existing_keys[key] = len(data_rows) + len(new_rows_to_append) + 1
            else:
                updated_count += 1

        new_added_count = len(new_rows_to_append)
        if new_rows_to_append:
            logger.info(f"Appending {new_added_count} projects to Bangalore_Projects in batches...")
            for i in range(0, len(new_rows_to_append), BATCH_CHUNK_SIZE):
                chunk = new_rows_to_append[i:i + BATCH_CHUNK_SIZE]
                self.projects_sheet.append_rows(chunk, value_input_option="USER_ENTERED")
                time.sleep(1.0)

        logger.info(f"Google Sheet Sync Complete! Added: {new_added_count}, Existing Matched: {updated_count}")
        return (new_added_count, updated_count)

    def log_run(self, summary: ScrapeRunSummary):
        """Record execution metrics into 'Scrape_Run_Logs' worksheet."""
        if not self.logs_sheet:
            return
        try:
            self.logs_sheet.append_row(summary.to_log_row(), value_input_option="USER_ENTERED")
        except Exception as e:
            logger.error(f"Failed to append to run log sheet: {e}")

    @property
    def sheet_url(self) -> str:
        """Returns the public/shared URL of the Google Sheet."""
        if self.spreadsheet:
            return self.spreadsheet.url
        return ""
