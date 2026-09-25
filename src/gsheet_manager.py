"""
Google Sheets Manager for Bangalore Real Estate Tracker.
Handles authentication, sheet creation, deduplication, batch appending, and daily run logging.
"""

import json
import logging
import os
from typing import Dict, List, Tuple
import gspread
from google.oauth2.service_account import Credentials
from src.config import (
    GCP_SERVICE_ACCOUNT_FILE,
    GCP_SERVICE_ACCOUNT_KEY,
    GOOGLE_SHEET_NAME,
    SPREADSHEET_ID,
)
from src.models import RealEstateProject, ScrapeRunSummary

logger = logging.getLogger("gsheet.manager")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

PROJECTS_WORKSHEET_NAME = "Bangalore_Projects"
LOGS_WORKSHEET_NAME = "Scrape_Run_Logs"


class GoogleSheetManager:
    def __init__(self):
        self.client = self._authenticate()
        self.spreadsheet = None
        self.projects_sheet = None
        self.logs_sheet = None

        if self.client:
            self._initialize_sheets()

    def _authenticate(self) -> gspread.Client:
        """Authenticate using service account key from env variable or local json file."""
        try:
            # 1. Check raw JSON key in environment variable (GitHub Actions / Cloud)
            if GCP_SERVICE_ACCOUNT_KEY:
                logger.info("Authenticating via GCP_SERVICE_ACCOUNT_KEY environment variable...")
                creds_dict = json.loads(GCP_SERVICE_ACCOUNT_KEY)
                creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
                return gspread.authorize(creds)

            # 2. Check local file on disk
            if os.path.exists(GCP_SERVICE_ACCOUNT_FILE):
                logger.info(f"Authenticating via service account file: {GCP_SERVICE_ACCOUNT_FILE}...")
                creds = Credentials.from_service_account_file(GCP_SERVICE_ACCOUNT_FILE, scopes=SCOPES)
                return gspread.authorize(creds)

            logger.warning(
                "No Google Service Account credentials found. "
                "Set GCP_SERVICE_ACCOUNT_KEY or provide service_account.json. "
                "Running in dry-run mode."
            )
            return None
        except Exception as e:
            logger.error(f"Failed to authenticate with Google Sheets API: {e}")
            return None

    def _initialize_sheets(self):
        """Open or create the Google Spreadsheet and required worksheets."""
        if not self.client:
            return

        try:
            # Open by ID if provided, else by Name
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

            # Ensure 'Bangalore_Projects' worksheet exists
            try:
                self.projects_sheet = self.spreadsheet.worksheet(PROJECTS_WORKSHEET_NAME)
            except gspread.WorksheetNotFound:
                logger.info(f"Creating worksheet '{PROJECTS_WORKSHEET_NAME}'...")
                self.projects_sheet = self.spreadsheet.add_worksheet(
                    title=PROJECTS_WORKSHEET_NAME, rows=1000, cols=20
                )
                # Remove default 'Sheet1' if present
                try:
                    default_sheet = self.spreadsheet.worksheet("Sheet1")
                    if default_sheet.id != self.projects_sheet.id:
                        self.spreadsheet.del_worksheet(default_sheet)
                except Exception:
                    pass

            # Setup Projects headers if sheet is empty
            existing_headers = self.projects_sheet.row_values(1)
            if not existing_headers:
                headers = RealEstateProject.sheet_headers()
                self.projects_sheet.append_row(headers)
                self._format_header_row(self.projects_sheet, len(headers))

            # Ensure 'Scrape_Run_Logs' worksheet exists
            try:
                self.logs_sheet = self.spreadsheet.worksheet(LOGS_WORKSHEET_NAME)
            except gspread.WorksheetNotFound:
                logger.info(f"Creating worksheet '{LOGS_WORKSHEET_NAME}'...")
                self.logs_sheet = self.spreadsheet.add_worksheet(
                    title=LOGS_WORKSHEET_NAME, rows=500, cols=10
                )
                log_headers = ScrapeRunSummary.log_headers()
                self.logs_sheet.append_row(log_headers)
                self._format_header_row(self.logs_sheet, len(log_headers))

        except Exception as e:
            logger.error(f"Error initializing Google Sheets: {e}")

    def _format_header_row(self, worksheet: gspread.Worksheet, col_count: int):
        """Format header row: bold, background color, frozen top row."""
        try:
            worksheet.freeze(rows=1)
            # Format top row with blue-grey header styling
            worksheet.format("A1:P1", {
                "backgroundColor": {"red": 0.15, "green": 0.25, "blue": 0.35},
                "horizontalAlignment": "CENTER",
                "textFormat": {
                    "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                    "fontSize": 10,
                    "bold": True
                }
            })
        except Exception as e:
            logger.debug(f"Could not apply sheet formatting: {e}")

    def sync_projects(self, scraped_projects: List[RealEstateProject]) -> Tuple[int, int]:
        """
        Synchronizes scraped projects with Google Sheets.
        Deduplicates against existing rows:
        - Appends brand new projects
        - Updates price / status / possession on existing rows if changed
        Returns: (new_added_count, existing_updated_count)
        """
        if not self.projects_sheet:
            logger.warning("No active Google Sheet. Skipping remote sync.")
            return (0, 0)

        logger.info("Reading existing records from Google Sheet for deduplication...")
        all_rows = self.projects_sheet.get_all_values()
        header_row = all_rows[0] if all_rows else []
        data_rows = all_rows[1:] if len(all_rows) > 1 else []

        # Map existing records by deduplication key to their 1-indexed row number
        # Columns: [0: Name, 1: Builder, ..., 8: RERA]
        existing_keys: Dict[str, int] = {}
        for idx, row in enumerate(data_rows, start=2):
            if not row or not row[0]:
                continue
            proj_name = row[0]
            builder_name = row[1] if len(row) > 1 else ""
            rera_no = row[8] if len(row) > 8 else ""

            # Reconstruct key
            clean_rera = "".join(filter(str.isalnum, rera_no.lower()))
            if clean_rera and "pending" not in clean_rera and "not" not in clean_rera and len(clean_rera) > 6:
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
                # New project!
                new_rows_to_append.append(project.to_sheet_row())
                # Add to existing_keys in case scraped list contains internal duplicates
                existing_keys[key] = len(data_rows) + len(new_rows_to_append) + 1
            else:
                # Existing project: update timestamp & latest pricing/status
                row_idx = existing_keys[key]
                try:
                    # Update columns G (Price), H (Status), J (Possession), P (Last Updated)
                    self.projects_sheet.update_cell(row_idx, 7, project.price_range)
                    self.projects_sheet.update_cell(row_idx, 8, project.status)
                    self.projects_sheet.update_cell(row_idx, 10, project.possession_date)
                    self.projects_sheet.update_cell(row_idx, 16, project.last_updated)
                    updated_count += 1
                except Exception as e:
                    logger.debug(f"Row update exception for {project.project_name}: {e}")

        # Batch append all new rows to avoid hitting Google API quota
        new_added_count = len(new_rows_to_append)
        if new_rows_to_append:
            logger.info(f"Appending {new_added_count} brand-new real estate projects to Google Sheet...")
            self.projects_sheet.append_rows(new_rows_to_append, value_input_option="USER_ENTERED")

        logger.info(f"Google Sheet Sync Complete! Added: {new_added_count}, Updated: {updated_count}")
        return (new_added_count, updated_count)

    def log_run(self, summary: ScrapeRunSummary):
        """Record execution metrics into 'Scrape_Run_Logs' worksheet."""
        if not self.logs_sheet:
            return
        try:
            self.logs_sheet.append_row(summary.to_log_row(), value_input_option="USER_ENTERED")
            logger.info(f"Logged run summary: {summary.status} ({summary.new_added} new, {summary.existing_updated} updated)")
        except Exception as e:
            logger.error(f"Failed to append to run log sheet: {e}")

    @property
    def sheet_url(self) -> str:
        """Returns the public/shared URL of the Google Sheet."""
        if self.spreadsheet:
            return self.spreadsheet.url
        return ""
