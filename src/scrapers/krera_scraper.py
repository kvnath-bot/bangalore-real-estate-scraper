"""
Karnataka RERA (K-RERA) full portal parser.
Scrapes all registered, approved real estate projects directly from
https://rera.karnataka.gov.in/viewAllProjects?language=en
Includes full master registry backup (8,900+ projects) for cloud/overseas runners.
"""

import html
import json
import logging
import os
import re
from pathlib import Path
from typing import List
import requests
from src.models import KRERARawProject

logger = logging.getLogger("scraper.krera")

KRERA_ALL_PROJECTS_URL = "https://rera.karnataka.gov.in/viewAllProjects?language=en"
MASTER_REGISTRY_FILE = Path(__file__).resolve().parent.parent / "data" / "krera_master_registry.json"


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
        Scrapes all approved projects from K-RERA portal.
        Falls back seamlessly to the 8,900+ official master registry if government server times out.
        """
        projects: List[KRERARawProject] = []
        logger.info(f"[K-RERA] Fetching live project database from {KRERA_ALL_PROJECTS_URL}...")

        try:
            resp = self.session.get(KRERA_ALL_PROJECTS_URL, timeout=12, verify=False)
            if resp.status_code == 200:
                content = resp.text
                ack_nos = re.findall(r"applicationNameList\s*\.push\('([^']*)'\);", content)
                rera_nos = re.findall(r"applicationNameList2\s*\.push\('([^']*)'\);", content)
                project_names = re.findall(r"applicationNameList3\s*\.push\('([^']*)'\);", content)
                promoter_names = re.findall(r"applicationNameList4\s*\.push\('([^']*)'\);", content)

                total_entries = min(len(rera_nos), len(project_names), len(promoter_names))
                logger.info(f"[K-RERA] Discovered {total_entries} live registered project entries on portal.")

                for i in range(total_entries):
                    rera_id = rera_nos[i].strip()
                    if not rera_id or not rera_id.startswith("PRM/KA/RERA"):
                        continue

                    proj_name = html.unescape(project_names[i]).strip()
                    promoter_name = html.unescape(promoter_names[i]).strip()
                    ack_no = ack_nos[i].strip() if i < len(ack_nos) else ""
                    district = KRERARawProject.get_district_from_rera(rera_id)

                    projects.append(KRERARawProject(
                        rera_number=rera_id,
                        project_name=proj_name,
                        promoter_name=promoter_name,
                        ack_number=ack_no,
                        district=district,
                        portal_url=KRERA_ALL_PROJECTS_URL,
                        status="Approved by K-RERA",
                        enrichment_status="Pending"
                    ))
                if projects:
                    logger.info(f"[K-RERA] Successfully parsed {len(projects)} live K-RERA project records.")
                    return projects

        except Exception as e:
            logger.warning(f"[K-RERA] Live portal connect timed out or geo-restricted ({e}). Loading master registry...")

        # Fallback to Master Registry Snapshot
        if MASTER_REGISTRY_FILE.exists():
            try:
                with open(MASTER_REGISTRY_FILE, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                    for item in data:
                        projects.append(KRERARawProject(**item))
                logger.info(f"[K-RERA] Loaded {len(projects)} official registered projects from Master K-RERA Registry.")
            except Exception as e:
                logger.error(f"[K-RERA] Failed to load master registry: {e}")

        return projects
