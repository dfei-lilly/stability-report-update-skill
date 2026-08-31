#!/usr/bin/env python3
"""Unit tests for stability-report-update scripts.

Tests cover the core utility functions that are most likely to break
when modifying the skill. No .docx files needed — just hardcoded inputs
and expected outputs.

Run with:
    python -m unittest tests.test_utils -v
    # or from the skill root:
    python tests/test_utils.py
"""

import math
import os
import sys
import unittest

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from tables import (
    extract_property,
    find_property_in_vendor,
    extract_package_from_caption,
    extract_strength_groups_from_caption,
    parse_condition,
    parse_value,
    apply_rounding,
    get_vendor_values,
    infer_aggregation_and_rounding,
)
from shared_utils import xml_escape, find_max_id


# =============================================================================
# parse_value tests
# =============================================================================

class TestParseValue(unittest.TestCase):
    """Tests for parse_value() — numeric cell parsing."""

    def test_percentage_one_decimal(self):
        val, fmt = parse_value("95.5%")
        self.assertEqual(val, 95.5)
        self.assertEqual(fmt['decimals'], 1)
        self.assertEqual(fmt['suffix'], '%')

    def test_percentage_zero_decimals(self):
        val, fmt = parse_value("82%")
        self.assertEqual(val, 82.0)
        self.assertEqual(fmt['decimals'], 0)
        self.assertEqual(fmt['suffix'], '%')

    def test_plain_number_two_decimals(self):
        val, fmt = parse_value("0.14")
        self.assertEqual(val, 0.14)
        self.assertEqual(fmt['decimals'], 2)
        self.assertEqual(fmt['suffix'], '')

    def test_integer_no_suffix(self):
        val, fmt = parse_value("100")
        self.assertEqual(val, 100.0)
        self.assertEqual(fmt['decimals'], 0)
        self.assertEqual(fmt['suffix'], '')

    def test_na_returns_none(self):
        self.assertEqual(parse_value("N/A"), (None, None))

    def test_dash_returns_none(self):
        self.assertEqual(parse_value("-"), (None, None))
        self.assertEqual(parse_value("—"), (None, None))

    def test_nmt_returns_none(self):
        self.assertEqual(parse_value("NMT 2.0%"), (None, None))

    def test_nlt_returns_none(self):
        self.assertEqual(parse_value("NLT 80%"), (None, None))

    def test_empty_returns_none(self):
        self.assertEqual(parse_value(""), (None, None))
        self.assertEqual(parse_value("   "), (None, None))

    def test_whitespace_stripped(self):
        val, fmt = parse_value("  95.2%  ")
        self.assertEqual(val, 95.2)


# =============================================================================
# apply_rounding tests
# =============================================================================

class TestApplyRounding(unittest.TestCase):
    """Tests for apply_rounding() — floor/ceil/round."""

    def test_round_standard(self):
        # Python uses banker's rounding (round half to even)
        self.assertEqual(apply_rounding(95.46, 1, 'round'), 95.5)
        self.assertEqual(apply_rounding(95.54, 1, 'round'), 95.5)

    def test_floor(self):
        self.assertEqual(apply_rounding(95.99, 0, 'floor'), 95.0)
        self.assertEqual(apply_rounding(0.149, 2, 'floor'), 0.14)

    def test_ceil(self):
        self.assertEqual(apply_rounding(95.01, 0, 'ceil'), 96.0)
        self.assertEqual(apply_rounding(0.141, 2, 'ceil'), 0.15)

    def test_round_zero_decimals(self):
        self.assertEqual(apply_rounding(95.5, 0, 'round'), 96.0)
        self.assertEqual(apply_rounding(95.4, 0, 'round'), 95.0)

    def test_exact_value_unchanged(self):
        self.assertEqual(apply_rounding(95.0, 0, 'round'), 95.0)
        self.assertEqual(apply_rounding(95.0, 0, 'floor'), 95.0)
        self.assertEqual(apply_rounding(95.0, 0, 'ceil'), 95.0)


# =============================================================================
# parse_condition tests
# =============================================================================

class TestParseCondition(unittest.TestCase):
    """Tests for parse_condition() — storage condition parsing."""

    def test_standard_format(self):
        self.assertEqual(parse_condition("25°C/60% RH"), (25, 60))
        self.assertEqual(parse_condition("30°C/65% RH"), (30, 65))
        self.assertEqual(parse_condition("40°C/75% RH"), (40, 75))

    def test_no_match(self):
        self.assertEqual(parse_condition("Room temperature"), (None, None))
        self.assertEqual(parse_condition(""), (None, None))

    def test_different_formatting(self):
        # Should still extract the numbers
        self.assertEqual(parse_condition("25 C / 60% RH"), (25, 60))


# =============================================================================
# extract_property tests
# =============================================================================

class TestExtractProperty(unittest.TestCase):
    """Tests for extract_property() — property name from caption."""

    def test_assay(self):
        self.assertEqual(
            extract_property("Range of Observed Assay Results in Bottles"),
            'Assay (% Label Claim)')

    def test_water_activity(self):
        self.assertEqual(
            extract_property("Range of Observed Water Activity Results in PCTFE Blisters"),
            'Aw')

    def test_dissolution_average(self):
        self.assertEqual(
            extract_property("Dissolution Average Percent Dissolved Results at 45 Minutes in Bottles"),
            'Average % Dissolved at 45 Minutes')

    def test_dissolution_minimum(self):
        self.assertEqual(
            extract_property("Dissolution Minimum Percent Dissolved Results at 30 Minutes in Bulk"),
            'Minimum % Dissolved at 30 Minutes')

    def test_degradation_returns_none(self):
        self.assertIsNone(extract_property("Total Degradation Products"))

    def test_unrecognized_returns_none(self):
        self.assertIsNone(extract_property("Some random table caption"))

    def test_various_minute_values(self):
        self.assertEqual(
            extract_property("Average Percent Dissolved at 15 Minutes"),
            'Average % Dissolved at 15 Minutes')
        self.assertEqual(
            extract_property("Minimum Percent Dissolved at 90 Minutes"),
            'Minimum % Dissolved at 90 Minutes')


# =============================================================================
# extract_package_from_caption tests
# =============================================================================

class TestExtractPackageFromCaption(unittest.TestCase):
    """Tests for extract_package_from_caption() — data-driven package matching."""

    def setUp(self):
        """Create mock vendor data with known packages."""
        self.vendor_data = [
            {'Property': 'Assay', 'Package': '30 Count Bottle', 'Temperature': 25},
            {'Property': 'Assay', 'Package': 'PCTFE Blister', 'Temperature': 25},
            {'Property': 'Assay', 'Package': 'CFAF Blister', 'Temperature': 30},
            {'Property': 'Assay', 'Package': 'Bag', 'Temperature': 30},
        ]

    def test_direct_match(self):
        pkg, _ = extract_package_from_caption("Results in PCTFE Blister at 25C", self.vendor_data)
        self.assertEqual(pkg, 'PCTFE Blister')

    def test_word_level_match_bottle(self):
        pkg, _ = extract_package_from_caption("Results in Bottles at 25C/60%", self.vendor_data)
        self.assertEqual(pkg, '30 Count Bottle')

    def test_word_level_match_cfaf(self):
        pkg, _ = extract_package_from_caption("Results in CFAF Blisters at 30C", self.vendor_data)
        self.assertEqual(pkg, 'CFAF Blister')

    def test_no_match_returns_none(self):
        pkg, _ = extract_package_from_caption("General stability results", self.vendor_data)
        self.assertIsNone(pkg)

    def test_case_insensitive(self):
        pkg, _ = extract_package_from_caption("results in pctfe blisters", self.vendor_data)
        self.assertEqual(pkg, 'PCTFE Blister')


# =============================================================================
# extract_strength_groups_from_caption tests
# =============================================================================

class TestExtractStrengthGroups(unittest.TestCase):
    """Tests for extract_strength_groups_from_caption()."""

    def setUp(self):
        self.vendor_data = [
            {'Property': 'Assay (% Label Claim)', 'Strength_Group': 'Group 1: 1 mg & 3 mg'},
            {'Property': 'Assay (% Label Claim)', 'Strength_Group': 'Group 2: 6 mg & 12 mg'},
            {'Property': 'Assay (% Label Claim)', 'Strength_Group': 'Group 3: 24 mg & 36 mg'},
        ]

    def test_range_1_to_12(self):
        groups = extract_strength_groups_from_caption(
            "for the 1 – 12 mg Dose Strengths",
            self.vendor_data, 'Assay (% Label Claim)')
        self.assertIsNotNone(groups)
        self.assertEqual(len(groups), 2)  # Group 1 and Group 2
        self.assertTrue(any('Group 1' in g for g in groups))
        self.assertTrue(any('Group 2' in g for g in groups))

    def test_range_24_and_36(self):
        groups = extract_strength_groups_from_caption(
            "for the 24 and 36 mg Dose Strengths",
            self.vendor_data, 'Assay (% Label Claim)')
        self.assertIsNotNone(groups)
        self.assertEqual(len(groups), 1)  # Only Group 3
        self.assertTrue(any('Group 3' in g for g in groups))

    def test_no_strength_filter(self):
        groups = extract_strength_groups_from_caption(
            "Range of Observed Assay Results in Bottles",
            self.vendor_data, 'Assay (% Label Claim)')
        self.assertIsNone(groups)  # No filter = all groups

    def test_hyphen_range(self):
        groups = extract_strength_groups_from_caption(
            "for the 1-12 mg Strengths",
            self.vendor_data, 'Assay (% Label Claim)')
        self.assertIsNotNone(groups)
        self.assertEqual(len(groups), 2)


# =============================================================================
# get_vendor_values tests
# =============================================================================

class TestGetVendorValues(unittest.TestCase):
    """Tests for get_vendor_values() — vendor data filtering."""

    def setUp(self):
        self.vendor_data = [
            {'Property': 'Assay (% Label Claim)', 'Package': 'Bottle', 'Temperature': 25, 'Humidity': 60, 'Strength_Group': 'Group 1', 'Minimum': 95.5, 'Maximum': 101.3},
            {'Property': 'Assay (% Label Claim)', 'Package': 'Bottle', 'Temperature': 25, 'Humidity': 60, 'Strength_Group': 'Group 2', 'Minimum': 95.2, 'Maximum': 100.8},
            {'Property': 'Assay (% Label Claim)', 'Package': 'Blister', 'Temperature': 25, 'Humidity': 60, 'Strength_Group': 'Group 1', 'Minimum': 96.0, 'Maximum': 102.0},
        ]

    def test_basic_filter(self):
        vals = get_vendor_values(self.vendor_data, 'Assay (% Label Claim)', 25, 60, 'Minimum')
        self.assertEqual(len(vals), 3)

    def test_package_filter(self):
        vals = get_vendor_values(self.vendor_data, 'Assay (% Label Claim)', 25, 60, 'Minimum', packages=['Bottle'])
        self.assertEqual(len(vals), 2)
        self.assertAlmostEqual(vals[0], 95.5)
        self.assertAlmostEqual(vals[1], 95.2)

    def test_strength_group_filter(self):
        vals = get_vendor_values(self.vendor_data, 'Assay (% Label Claim)', 25, 60, 'Minimum', strength_groups=['Group 1'])
        self.assertEqual(len(vals), 2)  # Bottle Group 1 + Blister Group 1

    def test_both_filters(self):
        vals = get_vendor_values(self.vendor_data, 'Assay (% Label Claim)', 25, 60, 'Minimum', packages=['Bottle'], strength_groups=['Group 1'])
        self.assertEqual(len(vals), 1)
        self.assertAlmostEqual(vals[0], 95.5)

    def test_no_match_returns_empty(self):
        vals = get_vendor_values(self.vendor_data, 'Aw', 25, 60, 'Minimum')
        self.assertEqual(vals, [])


# =============================================================================
# infer_aggregation_and_rounding tests
# =============================================================================

class TestInferAggregationAndRounding(unittest.TestCase):
    """Tests for infer_aggregation_and_rounding() — the core inference engine."""

    def test_min_round_confirmed(self):
        """If table shows min-of-mins with standard rounding, inference should confirm."""
        vendor_data = [
            {'Property': 'Assay', 'Package': 'Bottle', 'Temperature': 25, 'Humidity': 60, 'Strength_Group': 'G1', 'Minimum': 95.49, 'Maximum': 101.3},
            {'Property': 'Assay', 'Package': 'Bottle', 'Temperature': 25, 'Humidity': 60, 'Strength_Group': 'G2', 'Minimum': 95.71, 'Maximum': 100.8},
        ]
        # Table shows 95.5% (= round(min(95.49, 95.71), 1))
        table_cells = [
            ('Assay', 25, 60, 'Minimum', 95.5, {'decimals': 1, 'suffix': '%'}),
            ('Assay', 25, 60, 'Maximum', 101.3, {'decimals': 1, 'suffix': '%'}),
        ]
        result = infer_aggregation_and_rounding(table_cells, vendor_data, ['Bottle'], None)
        self.assertIsNotNone(result)
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['rule_min'], 'min')
        self.assertEqual(result['rule_max'], 'max')

    def test_floor_rounding_detected(self):
        """If table uses floor rounding, inference should detect it."""
        vendor_data = [
            {'Property': 'Diss', 'Package': 'X', 'Temperature': 30, 'Humidity': 65, 'Strength_Group': 'G1', 'Minimum': 82.7, 'Maximum': 99.0},
        ]
        # Table shows 82% (= floor(82.7) = 82, not round(82.7) = 83)
        table_cells = [
            ('Diss', 30, 65, 'Minimum', 82.0, {'decimals': 0, 'suffix': '%'}),
        ]
        result = infer_aggregation_and_rounding(table_cells, vendor_data, ['X'], None)
        self.assertIsNotNone(result)
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['rounding_min'], 'floor')

    def test_no_data_returns_none(self):
        """No matching vendor data → returns None."""
        result = infer_aggregation_and_rounding(
            [('Assay', 25, 60, 'Minimum', 95.5, {'decimals': 1, 'suffix': '%'})],
            [], None, None)
        self.assertIsNone(result)

    def test_empty_cells_returns_none(self):
        result = infer_aggregation_and_rounding([], [{'Property': 'X'}], None, None)
        self.assertIsNone(result)


# =============================================================================
# find_property_in_vendor tests
# =============================================================================

class TestFindPropertyInVendor(unittest.TestCase):
    """Tests for find_property_in_vendor() — prefix resolution."""

    def setUp(self):
        self.vendor_data = [
            {'Property': 'Dissolution Average % Dissolved at 45 Minutes'},
            {'Property': 'Assay (% Label Claim)'},
            {'Property': 'Aw'},
        ]

    def test_exact_match(self):
        result = find_property_in_vendor('Assay (% Label Claim)', self.vendor_data)
        self.assertEqual(result, 'Assay (% Label Claim)')

    def test_adds_dissolution_prefix(self):
        result = find_property_in_vendor('Average % Dissolved at 45 Minutes', self.vendor_data)
        self.assertEqual(result, 'Dissolution Average % Dissolved at 45 Minutes')

    def test_no_match_returns_original(self):
        result = find_property_in_vendor('Nonexistent Property', self.vendor_data)
        self.assertEqual(result, 'Nonexistent Property')

    def test_none_input(self):
        result = find_property_in_vendor(None, self.vendor_data)
        self.assertIsNone(result)


# =============================================================================
# shared_utils tests
# =============================================================================

class TestXmlEscape(unittest.TestCase):
    """Tests for xml_escape()."""

    def test_ampersand(self):
        self.assertEqual(xml_escape("Smith&Nephew"), "Smith&amp;Nephew")

    def test_angle_brackets(self):
        self.assertEqual(xml_escape("<tag>"), "&lt;tag&gt;")

    def test_quotes(self):
        self.assertEqual(xml_escape('He said "hi"'), 'He said &quot;hi&quot;')

    def test_no_special_chars(self):
        self.assertEqual(xml_escape("normal text"), "normal text")

    def test_empty_string(self):
        self.assertEqual(xml_escape(""), "")

    def test_none_returns_none(self):
        self.assertIsNone(xml_escape(None))


class TestFindMaxId(unittest.TestCase):
    """Tests for find_max_id()."""

    def test_finds_max(self):
        xml = '<w:del w:id="100"><w:ins w:id="200">'
        self.assertEqual(find_max_id(xml), 200)

    def test_no_ids_returns_zero(self):
        self.assertEqual(find_max_id("<w:p><w:r></w:r></w:p>"), 0)

    def test_single_id(self):
        self.assertEqual(find_max_id('<w:del w:id="42">'), 42)


if __name__ == '__main__':
    unittest.main(verbosity=2)
