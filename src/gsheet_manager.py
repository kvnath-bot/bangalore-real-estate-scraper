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
MAP_PINS_WORKSHEET_NAME = "Map_Pins"
BATCH_CHUNK_SIZE = 1000

# Columns J, K, L of KRERA_Raw_Projects hold Latitude / Longitude / Map Pin Link.
MAP_COL_START = "J"
MAP_COL_END = "L"

# Column E of KRERA_Raw_Projects holds District / Region.
DISTRICT_COL = "E"


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

            # Index each existing row under every key it can be recognised by,
            # so a project already in the sheet is never appended a second time
            # just because this run discovered it without a RERA number.
            row_project = RealEstateProject(
                project_name=proj_name,
                builder_name=builder_name,
                locality="",
                rera_number=rera_no or "Pending",
            )
            for key in row_project.identity_keys():
                existing_keys[key] = idx

        new_rows_to_append: List[List[str]] = []
        updated_count = 0

        for project in scraped_projects:
            matched = next((k for k in project.identity_keys() if k in existing_keys), None)
            if matched is None:
                new_rows_to_append.append(project.to_sheet_row())
                row_index = len(data_rows) + len(new_rows_to_append) + 1
                for key in project.identity_keys():
                    existing_keys[key] = row_index
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
        # A district histogram, because "8943 rows need coordinates" hid the fact
        # that only a fraction were recognised as Bangalore-region and written.
        histogram: Dict[str, int] = {}
        for entry in pending:
            histogram[entry["district"] or "(blank)"] = histogram.get(entry["district"] or "(blank)", 0) + 1
        top = sorted(histogram.items(), key=lambda kv: -kv[1])[:12]
        logger.info(
            f"[GSheet Manager] {len(pending)} KRERA_Raw_Projects rows still need "
            f"coordinates. District values seen: "
            + ", ".join(f"{name}={count}" for name, count in top)
        )
        return pending

    def update_krera_map_columns(self, row_values: Dict[int, List[str]]) -> int:
        """
        Batch writes Latitude / Longitude / Map Pin Link (columns J:L) for the
        given sheet rows.

        row_values maps a 1-based sheet row number to [latitude, longitude, link].
        """
        return self._write_column_blocks(MAP_COL_START, MAP_COL_END, row_values, "coordinates and map pins")

    def backfill_krera_districts(self) -> int:
        """
        Recomputes column E (District / Region) from each row's RERA number and
        writes back the rows that disagree.

        The bundled registry stored "Other Karnataka" for all 4,090 /1251/
        registrations, which are Bengaluru Urban, so the sheet inherited that
        error and those projects were treated as out of scope everywhere.
        Deriving the district in the model fixes new writes; this repairs rows
        already in the sheet.
        """
        if not self.krera_raw_sheet:
            return 0
        try:
            all_rows = self.krera_raw_sheet.get_all_values()
        except Exception as e:
            logger.error(f"Could not read KRERA_Raw_Projects for district backfill: {e}")
            return 0

        corrections: Dict[int, List[str]] = {}
        for idx, row in enumerate(all_rows[1:], start=2):
            if not row or not row[0].strip():
                continue
            rera = row[0].strip()
            current = row[4].strip() if len(row) > 4 else ""
            derived = KRERARawProject.get_district_from_rera(rera)
            if derived != "Other Karnataka" and current != derived:
                corrections[idx] = [derived]

        if not corrections:
            logger.info("[GSheet Manager] District column is already correct for every row.")
            return 0

        logger.info(
            f"[GSheet Manager] Correcting District / Region on {len(corrections)} rows "
            f"whose value disagrees with their RERA number."
        )
        return self._write_column_blocks(
            DISTRICT_COL, DISTRICT_COL, corrections, "district corrections"
        )

    def _write_column_blocks(
        self,
        col_start: str,
        col_end: str,
        row_values: Dict[int, List[str]],
        what: str,
    ) -> int:
        """
        Writes a span of columns for scattered rows. Contiguous rows are merged
        into single ranges so a few thousand updates cost only a handful of API
        calls.
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
                    "range": f"{col_start}{block_start}:{col_end}{block_start + len(block) - 1}",
                    "values": block,
                })
                block_start = row_num
                block = []
            block.append(values)
            previous_row = row_num

        if block:
            requests_payload.append({
                "range": f"{col_start}{block_start}:{col_end}{block_start + len(block) - 1}",
                "values": block,
            })

        written = 0
        logger.info(
            f"[GSheet Manager] Writing {what} for {len(ordered)} rows "
            f"in {len(requests_payload)} contiguous range(s)..."
        )
        for i in range(0, len(requests_payload), 100):
            chunk = requests_payload[i:i + 100]
            try:
                self.krera_raw_sheet.batch_update(chunk, value_input_option="USER_ENTERED")
                written += sum(len(r["values"]) for r in chunk)
                time.sleep(1.5)
            except Exception as e:
                logger.error(f"Failed writing {what} batch starting at index {i}: {e}")
                time.sleep(5.0)

        logger.info(f"[GSheet Manager] Wrote {what} for {written} rows.")
        return written

    def export_map_pins(self) -> int:
        """
        Rebuilds the 'Map_Pins' worksheet: one row per project that has REAL
        coordinates, ready to import straight into Google My Maps.

        This is the sharing surface for agents. KRERA_Raw_Projects holds all
        8,943 registrations, most of them unresolved or out of scope, which is
        not something anyone can usefully import. Map_Pins holds only the
        located ones, so "Import -> Latitude/Longitude" just works.

        Rows without coordinates are deliberately EXCLUDED rather than exported
        with a name-search link. A pin that is not a real location has no place
        on a map.
        """
        if not self.krera_raw_sheet or not self.spreadsheet:
            return 0
        try:
            all_rows = self.krera_raw_sheet.get_all_values()
        except Exception as e:
            logger.error(f"Could not read KRERA_Raw_Projects for map pin export: {e}")
            return 0

        headers = [
            "Project Name", "Promoter / Developer", "District / Region",
            "Latitude", "Longitude", "Karnataka RERA No.", "Map Pin Link",
        ]
        pins: List[List[str]] = []
        for row in all_rows[1:]:
            if not row or not row[0].strip():
                continue
            latitude = row[9].strip() if len(row) > 9 else ""
            longitude = row[10].strip() if len(row) > 10 else ""
            if not latitude or not longitude:
                continue
            pins.append([
                row[1].strip() if len(row) > 1 else "",
                row[2].strip() if len(row) > 2 else "",
                row[4].strip() if len(row) > 4 else "",
                latitude,
                longitude,
                row[0].strip(),
                row[11].strip() if len(row) > 11 else "",
            ])

        if not pins:
            logger.info("[GSheet Manager] No located projects yet; Map_Pins not written.")
            return 0

        try:
            sheet = self.spreadsheet.worksheet(MAP_PINS_WORKSHEET_NAME)
            sheet.clear()
        except gspread.WorksheetNotFound:
            logger.info(f"Creating worksheet '{MAP_PINS_WORKSHEET_NAME}'...")
            sheet = self.spreadsheet.add_worksheet(
                title=MAP_PINS_WORKSHEET_NAME, rows=max(1000, len(pins) + 50), cols=10
            )

        logger.info(f"[GSheet Manager] Writing {len(pins)} located projects to '{MAP_PINS_WORKSHEET_NAME}'...")
        sheet.update(range_name="A1", values=[headers] + pins, value_input_option="USER_ENTERED")
        self._format_header_row(sheet)
        logger.info(f"[GSheet Manager] Map_Pins refreshed with {len(pins)} pins.")
        return len(pins)

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
