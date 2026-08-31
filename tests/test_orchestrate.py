#!/usr/bin/env python3
"""Unit tests for orchestrate.py — same-timepoint and accelerated condition logic.

Covers:
  - Same-timepoint detection skips timepoint-text task
  - Same-timepoint never skips accelerated conditions for tables
  - Different timepoint (>6M) still skips accelerated conditions
  - _DRAFT suffix not doubled when prior report already has it

Run with:
    python -m pytest tests/test_orchestrate.py -v
    # or from the skill root:
    python -m unittest tests.test_orchestrate -v
"""

import os
import re
import sys
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from orchestrate import run_tasks_sequential, step0_setup, extract_timepoint


def make_args(**overrides):
    """Build a minimal args Namespace for run_tasks_sequential."""
    defaults = {
        'prior_folder': '/tmp/prior',
        'current_folder': '/tmp/current',
        'prior_report': 'DIR_Form_OGF_18M_FINAL.docx',
        'timepoint': '18M',
        'old_timepoint': '18M',
        'author': 'Test Author',
        'di_reviewer': 'Test DI',
        'tech_reviewer': 'Test Tech',
        'packages': '',
    }
    defaults.update(overrides)
    return Namespace(**defaults)


# =============================================================================
# extract_timepoint — None safety
# =============================================================================

class TestExtractTimepoint(unittest.TestCase):
    """extract_timepoint must handle None and empty inputs without crashing."""

    def test_none_returns_none(self):
        self.assertIsNone(extract_timepoint(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(extract_timepoint(''))

    def test_normal_extraction(self):
        self.assertEqual(extract_timepoint('DIR_Form_OGF_12M_FINAL.docx'), '12M')


# =============================================================================
# Same-timepoint detection
# =============================================================================

class TestSameTimepointSkipsTimepointText(unittest.TestCase):
    """When old_timepoint == timepoint, timepoint-text task must be excluded."""

    @patch('os.path.exists', return_value=True)
    def test_same_timepoint_excludes_timepoint_text(self, mock_exists):
        """Task list should NOT contain 'timepoint-text' when timepoints match,
        but all other tasks (except delete-sections without packages) must be present."""
        args = make_args(old_timepoint='18M', timepoint='18M')
        with tempfile.TemporaryDirectory() as tmpdir:
            working_copy = os.path.join(tmpdir, 'test.docx')
            open(working_copy, 'w').close()
            xml_dir = os.path.join(tmpdir, 'xml')
            os.makedirs(xml_dir, exist_ok=True)

            with patch('subprocess.run') as mock_run:
                mock_run.return_value = type('R', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()
                results = run_tasks_sequential(working_copy, args, xml_dir)

            task_names = list(results.keys())
            self.assertNotIn('timepoint-text', task_names)

            # All other tasks must still be present
            expected_tasks = ['author-reviewer', 'data-hash', 'golf-paths',
                             'filenames', 'figures', 'tables']
            for task in expected_tasks:
                self.assertIn(task, task_names, f"Expected task '{task}' missing")

            # delete-sections absent when no packages specified
            self.assertNotIn('delete-sections', task_names)

    @patch('os.path.exists', return_value=True)
    def test_same_timepoint_with_packages_includes_delete_sections(self, mock_exists):
        """Same timepoint + packages → delete-sections should still be included."""
        args = make_args(old_timepoint='18M', timepoint='18M',
                         packages='HDPE (125cc)')
        with tempfile.TemporaryDirectory() as tmpdir:
            working_copy = os.path.join(tmpdir, 'test.docx')
            open(working_copy, 'w').close()
            xml_dir = os.path.join(tmpdir, 'xml')
            os.makedirs(xml_dir, exist_ok=True)

            with patch('subprocess.run') as mock_run:
                mock_run.return_value = type('R', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()
                results = run_tasks_sequential(working_copy, args, xml_dir)

            task_names = list(results.keys())
            self.assertIn('delete-sections', task_names)
            self.assertNotIn('timepoint-text', task_names)

    @patch('os.path.exists', return_value=True)
    def test_different_timepoint_includes_timepoint_text(self, mock_exists):
        """Task list SHOULD contain 'timepoint-text' when timepoints differ."""
        args = make_args(old_timepoint='12M', timepoint='18M',
                         prior_report='DIR_Form_OGF_12M_FINAL.docx')
        with tempfile.TemporaryDirectory() as tmpdir:
            working_copy = os.path.join(tmpdir, 'test.docx')
            open(working_copy, 'w').close()
            xml_dir = os.path.join(tmpdir, 'xml')
            os.makedirs(xml_dir, exist_ok=True)

            with patch('subprocess.run') as mock_run:
                mock_run.return_value = type('R', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()
                results = run_tasks_sequential(working_copy, args, xml_dir)

            task_names = list(results.keys())
            self.assertIn('timepoint-text', task_names)


# =============================================================================
# Accelerated condition logic
# =============================================================================

class TestAcceleratedConditionLogic(unittest.TestCase):
    """Accelerated conditions (40/75) should only be skipped for timepoint
    progression (not refresh) AND only when timepoint > 6M."""

    @patch('os.path.exists', return_value=True)
    def test_same_timepoint_does_not_skip_accelerated(self, mock_exists):
        """Same timepoint at 18M: tables must NOT receive --skip-conditions."""
        args = make_args(old_timepoint='18M', timepoint='18M')
        with tempfile.TemporaryDirectory() as tmpdir:
            working_copy = os.path.join(tmpdir, 'test.docx')
            open(working_copy, 'w').close()
            xml_dir = os.path.join(tmpdir, 'xml')
            os.makedirs(xml_dir, exist_ok=True)

            captured_cmds = {}

            def capture_run(cmd, **kwargs):
                # Find task name from the script path
                for name in ['tables', 'figures', 'author_reviewer',
                             'data_hash', 'golf_paths', 'filenames',
                             'delete_sections']:
                    if any(name in str(c) for c in cmd):
                        captured_cmds[name] = cmd
                        break
                return type('R', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()

            with patch('subprocess.run', side_effect=capture_run):
                run_tasks_sequential(working_copy, args, xml_dir)

            # tables command should NOT have --skip-conditions
            self.assertIn('tables', captured_cmds)
            self.assertNotIn('--skip-conditions', captured_cmds['tables'])

    @patch('os.path.exists', return_value=True)
    def test_different_timepoint_above_6M_skips_accelerated(self, mock_exists):
        """12M → 18M: tables MUST receive --skip-conditions 40/75."""
        args = make_args(old_timepoint='12M', timepoint='18M',
                         prior_report='DIR_Form_OGF_12M_FINAL.docx')
        with tempfile.TemporaryDirectory() as tmpdir:
            working_copy = os.path.join(tmpdir, 'test.docx')
            open(working_copy, 'w').close()
            xml_dir = os.path.join(tmpdir, 'xml')
            os.makedirs(xml_dir, exist_ok=True)

            captured_cmds = {}

            def capture_run(cmd, **kwargs):
                for name in ['tables', 'figures']:
                    if any(name in str(c) for c in cmd):
                        captured_cmds[name] = cmd
                        break
                return type('R', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()

            with patch('subprocess.run', side_effect=capture_run):
                run_tasks_sequential(working_copy, args, xml_dir)

            self.assertIn('tables', captured_cmds)
            tbl_cmd = captured_cmds['tables']
            self.assertIn('--skip-conditions', tbl_cmd)
            skip_idx = tbl_cmd.index('--skip-conditions')
            self.assertEqual(tbl_cmd[skip_idx + 1], '40/75')

    @patch('os.path.exists', return_value=True)
    def test_different_timepoint_at_6M_no_skip(self, mock_exists):
        """3M → 6M: tables must NOT skip accelerated (cutoff is >6M, not >=)."""
        args = make_args(old_timepoint='3M', timepoint='6M',
                         prior_report='DIR_Form_OGF_3M_FINAL.docx')
        with tempfile.TemporaryDirectory() as tmpdir:
            working_copy = os.path.join(tmpdir, 'test.docx')
            open(working_copy, 'w').close()
            xml_dir = os.path.join(tmpdir, 'xml')
            os.makedirs(xml_dir, exist_ok=True)

            captured_cmds = {}

            def capture_run(cmd, **kwargs):
                if any('tables' in str(c) for c in cmd):
                    captured_cmds['tables'] = cmd
                return type('R', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()

            with patch('subprocess.run', side_effect=capture_run):
                run_tasks_sequential(working_copy, args, xml_dir)

            self.assertIn('tables', captured_cmds)
            self.assertNotIn('--skip-conditions', captured_cmds['tables'])


# =============================================================================
# _DRAFT suffix doubling
# =============================================================================

class TestDraftSuffixNotDoubled(unittest.TestCase):
    """Prior report with _DRAFT in name must not produce *_DRAFT_DRAFT.docx."""

    def test_draft_suffix_stripped_before_readding(self):
        """step0_setup should strip existing _DRAFT before appending it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prior_dir = os.path.join(tmpdir, 'prior')
            working_dir = os.path.join(tmpdir, 'working')
            os.makedirs(prior_dir)
            os.makedirs(working_dir)

            # Create a prior report with _DRAFT in the name
            prior_name = 'DIR_Form_OGF_18M_DRAFT.docx'
            open(os.path.join(prior_dir, prior_name), 'w').close()

            args = make_args(
                prior_folder=prior_dir,
                current_folder=prior_dir,  # doesn't matter for this test
                prior_report=prior_name,
                timepoint='18M',
                old_timepoint='18M',
            )

            working_copy = step0_setup(args, working_dir)
            filename = os.path.basename(working_copy)

            # Should be *_DRAFT.docx, NOT *_DRAFT_DRAFT.docx
            self.assertNotIn('_DRAFT_DRAFT', filename)
            self.assertTrue(filename.endswith('_DRAFT.docx'))

    def test_final_suffix_produces_clean_draft(self):
        """Standard case: _FINAL → _DRAFT without doubling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prior_dir = os.path.join(tmpdir, 'prior')
            working_dir = os.path.join(tmpdir, 'working')
            os.makedirs(prior_dir)
            os.makedirs(working_dir)

            prior_name = 'DIR_Form_OGF_12M_FINAL_14Jun2025.docx'
            open(os.path.join(prior_dir, prior_name), 'w').close()

            args = make_args(
                prior_folder=prior_dir,
                current_folder=prior_dir,
                prior_report=prior_name,
                timepoint='18M',
                old_timepoint='12M',
            )

            working_copy = step0_setup(args, working_dir)
            filename = os.path.basename(working_copy)

            self.assertEqual(filename, 'DIR_Form_OGF_18M_DRAFT.docx')


if __name__ == '__main__':
    unittest.main()
