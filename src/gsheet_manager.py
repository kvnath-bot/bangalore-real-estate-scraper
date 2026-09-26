"""
Google Sheets Manager for Bangalore Real Estate Tracker.
Handles authentication, sheet creation, KRERA_Raw_Projects sync, deduplication,
batch appending, status updates, and daily execution logging with Google Sheets write-rate limit protection.
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional, Set, Tuple
import gspread
from google.oauth2.service_account import Credentials
from src.config import (
    GCP_SERVICE_ACCOUNT_FILE,
    GCP_SERVICE_ACCOUNT_KEY,
    GOOGLE_SHEET_NAME,
    SHARE_NOTIFY,
    SHARE_ROLE,
    SHARE_WITH_EMAILS,
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

# Columns J, K, L of KRERA_Raw_Projects hold Latitude / Longitude / Map Pin Link.
MAP_COL_START = "J"
MAP_COL_END = "L"


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
            expected_raw_headers = KRERARawProject.sheet_headers()
            if not raw_headers:
                self.krera_raw_sheet.append_row(expected_raw_headers)
                self._format_header_row(self.krera_raw_sheet)
            elif raw_headers != expected_raw_headers:
                # Sheets created before the Latitude / Longitude / Map Pin Link
                # columns existed keep their data; only the header row is widened.
                logger.info("Upgrading KRERA_Raw_Projects header row to include map columns...")
                self.krera_raw_sheet.update(
                    range_name=f"A1:{chr(ord('A') + len(expected_raw_headers) - 1)}1",
                    values=[expected_raw_headers],
                    value_input_option="USER_ENTERED",
                )

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
                    time.sleep(1.5)
                except Exception as e:
                    logger.error(f"Error appending chunk {chunk_num}: {e}")
                    time.sleep(5.0)

        return new_count

    def update_krera_enrichment_statuses(self, rera_status_map: Dict[str, str]):
        """
        Batch updates Column I (Enrichment Status) for all rows in KRERA_Raw_Projects
        in a single fast API call without hitting rate limits.
        """
        if not self.krera_raw_sheet:
            return

        try:
            logger.info("[GSheet Manager] Updating Enrichment Status column in KRERA_Raw_Projects...")
            all_reras = self.krera_raw_sheet.col_values(1)
            if len(all_reras) <= 1:
                return

            status_updates = []
            for rera_id in all_reras[1:]:
                clean_rera = rera_id.strip()
                status = rera_status_map.get(clean_rera, "Pending")
                status_updates.append([status])

            range_to_update = f"I2:I{len(status_updates) + 1}"
            logger.info(f"Batch updating {len(status_updates)} enrichment status cells ({range_to_update})...")
            self.krera_raw_sheet.update(range_name=range_to_update, values=status_updates, value_input_option="USER_ENTERED")
            logger.info("Successfully updated all enrichment statuses in KRERA_Raw_Projects!")
        except Exception as e:
            logger.error(f"Failed to batch update KRERA_Raw_Projects enrichment status: {e}")

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

    def get_krera_rows_needing_coordinates(self) -> List[Dict[str, str]]:
        """
        Returns the KRERA_Raw_Projects rows that still have no latitude/longitude,
        each tagged with its 1-based sheet row number so results can be written
        straight back into columns J:L.
        """
        if not self.krera_raw_sheet:
            return []
        try:
            all_rows = self.krera_raw_sheet.get_all_values()
        except Exception as e:
            logger.error(f"Could not read KRERA_Raw_Projects for geocoding: {e}")
            return []

        pending: List[Dict[str, str]] = []
        for idx, row in enumerate(all_rows[1:], start=2):
            if not row or not row[0].strip():
                continue
            latitude = row[9].strip() if len(row) > 9 else ""
            longitude = row[10].strip() if len(row) > 10 else ""
            if latitude and longitude:
                continue
            pending.append({
                "row": idx,
                "rera_number": row[0].strip(),
                "project_name": row[1].strip() if len(row) > 1 else "",
                "district": row[4].strip() if len(row) > 4 else "",
            })
        logger.info(f"[GSheet Manager] {len(pending)} KRERA_Raw_Projects rows still need coordinates.")
        return pending

    def update_krera_map_columns(self, row_values: Dict[int, List[str]]) -> int:
        """
        Batch writes Latitude / Longitude / Map Pin Link (columns J:L) for the
        given sheet rows. Contiguous rows are merged into single ranges so a few
        thousand updates cost only a handful of API calls.

        row_values maps a 1-based sheet row number to [latitude, longitude, link].
        """
        if not self.krera_raw_sheet or not row_values:
            return 0

        ordered = sorted(row_values.items())
        requests_payload = []
        block_start = ordered[0][0]
        block: List[List[str]] = []
        previous_row = None

        for row_num, values in ordered:
            if previous_row is not None and row_num != previous_row + 1:
                requests_payload.append({
                    "range": f"{MAP_COL_START}{block_start}:{MAP_COL_END}{block_start + len(block) - 1}",
                    "values": block,
                })
                block_start = row_num
                block = []
            block.append(values)
            previous_row = row_num

        if block:
            requests_payload.append({
                "range": f"{MAP_COL_START}{block_start}:{MAP_COL_END}{block_start + len(block) - 1}",
                "values": block,
            })

        written = 0
        logger.info(
            f"[GSheet Manager] Writing map data for {len(ordered)} rows "
            f"in {len(requests_payload)} contiguous range(s)..."
        )
        for i in range(0, len(requests_payload), 100):
            chunk = requests_payload[i:i + 100]
            try:
                self.krera_raw_sheet.batch_update(chunk, value_input_option="USER_ENTERED")
                written += sum(len(r["values"]) for r in chunk)
                time.sleep(1.5)
            except Exception as e:
                logger.error(f"Failed writing map-column batch starting at index {i}: {e}")
                time.sleep(5.0)

        logger.info(f"[GSheet Manager] Wrote coordinates and map pins for {written} rows.")
        return written

    def share_with_emails(
        self,
        emails: Optional[List[str]] = None,
        role: Optional[str] = None,
        notify: Optional[bool] = None,
    ) -> List[str]:
        """
        Grants the given addresses access to the spreadsheet via the Drive API.
        Defaults come from SHARE_WITH_EMAILS / SHARE_ROLE / SHARE_NOTIFY.
        Returns the addresses that were shared successfully.
        """
        if not self.spreadsheet:
            logger.warning("No spreadsheet open; cannot share.")
            return []

        targets = [e.strip() for e in (emails if emails is not None else SHARE_WITH_EMAILS) if e and e.strip()]
        if not targets:
            logger.info("[GSheet Manager] No SHARE_WITH_EMAILS configured; skipping sharing step.")
            return []

        share_role = (role or SHARE_ROLE or "writer").lower()
        if share_role not in ("reader", "commenter", "writer", "owner"):
            logger.warning(f"Unsupported share role '{share_role}'; falling back to 'writer'.")
            share_role = "writer"
        send_notification = SHARE_NOTIFY if notify is None else notify

        shared: List[str] = []
        for email in targets:
            try:
                self.spreadsheet.share(
                    email,
                    perm_type="user",
                    role=share_role,
                    notify=send_notification,
                )
                shared.append(email)
                logger.info(f"[GSheet Manager] Shared sheet with {email} as '{share_role}'.")
            except Exception as e:
                logger.error(f"Failed to share sheet with {email}: {e}")
        return shared

    @property
    def sheet_url(self) -> str:
        """Returns the public/shared URL of the Google Sheet."""
        if self.spreadsheet:
            return self.spreadsheet.url
        return ""
