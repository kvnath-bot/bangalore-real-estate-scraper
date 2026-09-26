"""
Tests for scripts/dedupe_sheet.py - the one-off duplicate cleanup.

No network and no Google credentials: the worksheet is a mock, so these verify
the clustering, merging and row-deletion arithmetic, which is the part that can
destroy data if it is wrong.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.dedupe_sheet import (  # noqa: E402
    cluster_project_rows,
    cluster_raw_rows,
    delete_rows,
    merge_project_cluster,
)
from src.models import RealEstateProject  # noqa: E402

REAL_RERA = "PRM/KA/RERA/1251/310/PR/230123/005655"
OTHER_RERA = "PRM/KA/RERA/1251/308/PR/141223/006479"


def row(name, builder, rera, **extra):
    return RealEstateProject(
        project_name=name,
        builder_name=builder,
        locality=extra.pop("locality", "Somewhere"),
        rera_number=rera,
        **extra,
    ).to_sheet_row()


class TestProjectClustering(unittest.TestCase):

    def test_row_with_rera_clusters_with_row_without(self):
        """The exact duplicate the old keying produced."""
        rows = [
            (2, row("Godrej Athena", "Godrej Properties", REAL_RERA)),
            (3, row("Godrej Athena", "Godrej Properties", "Pending")),
        ]
        self.assertEqual(cluster_project_rows(rows), [[2, 3]])

    def test_distinct_projects_are_not_clustered(self):
        rows = [
            (2, row("Godrej Athena", "Godrej Properties", REAL_RERA)),
            (3, row("Brigade Sanctuary", "Brigade Group", OTHER_RERA)),
            (4, row("Sobha Neopolis", "Sobha Limited", "Pending")),
        ]
        self.assertEqual(cluster_project_rows(rows), [])

    def test_same_name_different_builder_stays_separate(self):
        rows = [
            (2, row("Riverside", "Builder A", "Pending")),
            (3, row("Riverside", "Builder B", "Pending")),
        ]
        self.assertEqual(cluster_project_rows(rows), [])

    def test_transitive_linking_through_a_shared_row(self):
        """
        Row 3 carries both the name of row 2 and the RERA of row 4, so all three
        are the same project and must end up in one cluster.
        """
        rows = [
            (2, row("Godrej Athena", "Godrej Properties", "Pending")),
            (3, row("Godrej Athena", "Godrej Properties", REAL_RERA)),
            (4, row("Godrej Athena Phase 2", "Godrej Properties", REAL_RERA)),
        ]
        self.assertEqual(cluster_project_rows(rows), [[2, 3, 4]])

    def test_lowest_row_number_leads_the_cluster(self):
        rows = [
            (9, row("Godrej Athena", "Godrej Properties", "Pending")),
            (4, row("Godrej Athena", "Godrej Properties", REAL_RERA)),
            (7, row("Godrej Athena", "Godrej Properties", "Pending")),
        ]
        cluster = cluster_project_rows(rows)[0]
        self.assertEqual(cluster, [4, 7, 9])

    def test_short_rows_are_tolerated(self):
        rows = [(2, ["Godrej Athena", "Godrej Properties"]),
                (3, ["Godrej Athena", "Godrej Properties", "Whitefield"])]
        self.assertEqual(cluster_project_rows(rows), [[2, 3]])


class TestRawClustering(unittest.TestCase):

    def test_identical_rera_numbers_cluster(self):
        rows = [(2, [REAL_RERA, "A"]), (3, [REAL_RERA, "A"]), (4, [OTHER_RERA, "B"])]
        self.assertEqual(cluster_raw_rows(rows), [[2, 3]])

    def test_match_is_case_insensitive(self):
        rows = [(2, [REAL_RERA.lower(), "A"]), (3, [REAL_RERA.upper(), "A"])]
        self.assertEqual(cluster_raw_rows(rows), [[2, 3]])

    def test_blank_rera_rows_are_ignored(self):
        self.assertEqual(cluster_raw_rows([(2, ["", "A"]), (3, ["", "B"])]), [])


class TestClusterMerging(unittest.TestCase):

    def test_survivor_gains_the_real_rera_number(self):
        row_map = {
            2: row("Godrej Athena", "Godrej Properties", "Pending"),
            3: row("Godrej Athena", "Godrej Properties", REAL_RERA),
        }
        merged, changes = merge_project_cluster([2, 3], row_map)
        self.assertEqual(merged.rera_number, REAL_RERA)
        self.assertTrue(any("rera_number" in c for c in changes))

    def test_survivor_gains_price_and_possession(self):
        row_map = {
            2: row("Godrej Athena", "Godrej Properties", "Pending"),
            3: row("Godrej Athena", "Godrej Properties", REAL_RERA,
                   price_range="2.5 Cr onwards", possession_date="Dec 2028"),
        }
        merged, _ = merge_project_cluster([2, 3], row_map)
        self.assertEqual(merged.price_range, "2.5 Cr onwards")
        self.assertEqual(merged.possession_date, "Dec 2028")

    def test_richer_survivor_is_not_downgraded(self):
        row_map = {
            2: row("Godrej Athena", "Godrej Properties", REAL_RERA,
                   price_range="2.5 Cr onwards"),
            3: row("Godrej Athena", "Godrej Properties", "Pending"),
        }
        merged, _ = merge_project_cluster([2, 3], row_map)
        self.assertEqual(merged.rera_number, REAL_RERA)
        self.assertEqual(merged.price_range, "2.5 Cr onwards")

    def test_earliest_discovery_and_latest_update_are_kept(self):
        a = row("Godrej Athena", "Godrej Properties", "Pending",
                first_discovered="2025-01-05 09:00:00",
                last_updated="2025-01-05 09:00:00")
        b = row("Godrej Athena", "Godrej Properties", REAL_RERA,
                first_discovered="2024-03-02 09:00:00",
                last_updated="2026-09-20 09:00:00")
        merged, _ = merge_project_cluster([2, 3], {2: a, 3: b})
        self.assertEqual(merged.first_discovered, "2024-03-02 09:00:00")
        self.assertEqual(merged.last_updated, "2026-09-20 09:00:00")

    def test_longest_amenities_win(self):
        row_map = {
            2: row("Godrej Athena", "Godrej Properties", "Pending", key_amenities="Pool"),
            3: row("Godrej Athena", "Godrej Properties", REAL_RERA,
                   key_amenities="Pool, clubhouse, metro 400m, 12 acre park"),
        }
        merged, _ = merge_project_cluster([2, 3], row_map)
        self.assertEqual(merged.key_amenities, "Pool, clubhouse, metro 400m, 12 acre park")

    def test_merged_row_is_sheet_shaped(self):
        row_map = {
            2: row("Godrej Athena", "Godrej Properties", "Pending"),
            3: row("Godrej Athena", "Godrej Properties", REAL_RERA),
        }
        merged, _ = merge_project_cluster([2, 3], row_map)
        self.assertEqual(
            len(merged.to_sheet_row()), len(RealEstateProject.sheet_headers())
        )


class TestRowDeletion(unittest.TestCase):
    """Index arithmetic - the part that silently destroys the wrong rows if wrong."""

    def _worksheet(self):
        ws = mock.MagicMock()
        ws.id = 1234
        return ws

    def _requests(self, ws):
        return ws.spreadsheet.batch_update.call_args[0][0]["requests"]

    def test_contiguous_rows_become_one_range(self):
        ws = self._worksheet()
        delete_rows(ws, [5, 6, 7])
        requests = self._requests(ws)
        self.assertEqual(len(requests), 1)
        rng = requests[0]["deleteDimension"]["range"]
        # 1-based rows 5..7 -> 0-based start 4, end-exclusive 7
        self.assertEqual((rng["startIndex"], rng["endIndex"]), (4, 7))
        self.assertEqual(rng["sheetId"], 1234)
        self.assertEqual(rng["dimension"], "ROWS")

    def test_blocks_are_submitted_bottom_up(self):
        """Descending order, so an earlier delete never shifts a later one."""
        ws = self._worksheet()
        delete_rows(ws, [3, 10, 11, 20])
        starts = [r["deleteDimension"]["range"]["startIndex"] for r in self._requests(ws)]
        self.assertEqual(starts, sorted(starts, reverse=True))
        self.assertEqual(starts, [19, 9, 2])

    def test_unsorted_input_is_handled(self):
        ws = self._worksheet()
        delete_rows(ws, [11, 3, 10])
        ranges = [
            (r["deleteDimension"]["range"]["startIndex"],
             r["deleteDimension"]["range"]["endIndex"])
            for r in self._requests(ws)
        ]
        self.assertEqual(ranges, [(9, 11), (2, 3)])

    def test_single_row(self):
        ws = self._worksheet()
        delete_rows(ws, [2])
        rng = self._requests(ws)[0]["deleteDimension"]["range"]
        self.assertEqual((rng["startIndex"], rng["endIndex"]), (1, 2))

    def test_empty_list_makes_no_call(self):
        ws = self._worksheet()
        delete_rows(ws, [])
        ws.spreadsheet.batch_update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
