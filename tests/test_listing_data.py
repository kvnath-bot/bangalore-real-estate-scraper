"""
Tests for src/listing_data.py - the price / BHK / possession layer.

These pin the parsers that turn what agents type into numbers the map can
filter on, the strict type-from-name guess, and the rule that a seed never
overwrites an agent's entry.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.listing_data import (  # noqa: E402
    LISTING_HEADERS,
    load_listing_rows,
    normalise_type,
    parse_bhk,
    parse_price_lakh,
    read_seed,
    rows_to_add,
    type_from_name,
)


class TestTypeFromName(unittest.TestCase):

    def test_clear_keywords(self):
        self.assertEqual(type_from_name("KRK URBAN VILLE VILLAS"), "Villa")
        self.assertEqual(type_from_name("Ashish ANR Row house"), "Row House / Townhouse")
        self.assertEqual(type_from_name("Green Valley Layout"), "Plots")
        self.assertEqual(type_from_name("Sattva Tech Park"), "Commercial")
        self.assertEqual(type_from_name("Prestige Falcon City Apartments"), "Apartment")

    def test_unknown_when_the_name_says_nothing(self):
        for name in ["PRESTIGE FALCON CITY", "GODREJ FLORENNE", "MBS VASUDHA", ""]:
            self.assertEqual(type_from_name(name), "Unknown", name)

    def test_does_not_repeat_the_enrichers_mistakes(self):
        """'Meadows' and 'Acres' are not plots. The old keyword list said they were."""
        self.assertEqual(type_from_name("Brigade Meadows"), "Unknown")
        self.assertEqual(type_from_name("Sobha Dream Acres"), "Unknown")

    def test_row_house_beats_villa_when_both_appear(self):
        self.assertEqual(type_from_name("Sattva Springs Row Villas"), "Row House / Townhouse")


class TestParseBhk(unittest.TestCase):

    def test_common_forms(self):
        self.assertEqual(parse_bhk("2, 3 & 4 BHK"), [2, 3, 4])
        self.assertEqual(parse_bhk("3 BHK"), [3])
        self.assertEqual(parse_bhk("2 and 3 BHK"), [2, 3])
        self.assertEqual(parse_bhk("3/4 BHK"), [3, 4])

    def test_half_bedrooms_round_down(self):
        self.assertEqual(parse_bhk("2.5 BHK"), [2])
        self.assertEqual(parse_bhk("3.5 & 4.5 BHK"), [3, 4])

    def test_ranges_expand(self):
        self.assertEqual(parse_bhk("2-4 BHK"), [2, 3, 4])
        self.assertEqual(parse_bhk("1 to 3 BHK"), [1, 2, 3])

    def test_studio_counts_as_one(self):
        self.assertEqual(parse_bhk("Studio"), [1])
        self.assertEqual(parse_bhk("1 RK, 2 BHK"), [1, 2])

    def test_empty_and_junk(self):
        self.assertEqual(parse_bhk(""), [])
        self.assertEqual(parse_bhk("On request"), [])


class TestParsePriceLakh(unittest.TestCase):

    def test_crore_forms(self):
        self.assertEqual(parse_price_lakh("1.2 Cr"), 120.0)
        self.assertEqual(parse_price_lakh("Rs 2.5 crore onwards"), 250.0)
        self.assertEqual(parse_price_lakh("1,2 cr"), 120.0)

    def test_lakh_forms(self):
        self.assertEqual(parse_price_lakh("85 L"), 85.0)
        self.assertEqual(parse_price_lakh("85 lakh"), 85.0)
        self.assertEqual(parse_price_lakh("Rs. 86.85 Lacs"), 86.85)

    def test_bare_numbers(self):
        self.assertEqual(parse_price_lakh("120"), 120.0, "a bare number is lakh")
        self.assertEqual(parse_price_lakh("1,20,00,000"), 120.0, "a rupee amount converts to lakh")
        self.assertEqual(parse_price_lakh("12000000"), 120.0)

    def test_nothing_numeric(self):
        self.assertIsNone(parse_price_lakh(""))
        self.assertIsNone(parse_price_lakh("On request"))
        self.assertIsNone(parse_price_lakh("."))


class TestNormaliseType(unittest.TestCase):

    def test_canonical_and_loose_inputs(self):
        self.assertEqual(normalise_type("Villa"), "Villa")
        self.assertEqual(normalise_type("villas"), "Villa")
        self.assertEqual(normalise_type("Townhouse"), "Row House / Townhouse")
        self.assertEqual(normalise_type("plotted"), "Plots")
        self.assertEqual(normalise_type("Flat"), "Apartment")
        self.assertEqual(normalise_type("something else"), "Unknown")
        self.assertEqual(normalise_type(""), "")


class TestLoadListingRows(unittest.TestCase):

    def _row(self, rera, typ="Apartment", bhk="2, 3 BHK", price="1.2 Cr", poss="Dec 2027",
             sale="Available", src="https://x", who="Asha", when="2026-09-26", notes=""):
        return [rera, typ, bhk, price, poss, sale, src, who, when, notes]

    def test_rows_are_keyed_and_normalised(self):
        rows = load_listing_rows([self._row("R1")])
        r = rows["R1"]
        self.assertEqual(r["type"], "Apartment")
        self.assertEqual(r["bhk"], [2, 3])
        self.assertEqual(r["price_lakh"], 120.0)
        self.assertEqual(r["possession"], "Dec 2027")
        self.assertEqual(r["source"], "https://x")
        self.assertEqual(r["entered_by"], "Asha")

    def test_later_row_for_same_rera_wins(self):
        rows = load_listing_rows([self._row("R1", price="1.2 Cr"), self._row("R1", price="1.4 Cr")])
        self.assertEqual(rows["R1"]["price_lakh"], 140.0)

    def test_blank_and_short_rows_are_tolerated(self):
        rows = load_listing_rows([[], ["", "Villa"], ["R2"]])
        self.assertEqual(list(rows), ["R2"])
        self.assertEqual(rows["R2"]["price_lakh"], None)
        self.assertEqual(rows["R2"]["bhk"], [])


class TestSeed(unittest.TestCase):

    def test_seed_never_overwrites_existing_rows(self):
        seed = [["R1", "Villa", "4 BHK", "3.8 Cr"], ["R2", "Apartment", "2 BHK", "80 L"]]
        fresh = rows_to_add(existing_reras=["R1"], seed_rows=seed)
        self.assertEqual([r[0] for r in fresh], ["R2"])

    def test_seed_deduplicates_itself(self):
        seed = [["R1", "Villa"], ["R1", "Villa"]]
        self.assertEqual(len(rows_to_add([], seed)), 1)

    def test_seed_rows_are_padded_to_the_header_width(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seed.csv"
            path.write_text(",".join(LISTING_HEADERS) + "\nR1,Villa,4 BHK,3.8 Cr\n\n", encoding="utf-8")
            rows = read_seed(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(len(rows[0]), len(LISTING_HEADERS))
            self.assertEqual(rows[0][:4], ["R1", "Villa", "4 BHK", "3.8 Cr"])

    def test_missing_seed_file_is_empty(self):
        self.assertEqual(read_seed(Path("/definitely/not/here.csv")), [])

    def test_shipped_seed_file_parses(self):
        """The real seed file must always be loadable, even when it is just headers."""
        rows = read_seed()
        for r in rows:
            self.assertEqual(len(r), len(LISTING_HEADERS))


if __name__ == "__main__":
    unittest.main()
