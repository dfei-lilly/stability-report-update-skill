#!/usr/bin/env python3
"""Stability Report Update — Orchestrator.

Sequential 8-task pipeline for updating a DIR stability report from one
timepoint to the next. Supports optional package filtering.

Tasks:
  1. author-reviewer      — personnel updates
  2. data-hash            — hash value updates
  3. golf-paths           — folder path references
  4. filenames            — filename references
  5. timepoint-text       — timepoint text replacement
  6. figures              — figure image replacement
  7. tables               — table value updates (per-table inference)
  8. delete-sections      — remove non-target package sections (if --packages)

Usage:
    python orchestrate.py \
      --prior-folder /path/to/prior/vendor \
      --current-folder /path/to/current/vendor \
      --timepoint "18M" \
      --author "John Smith" \
      --di-reviewer "Jane Doe" \
      --tech-reviewer "Bob Jones" \
      --packages "HDPE (125cc)"
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import date

# All scripts live in the same directory as this orchestrator
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.expanduser('~/.claude/skills')
UNPACK_SCRIPT = os.path.join(SKILLS_DIR, 'docx', 'scripts', 'office', 'unpack.py')
PACK_SCRIPT = os.path.join(SKILLS_DIR, 'docx', 'scripts', 'office', 'pack.py')


def validate_inputs(args):
    """Validate all required inputs exist."""
    errors = []

    if not os.path.isdir(args.prior_folder):
        errors.append(f"Prior folder does not exist: {args.prior_folder}")
    elif args.prior_report:
        prior_report_path = os.path.join(args.prior_folder, args.prior_report)
        if not os.path.isfile(prior_report_path):
            errors.append(f"Prior report not found: {prior_report_path}")

    if not os.path.isdir(args.current_folder):
        errors.append(f"Current folder does not exist: {args.current_folder}")

    if not re.match(r'^\d+M$', args.timepoint):
        errors.append(f"Timepoint format invalid (expected e.g. '18M'): {args.timepoint}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False
    return True


def extract_timepoint(filename):
    """Extract timepoint (e.g. '12M') from a DIR report filename."""
    if not filename:
        return None
    match = re.search(r'(\d+M)', filename)
    return match.group(1) if match else None


# Package keywords for detecting package type from folder names.
FOLDER_PACKAGE_KEYWORDS = {
    'HDPE (125cc)': ['bottle', 'bottles', 'hdpe'],
    'CFAF Blister': ['cfaf', 'cff'],
    'PCTFE Blister': ['pctfe'],
    'Bulk Simulator': ['bulk'],
}


def detect_package_keyword(folder_name):
    """Detect package type from a folder name by keyword matching.

    Returns the canonical package name (e.g., 'HDPE (125cc)') or None.
    """
    name_lower = folder_name.lower()
    for pkg_name, keywords in FOLDER_PACKAGE_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return pkg_name
    return None


def step0_setup(args, working_dir):
    """Copy prior report, rename with new timepoint + _DRAFT suffix."""
    prior_report_path = os.path.join(args.prior_folder, args.prior_report)
    old_timepoint = extract_timepoint(args.prior_report)

    # Build new filename
    new_filename = args.prior_report
    if old_timepoint:
        new_filename = new_filename.replace(old_timepoint, args.timepoint)

    # Remove existing suffixes like _FINAL, date stamps, _DRAFT
    base, ext = os.path.splitext(new_filename)
    base = re.sub(r'_FINAL(?:_\d{2}[A-Z][a-z]{2}\d{4})?$', '', base)
    base = re.sub(r'_\d{2}[A-Z][a-z]{2}\d{4}$', '', base)
    base = re.sub(r'_DRAFT$', '', base)
    new_filename = f"{base}_DRAFT{ext}"

    dest_path = os.path.join(working_dir, new_filename)
    shutil.copy2(prior_report_path, dest_path)

    print(f"  Prior report: {args.prior_report}")
    print(f"  Working copy: {new_filename}")
    if old_timepoint and old_timepoint != args.timepoint:
        print(f"  Timepoint:    {old_timepoint} → {args.timepoint}")
    elif old_timepoint:
        print(f"  Timepoint:    {old_timepoint} (data refresh — same timepoint)")

    # Copy zip files from current vendor folder
    zip_count = 0
    for pattern in ['DIR_[Pp]kg_*.zip', 'stab_package_*.zip']:
        for zf in glob.glob(os.path.join(args.current_folder, pattern)):
            dest_zip = os.path.join(working_dir, os.path.basename(zf))
            if not os.path.exists(dest_zip):
                shutil.copy2(zf, dest_zip)
                zip_count += 1
    if zip_count > 0:
        print(f"  Copied {zip_count} zip file(s) from current vendor folder")

    # Extract prior vendor plots/data
    prior_plots = os.path.join(args.prior_folder, 'stability_plots.docx')
    prior_data = os.path.join(args.prior_folder, 'stability_plot_data.xlsx')
    prior_vendor_dir = os.path.join(working_dir, 'prior_vendor')

    if os.path.exists(prior_plots) and os.path.exists(prior_data):
        os.makedirs(prior_vendor_dir, exist_ok=True)
        shutil.copy2(prior_plots, os.path.join(prior_vendor_dir, 'stability_plots.docx'))
        shutil.copy2(prior_data, os.path.join(prior_vendor_dir, 'stability_plot_data.xlsx'))
        print(f"  Copied prior vendor plots/data from folder")
    else:
        prior_zips = glob.glob(os.path.join(args.prior_folder, 'stab_package_*.zip'))
        extracted = False
        for zp in prior_zips:
            try:
                with zipfile.ZipFile(zp, 'r') as zf:
                    names = zf.namelist()
                    plots_in_zip = [n for n in names if n.endswith('stability_plots.docx')]
                    data_in_zip = [n for n in names if n.endswith('stability_plot_data.xlsx')]
                    if plots_in_zip and data_in_zip:
                        os.makedirs(prior_vendor_dir, exist_ok=True)
                        zf.extract(plots_in_zip[0], prior_vendor_dir)
                        src = os.path.join(prior_vendor_dir, plots_in_zip[0])
                        dst = os.path.join(prior_vendor_dir, 'stability_plots.docx')
                        if src != dst:
                            shutil.move(src, dst)
                        zf.extract(data_in_zip[0], prior_vendor_dir)
                        src = os.path.join(prior_vendor_dir, data_in_zip[0])
                        dst = os.path.join(prior_vendor_dir, 'stability_plot_data.xlsx')
                        if src != dst:
                            shutil.move(src, dst)
                        print(f"  Extracted prior vendor plots/data from {os.path.basename(zp)}")
                        extracted = True
                        break
            except (zipfile.BadZipFile, KeyError):
                continue
        if not extracted:
            print(f"  WARNING: Prior vendor plots/data not found")

    # Copy current vendor plots/data
    cur_plots = os.path.join(args.current_folder, 'stability_plots.docx')
    cur_data = os.path.join(args.current_folder, 'stability_plot_data.xlsx')
    cur_plots_dst = os.path.join(working_dir, 'stability_plots.docx')
    cur_data_dst = os.path.join(working_dir, 'stability_plot_data.xlsx')

    if os.path.exists(cur_plots) and not os.path.exists(cur_plots_dst):
        shutil.copy2(cur_plots, cur_plots_dst)
    if os.path.exists(cur_data) and not os.path.exists(cur_data_dst):
        shutil.copy2(cur_data, cur_data_dst)

    if not os.path.exists(cur_plots_dst) or not os.path.exists(cur_data_dst):
        cur_zips = glob.glob(os.path.join(working_dir, 'stab_package_*.zip'))
        for zp in cur_zips:
            try:
                with zipfile.ZipFile(zp, 'r') as zf:
                    names = zf.namelist()
                    if not os.path.exists(cur_plots_dst):
                        plots_in_zip = [n for n in names if n.endswith('stability_plots.docx')]
                        if plots_in_zip:
                            zf.extract(plots_in_zip[0], working_dir)
                            src = os.path.join(working_dir, plots_in_zip[0])
                            if src != cur_plots_dst:
                                shutil.move(src, cur_plots_dst)
                    if not os.path.exists(cur_data_dst):
                        data_in_zip = [n for n in names if n.endswith('stability_plot_data.xlsx')]
                        if data_in_zip:
                            zf.extract(data_in_zip[0], working_dir)
                            src = os.path.join(working_dir, data_in_zip[0])
                            if src != cur_data_dst:
                                shutil.move(src, cur_data_dst)
            except (zipfile.BadZipFile, KeyError):
                continue

    if os.path.exists(cur_plots_dst):
        print(f"  Current vendor plots/data ready")
    else:
        print(f"  WARNING: Current vendor plots not found")

    return dest_path


def execute_task(cmd, task_name):
    """Run a single subprocess task. Returns (task_name, success, stdout, stderr, duration)."""
    start_time = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return (task_name, False, '', 'TIMEOUT after 300s', time.time() - start_time)
    except Exception as e:
        return (task_name, False, '', str(e), time.time() - start_time)

    duration = time.time() - start_time
    return (task_name, result.returncode == 0, result.stdout, result.stderr, duration)


def run_tasks_sequential(working_copy, args, xml_dir):
    """Execute all 8 tasks sequentially.

    Order:
      1. author-reviewer  — header metadata
      2. data-hash        — hash values
      3. golf-paths       — folder path references
      4. filenames        — filename references
      5. timepoint-text   — timepoint text
      6. figures          — image replacement
      7. tables           — table values (per-table inference)
      8. delete-sections  — remove non-target package headings (if --packages)
    """
    working_dir = os.path.dirname(working_copy)
    python = sys.executable
    task_list = []

    # Determine old timepoint and whether this is a same-timepoint refresh.
    old_tp = args.old_timepoint or extract_timepoint(args.prior_report) or ''
    is_same_timepoint = (old_tp == args.timepoint)

    if is_same_timepoint:
        print(f"  Mode: Same-timepoint data refresh ({args.timepoint})")
        print(f"  Skipping: timepoint-text (no timepoint change)")
        print(f"  Accelerated conditions: will be processed (not skipped)")
        print()

    # Accelerated stability conditions stop collecting data after this cutoff.
    # On a same-timepoint refresh, never skip — vendor may have corrected data.
    ACCELERATED_CUTOFF_MONTHS = 6
    ACCELERATED_CONDITIONS = '40/75'  # 40°C/75%RH

    skip_conditions = None
    timepoint_months = int(args.timepoint.rstrip('M'))
    if timepoint_months > ACCELERATED_CUTOFF_MONTHS and not is_same_timepoint:
        skip_conditions = ACCELERATED_CONDITIONS

    # Detect cross-package mode: prior folder has one package, target is different.
    prior_folder_name = os.path.basename(os.path.normpath(args.prior_folder))
    current_folder_name = os.path.basename(os.path.normpath(args.current_folder))
    prior_pkg = detect_package_keyword(prior_folder_name)
    current_pkg = detect_package_keyword(current_folder_name)
    is_cross_package = (args.packages and prior_pkg and current_pkg
                        and prior_pkg != current_pkg)

    if is_cross_package:
        print(f"  Cross-package mode: {prior_pkg} → {current_pkg}")
        print(f"  Template sections from {prior_pkg} will be filled with {current_pkg} data")
        print()

    # 1. author-reviewer
    script = os.path.join(SCRIPTS_DIR, 'author_reviewer.py')
    if os.path.exists(script):
        task_list.append(('author-reviewer', [
            python, script, working_dir,
            '--author', args.author,
            '--di-reviewer', args.di_reviewer,
            '--tech-reviewer', args.tech_reviewer,
            '--xml-dir', xml_dir
        ]))

    # 2. data-hash
    script = os.path.join(SCRIPTS_DIR, 'data_hash.py')
    if os.path.exists(script):
        task_list.append(('data-hash', [python, script, working_dir, '--xml-dir', xml_dir]))

    # 3. golf-paths
    script = os.path.join(SCRIPTS_DIR, 'golf_paths.py')
    current_folder_name = os.path.basename(os.path.normpath(args.current_folder))
    if os.path.exists(script):
        task_list.append(('golf-paths', [
            python, script, working_dir,
            '--new-folder-name', current_folder_name,
            '--xml-dir', xml_dir
        ]))

    # 4. filenames
    script = os.path.join(SCRIPTS_DIR, 'filenames.py')
    if os.path.exists(script):
        task_list.append(('filenames', [
            python, script, working_dir,
            '--prior-folder', args.prior_folder,
            '--current-folder', args.current_folder,
            '--xml-dir', xml_dir
        ]))

    # 5. timepoint-text (skip on same-timepoint — no text change needed)
    script = os.path.join(SCRIPTS_DIR, 'timepoint_text.py')
    if os.path.exists(script) and old_tp and not is_same_timepoint:
        task_list.append(('timepoint-text', [
            python, script, working_dir,
            '--old-timepoint', old_tp,
            '--new-timepoint', args.timepoint,
            '--xml-dir', xml_dir
        ]))

    # 6. figures
    # NOTE: Do NOT pass --skip-conditions to figures. Even though accelerated
    # conditions (40/75) stop collecting new data after 6M, the vendor may
    # regenerate plots with updated styling, so they always need replacing.
    script = os.path.join(SCRIPTS_DIR, 'figures.py')
    if os.path.exists(script):
        fig_cmd = [python, script, working_dir, '--xml-dir', xml_dir]
        if args.packages:
            fig_cmd.extend(['--packages', args.packages])
        if is_cross_package:
            fig_cmd.append('--cross-package')
        task_list.append(('figures', fig_cmd))

    # 7. tables
    script = os.path.join(SCRIPTS_DIR, 'tables.py')
    if os.path.exists(script):
        tbl_cmd = [python, script, working_dir, '--xml-dir', xml_dir]
        if args.packages:
            tbl_cmd.extend(['--packages', args.packages])
        if skip_conditions:
            tbl_cmd.extend(['--skip-conditions', skip_conditions])
        if is_cross_package:
            tbl_cmd.append('--cross-package')
        task_list.append(('tables', tbl_cmd))

    # 8. delete-sections (only if --packages specified)
    script = os.path.join(SCRIPTS_DIR, 'delete_sections.py')
    if os.path.exists(script) and args.packages:
        task_list.append(('delete-sections', [
            python, script, working_dir,
            '--packages', args.packages,
            '--xml-dir', xml_dir
        ]))

    if not task_list:
        print("  WARNING: No task scripts found!", file=sys.stderr)
        return {}

    print(f"\n  Running {len(task_list)} tasks sequentially...")
    print(f"  Order: {' → '.join(name for name, _ in task_list)}")
    print()

    results = {}
    for task_name, cmd in task_list:
        task_name, success, stdout, stderr, duration = execute_task(cmd, task_name)
        status = '✓' if success else '✗'
        print(f"  {status} {task_name} ({duration:.1f}s)")
        if stdout.strip():
            for line in stdout.strip().split('\n'):
                print(f"      {line}")
        if not success and stderr.strip():
            print(f"      ERROR: {stderr.strip()[:200]}")

        results[task_name] = {
            'success': success,
            'duration': duration,
            'stdout': stdout,
            'stderr': stderr
        }

    return results


def print_summary(working_copy, results, args):
    """Print final summary as JSON for Claude to parse."""
    total_time = sum(r['duration'] for r in results.values())
    successes = sum(1 for r in results.values() if r['success'])
    failures = sum(1 for r in results.values() if not r['success'])

    summary = {
        'working_copy': working_copy,
        'working_dir': os.path.dirname(working_copy),
        'timepoint': args.timepoint,
        'prior_folder': args.prior_folder,
        'current_folder': args.current_folder,
        'packages': args.packages,
        'tasks_completed': successes,
        'tasks_failed': failures,
        'total_time_seconds': round(total_time, 1),
        'task_results': {
            name: {'success': r['success'], 'duration': round(r['duration'], 1)}
            for name, r in results.items()
        }
    }

    print(f"\n{'='*60}")
    print("STABILITY REPORT UPDATE COMPLETE")
    print(f"{'='*60}")
    print(f"  Output: {os.path.basename(working_copy)}")
    print(f"  Tasks: {successes}/{successes + failures} passed ({total_time:.1f}s)")
    if args.packages:
        print(f"  Package filter: {args.packages}")

    if failures > 0:
        print(f"\n  Failures:")
        for name, r in results.items():
            if not r['success']:
                print(f"    ✗ {name}: {r['stderr'][:100]}")

    print(f"{'='*60}")
    print(f"\n__ORCHESTRATOR_RESULT__")
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description='Stability Report Update — Orchestrator')
    parser.add_argument('--prior-folder', required=True)
    parser.add_argument('--prior-report', default=None)
    parser.add_argument('--current-folder', required=True)
    parser.add_argument('--timepoint', required=True)
    parser.add_argument('--author', required=True)
    parser.add_argument('--di-reviewer', required=True)
    parser.add_argument('--tech-reviewer', required=True)
    parser.add_argument('--working-dir', default='.')
    parser.add_argument('--old-timepoint', default=None)
    parser.add_argument('--packages', default=None,
                       help='Comma-separated package filter (e.g., "HDPE (125cc)")')
    args = parser.parse_args()

    # Resolve paths
    args.prior_folder = os.path.abspath(args.prior_folder)
    args.current_folder = os.path.abspath(args.current_folder)
    working_dir = os.path.abspath(args.working_dir)

    # Auto-discover prior report
    if not args.prior_report:
        candidates = glob.glob(os.path.join(args.prior_folder, 'DIR_Form_*.docx'))
        candidates = [c for c in candidates if not os.path.basename(c).startswith('~$')]
        if len(candidates) == 1:
            args.prior_report = os.path.basename(candidates[0])
        elif len(candidates) > 1:
            print(f"ERROR: Multiple DIR_Form_*.docx found. Specify --prior-report.", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"ERROR: No DIR_Form_*.docx found in: {args.prior_folder}", file=sys.stderr)
            sys.exit(1)

    print("═══════════════════════════════════════════════════════════════")
    print("STABILITY REPORT UPDATE")
    print("═══════════════════════════════════════════════════════════════")

    # Validate
    print("\n[Step 0] Validating inputs...")
    if not validate_inputs(args):
        sys.exit(1)
    print("  ✓ All inputs valid")

    # Setup
    print("\n[Step 0] Creating working copy...")
    working_copy = step0_setup(args, working_dir)
    print(f"  ✓ Working copy ready")

    # Unpack DRAFT once
    print("\n[Step 0] Unpacking DRAFT for editing...")
    xml_dir = tempfile.mkdtemp(prefix='dir_work_')
    try:
        unpack_result = subprocess.run(
            [sys.executable, UNPACK_SCRIPT, working_copy, xml_dir, '--no-indent'],
            capture_output=True, text=True, timeout=60
        )
        if unpack_result.returncode != 0:
            print(f"  ERROR unpacking: {unpack_result.stderr[:200]}", file=sys.stderr)
            sys.exit(1)
        print(f"  ✓ Unpacked to temp directory")

        # Run all tasks
        print("\n[Running] All tasks sequentially...")
        results = run_tasks_sequential(working_copy, args, xml_dir)

        # Repack
        print("\n[Step F] Repacking DRAFT...")
        pack_result = subprocess.run(
            [sys.executable, PACK_SCRIPT, xml_dir, working_copy, '--validate', 'false'],
            capture_output=True, text=True, timeout=60
        )
        if pack_result.returncode != 0:
            print(f"  ERROR repacking: {pack_result.stderr[:200]}", file=sys.stderr)
            sys.exit(1)
        print(f"  ✓ Repacked successfully")

        # Cleanup auxiliary files
        for pattern in ['DIR_Pkg_*.zip', 'stab_package_*.zip',
                        'stability_plots.docx', 'stability_plot_data.xlsx']:
            for f in glob.glob(os.path.join(working_dir, pattern)):
                os.remove(f)
        prior_vendor_dir = os.path.join(working_dir, 'prior_vendor')
        if os.path.isdir(prior_vendor_dir):
            shutil.rmtree(prior_vendor_dir)

    finally:
        shutil.rmtree(xml_dir, ignore_errors=True)

    # Summary
    print_summary(working_copy, results, args)

    if any(not r['success'] for r in results.values()):
        sys.exit(1)


if __name__ == '__main__':
    main()
