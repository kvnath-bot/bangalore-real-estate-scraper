"""
Karnataka RERA (K-RERA) full portal parser.
Scrapes all registered, approved real estate projects directly from
https://rera.karnataka.gov.in/viewAllProjects?language=en
"""

import html
import logging
import re
from typing import List, Optional
import requests
from src.models import KRERARawProject

logger = logging.getLogger("scraper.krera")

KRERA_ALL_PROJECTS_URL = "https://rera.karnataka.gov.in/viewAllProjects?language=en"


class KRERAParser:
    """Fetches and parses the official Karnataka RERA project database."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def fetch_all_raw_projects(self) -> List[KRERARawProject]:
        """
        Scrapes all approved projects from K-RERA viewAllProjects portal.
        Extracts Application No, RERA Registration ID, Project Name, and Promoter Name.
        """
        projects: List[KRERARawProject] = []
        logger.info(f"[K-RERA] Fetching project database from {KRERA_ALL_PROJECTS_URL}...")

        try:
            resp = self.session.get(KRERA_ALL_PROJECTS_URL, timeout=45, verify=False)
            if resp.status_code != 200:
                logger.error(f"[K-RERA] Portal returned status {resp.status_code}")
                return projects

            content = resp.text

            # Extract arrays from JavaScript data blocks
            ack_nos = re.findall(r"applicationNameList\s*\.push\('([^']*)'\);", content)
            rera_nos = re.findall(r"applicationNameList2\s*\.push\('([^']*)'\);", content)
            project_names = re.findall(r"applicationNameList3\s*\.push\('([^']*)'\);", content)
            promoter_names = re.findall(r"applicationNameList4\s*\.push\('([^']*)'\);", content)

            total_entries = min(len(rera_nos), len(project_names), len(promoter_names))
            logger.info(f"[K-RERA] Discovered {total_entries} total registered project entries on portal.")

            for i in range(total_entries):
                rera_id = rera_nos[i].strip()
                if not rera_id or not rera_id.startswith("PRM/KA/RERA"):
                    continue

                proj_name = html.unescape(project_names[i]).strip()
                promoter_name = html.unescape(promoter_names[i]).strip()
                ack_no = ack_nos[i].strip() if i < len(ack_nos) else ""
                district = KRERARawProject.get_district_from_rera(rera_id)

                raw_proj = KRERARawProject(
                    rera_number=rera_id,
                    project_name=proj_name,
                    promoter_name=promoter_name,
                    ack_number=ack_no,
                    district=district,
                    portal_url=KRERA_ALL_PROJECTS_URL,
                    status="Approved by K-RERA",
                    enrichment_status="Pending"
                )
                projects.append(raw_proj)

            logger.info(f"[K-RERA] Successfully parsed {len(projects)} valid K-RERA project records.")

        except Exception as e:
            logger.error(f"[K-RERA] Failed to fetch or parse K-RERA portal: {e}", exc_info=True)

        return projects
