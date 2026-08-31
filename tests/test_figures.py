#!/usr/bin/env python3
"""Unit tests for figures.py — heading_similarity and condition_matches_skip.

Covers the field-aware heading matching introduced to fix numeric-token
confusion (e.g., '75 Minutes' vs 'Humidity: 75%') and the skip_conditions
feature for accelerated stability conditions.

Run with:
    python -m unittest tests.test_figures -v
    # or from the skill root:
    python tests/test_figures.py
"""

import os
import sys
import unittest

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from figures import heading_similarity, condition_matches_skip


# =============================================================================
# heading_similarity — structured field-aware comparison
# =============================================================================

class TestHeadingSimilarityStructured(unittest.TestCase):
    """Tests for the structured (field-aware) comparison path.

    This path activates when both headings have >= 2 recognized fields
    (Package, Property, Temperature, Humidity, Strength_Group).
    """

    def test_identical_headings_score_one(self):
        h = ('Package: PCTFE Blister, Property: Dissolution Average % Dissolved '
             'at 75 Minutes, Temperature: 30 °C, Humidity: 75%, Strength_Group: 1 mg')
        self.assertAlmostEqual(heading_similarity(h, h), 1.0)

    def test_different_minute_value_scores_lower(self):
        """The core bug fix: '75 Minutes' must score higher than '30 Minutes'."""
        prior = ('Package: PCTFE Blister, Property: Dissolution Average % Dissolved '
                 'at 75 Minutes, Temperature: 30 °C, Humidity: 75%, Strength_Group: 1 mg')
        correct = ('Property: Dissolution Average % Dissolved at 75 Minutes, '
                   'Temperature: 30 °C, Humidity: 75%, Package: PCTFE, Strength_Group: 1 mg')
        wrong = ('Property: Dissolution Average % Dissolved at 30 Minutes, '
                 'Temperature: 30 °C, Humidity: 75%, Package: PCTFE, Strength_Group: 1 mg')

        score_correct = heading_similarity(prior, correct)
        score_wrong = heading_similarity(prior, wrong)
        self.assertGreater(score_correct, score_wrong)
        # Correct should be very high
        self.assertGreater(score_correct, 0.9)
        # Wrong should still be above 0.7 (it matches most fields)
        self.assertGreater(score_wrong, 0.7)

    def test_60_minutes_not_confused_with_60_percent_humidity(self):
        """Token '60' in Humidity shouldn't boost a '30 Minutes' heading."""
        prior = ('Package: PCTFE Blister, Property: Dissolution Average % Dissolved '
                 'at 60 Minutes, Temperature: 25 °C, Humidity: 60%, Strength_Group: 1 mg')
        correct = ('Property: Dissolution Average % Dissolved at 60 Minutes, '
                   'Temperature: 25 °C, Humidity: 60%, Package: PCTFE, Strength_Group: 1 mg')
        wrong = ('Property: Dissolution Average % Dissolved at 30 Minutes, '
                 'Temperature: 25 °C, Humidity: 60%, Package: PCTFE, Strength_Group: 1 mg')

        self.assertGreater(heading_similarity(prior, correct),
                           heading_similarity(prior, wrong))

    def test_different_package_scores_low(self):
        h1 = ('Package: CFAF Blister, Property: Assay, '
              'Temperature: 30 °C, Humidity: 75%')
        h2 = ('Package: Bottle, Property: Assay, '
              'Temperature: 30 °C, Humidity: 75%')
        score = heading_similarity(h1, h2)
        # Package mismatch should drag score down
        self.assertLess(score, 0.8)

    def test_package_partial_match(self):
        """'PCTFE Blister' vs 'PCTFE' should score ~0.9 for that field."""
        h1 = ('Package: PCTFE Blister, Property: Assay, '
              'Temperature: 30 °C, Humidity: 75%')
        h2 = ('Package: PCTFE, Property: Assay, '
              'Temperature: 30 °C, Humidity: 75%')
        score = heading_similarity(h1, h2)
        # Should be very close to 1.0 (only 0.1 penalty on Package)
        self.assertGreater(score, 0.95)

    def test_different_temperature_exact_mismatch(self):
        h1 = ('Property: Assay, Temperature: 25 °C, Humidity: 60%, '
              'Package: PCTFE')
        h2 = ('Property: Assay, Temperature: 40 °C, Humidity: 60%, '
              'Package: PCTFE')
        score = heading_similarity(h1, h2)
        # One field out of 4 mismatches: score = 3/4 = 0.75
        self.assertAlmostEqual(score, 0.75, places=2)

    def test_different_strength_group(self):
        h1 = ('Property: Assay, Temperature: 30 °C, Humidity: 75%, '
              'Package: CFAF, Strength_Group: 1 mg')
        h2 = ('Property: Assay, Temperature: 30 °C, Humidity: 75%, '
              'Package: CFAF, Strength_Group: 3 mg')
        score = heading_similarity(h1, h2)
        # 4 of 5 fields match: 4/5 = 0.8
        self.assertAlmostEqual(score, 0.8, places=2)

    def test_field_order_does_not_matter(self):
        """Prior uses 'Package: X, Property: Y'; current uses 'Property: Y, Package: X'."""
        h1 = ('Package: CFAF Blister, Property: Water Activity, '
              'Temperature: 30 °C, Humidity: 75%')
        h2 = ('Property: Water Activity, Temperature: 30 °C, '
              'Humidity: 75%, Package: CFAF')
        score = heading_similarity(h1, h2)
        self.assertGreater(score, 0.95)

    def test_minimum_two_fields_triggers_structured(self):
        """With exactly 2 fields, should use structured path."""
        h1 = 'Property: Assay, Package: PCTFE'
        h2 = 'Property: Assay, Package: PCTFE'
        self.assertAlmostEqual(heading_similarity(h1, h2), 1.0)

    def test_one_field_only_uses_fallback(self):
        """With only 1 recognized field, should fallback to token overlap."""
        h1 = 'Property: Assay (% Label Claim)'
        h2 = 'Property: Dissolution Average at 30 Minutes'
        # Fallback path — token-based
        score = heading_similarity(h1, h2)
        self.assertIsInstance(score, float)
        self.assertLess(score, 0.5)


# =============================================================================
# heading_similarity — fallback (token-based) path
# =============================================================================

class TestHeadingSimilarityFallback(unittest.TestCase):
    """Tests for the fallback token-based comparison (unstructured headings).

    DIR document headings use formats like:
        'Dissolution Average Percent Dissolved Results at 75 Minutes in CFAF Blisters at 30°C/75% RH'
    """

    def test_identical_unstructured_headings(self):
        h = 'Dissolution Average Percent Dissolved Results at 75 Minutes in CFAF Blisters at 30°C/75% RH'
        self.assertAlmostEqual(heading_similarity(h, h), 1.0)

    def test_similar_unstructured_headings(self):
        h1 = 'Dissolution Average Percent Dissolved Results at 75 Minutes in CFAF Blisters at 30°C/75% RH'
        h2 = 'Dissolution Average Percent Dissolved Results at 75 Minutes in PCTFE Blisters at 30°C/75% RH'
        score = heading_similarity(h1, h2)
        # Most words overlap except package name
        self.assertGreater(score, 0.8)

    def test_empty_headings_return_zero(self):
        self.assertEqual(heading_similarity('', ''), 0.0)
        self.assertEqual(heading_similarity('hello', ''), 0.0)
        self.assertEqual(heading_similarity('', 'world'), 0.0)

    def test_stopwords_excluded(self):
        """Headings differing only in stop words should score high."""
        h1 = 'Results at the Temperature'
        h2 = 'Results in a Temperature'
        score = heading_similarity(h1, h2)
        # 'results' and 'temperature' overlap, stop words removed
        self.assertAlmostEqual(score, 1.0)

    def test_figure_caption_format(self):
        h1 = 'Figure 3.10.1-1.Water Activity Results for 1 mg and 3 mg Batches Packaged in CFAF Blisters at 30°C/75% RH'
        h2 = 'Figure 3.10.1-2.Water Activity Results for 6 mg and 12 mg Batches Packaged in CFAF Blisters at 30°C/75% RH'
        score = heading_similarity(h1, h2)
        # Very similar, differ only in figure number and mg values
        self.assertGreater(score, 0.7)


# =============================================================================
# condition_matches_skip — structured heading format
# =============================================================================

class TestConditionMatchesSkipStructured(unittest.TestCase):
    """Tests for condition_matches_skip with structured headings."""

    def test_none_skip_conditions_returns_false(self):
        heading = 'Package: PCTFE, Property: Assay, Temperature: 40 °C, Humidity: 75%'
        self.assertFalse(condition_matches_skip(heading, None))

    def test_empty_skip_conditions_returns_false(self):
        heading = 'Package: PCTFE, Property: Assay, Temperature: 40 °C, Humidity: 75%'
        self.assertFalse(condition_matches_skip(heading, set()))

    def test_matching_condition_returns_true(self):
        heading = ('Package: PCTFE Blister, Property: Dissolution Average % Dissolved '
                   'at 60 Minutes, Temperature: 40 °C, Humidity: 75%, Strength_Group: 1 mg')
        self.assertTrue(condition_matches_skip(heading, {(40, 75)}))

    def test_non_matching_condition_returns_false(self):
        heading = ('Package: PCTFE Blister, Property: Dissolution Average % Dissolved '
                   'at 60 Minutes, Temperature: 25 °C, Humidity: 60%, Strength_Group: 1 mg')
        self.assertFalse(condition_matches_skip(heading, {(40, 75)}))

    def test_multiple_skip_conditions(self):
        heading = 'Property: Assay, Temperature: 30 °C, Humidity: 65%, Package: PCTFE'
        skip = {(40, 75), (30, 65)}
        self.assertTrue(condition_matches_skip(heading, skip))

    def test_30c_75_not_matched_when_skipping_40_75(self):
        """30°C/75%RH (intermediate condition) should NOT be skipped."""
        heading = 'Property: Assay, Temperature: 30 °C, Humidity: 75%, Package: CFAF'
        self.assertFalse(condition_matches_skip(heading, {(40, 75)}))

    def test_humidity_number_not_confused_with_temperature(self):
        """Heading with '75' in Humidity should not match temperature=75."""
        heading = 'Property: Assay, Temperature: 25 °C, Humidity: 75%, Package: CFAF'
        # Skip (75, 60) — should NOT match because temp is 25, not 75
        self.assertFalse(condition_matches_skip(heading, {(75, 60)}))


# =============================================================================
# condition_matches_skip — DIR heading format
# =============================================================================

class TestConditionMatchesSkipDIR(unittest.TestCase):
    """Tests for condition_matches_skip with DIR-style headings.

    DIR headings use format: '... at 40°C/75% RH'
    """

    def test_dir_format_matching(self):
        heading = 'Dissolution Average Percent Dissolved Results at 75 Minutes in PCTFE Blisters at 40°C/75% RH'
        self.assertTrue(condition_matches_skip(heading, {(40, 75)}))

    def test_dir_format_non_matching(self):
        heading = 'Assay Results in PCTFE Blisters at 25°C/60% RH'
        self.assertFalse(condition_matches_skip(heading, {(40, 75)}))

    def test_dir_format_30c_75(self):
        heading = 'Water Activity Results in CFAF Blisters at 30°C/75% RH'
        self.assertFalse(condition_matches_skip(heading, {(40, 75)}))
        self.assertTrue(condition_matches_skip(heading, {(30, 75)}))

    def test_dir_format_with_degree_symbol_variations(self):
        """Handle '40 °C' (space before degree) vs '40°C' (no space)."""
        h_no_space = 'Results at 40°C/75% RH'
        h_with_space = 'Results at 40 °C/75% RH'
        skip = {(40, 75)}
        self.assertTrue(condition_matches_skip(h_no_space, skip))
        # The regex uses \s*°?\s*C — should handle space before °
        self.assertTrue(condition_matches_skip(h_with_space, skip))

    def test_heading_with_no_condition_info(self):
        """Headings without temperature/humidity return False (not skipped)."""
        heading = 'Figure 3.1-1. Assay Results for 1 mg and 3 mg Batches'
        self.assertFalse(condition_matches_skip(heading, {(40, 75)}))

    def test_empty_heading(self):
        self.assertFalse(condition_matches_skip('', {(40, 75)}))

    def test_minute_value_not_parsed_as_temperature(self):
        """'45 Minutes' should not be parsed as temperature 45."""
        heading = 'Dissolution at 45 Minutes in Blisters'
        # No °C or Humidity in this heading, so neither regex should match
        self.assertFalse(condition_matches_skip(heading, {(45, 75)}))


# =============================================================================
# skip_conditions CLI parsing (integration-level)
# =============================================================================

class TestSkipConditionsParsing(unittest.TestCase):
    """Tests for the CLI string → set parsing used by both scripts."""

    def _parse(self, arg_string):
        """Simulate the parsing logic from figures.py/tables.py main()."""
        skip_conditions = set()
        for cond in arg_string.split(','):
            temp, hum = cond.strip().split('/')
            skip_conditions.add((int(temp), int(hum)))
        return skip_conditions

    def test_single_condition(self):
        result = self._parse('40/75')
        self.assertEqual(result, {(40, 75)})

    def test_multiple_conditions(self):
        result = self._parse('40/75,30/65')
        self.assertEqual(result, {(40, 75), (30, 65)})

    def test_whitespace_handling(self):
        result = self._parse(' 40/75 , 30/65 ')
        self.assertEqual(result, {(40, 75), (30, 65)})

    def test_malformed_no_slash_raises(self):
        with self.assertRaises(ValueError):
            self._parse('4075')

    def test_non_numeric_raises(self):
        with self.assertRaises(ValueError):
            self._parse('forty/75')


# =============================================================================
# Orchestrator skip_conditions logic
# =============================================================================

class TestOrchestratorSkipLogic(unittest.TestCase):
    """Tests for the timepoint → skip_conditions derivation."""

    def _compute_skip(self, timepoint_str):
        """Simulate orchestrate.py logic: skip 40/75 when months > 6."""
        timepoint_months = int(timepoint_str.rstrip('M'))
        if timepoint_months > 6:
            return '40/75'
        return None

    def test_6m_does_not_skip(self):
        """At exactly 6M, accelerated condition is still updated."""
        self.assertIsNone(self._compute_skip('6M'))

    def test_9m_skips(self):
        self.assertEqual(self._compute_skip('9M'), '40/75')

    def test_12m_skips(self):
        self.assertEqual(self._compute_skip('12M'), '40/75')

    def test_18m_skips(self):
        self.assertEqual(self._compute_skip('18M'), '40/75')

    def test_24m_skips(self):
        self.assertEqual(self._compute_skip('24M'), '40/75')

    def test_3m_does_not_skip(self):
        """Short timepoints should NOT skip accelerated."""
        self.assertIsNone(self._compute_skip('3M'))

    def test_1m_does_not_skip(self):
        self.assertIsNone(self._compute_skip('1M'))


if __name__ == '__main__':
    unittest.main()
