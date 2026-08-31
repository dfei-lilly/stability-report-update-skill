#!/usr/bin/env python3
"""Fuzzy-match filenames between prior/current vendor folders and update DIR with tracked changes.

Version: 1.01
Changes from v1.0:
  - Added \\s* whitespace tolerance in regex patterns (Strategy 1, 2, 3) to handle
    pretty-printed XML from unpack.py (toprettyxml inserts newlines between elements)

Usage:
    python update_filenames.py [project_folder] \
        --prior-folder "/path/to/prior" \
        --current-folder "/path/to/current"

Discovers DIR_Form_*_DRAFT.docx in project_folder, replaces all prior filename
references with their current counterparts using Word tracked changes.
"""

import argparse
import glob
import os
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import date
from difflib import SequenceMatcher

# Import shared XML escape utility
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared_utils import xml_escape, find_max_id

AUTHOR = "Claude"
TODAY = date.today().isoformat()

# Global ID counter for tracked change IDs
_next_id = 4000


def get_next_ids():
    global _next_id
    del_id = _next_id
    ins_id = _next_id + 1
    _next_id += 2
    return del_id, ins_id


# --- Filename Matching ---

# Patterns to strip when building a "skeleton" for comparison
DATE_PATTERNS = [
    r'\d{14}',                    # 20251007141040 (14-digit timestamp)
    r'\d{2}-[A-Z]{3}-\d{4}',     # 01-OCT-2025
    r'\d{2}[A-Z][a-z]{2}\d{4}',  # 28Aug2025, 01Oct2025
    r'\d{2}[A-Z][a-z]{2}\d{2}',  # 28Aug25
    r'\d{2}[A-Z][a-z]{2}',       # 28Aug (no year)
    r'\d{4}_\d{2}_\d{2}',        # 2025_08_14
    r'\d{2}[A-Z][a-z]{2}\d{4}',  # 09Dec2025
    r'\d{4}\d{2}\d{2}',          # 20250829 (8-digit date, only if not part of longer number)
    r'V\d+',                      # V3 version markers
]

# Files that should never be matched/replaced (generic names shared across timepoints)
SKIP_PATTERNS = [
    r'^stability_plots\.docx$',
    r'^stability_plot_data\.xlsx$',
    r'^PRD-PRT-.*\.pdf$',
    r'^~\$',  # Word temp files
]


def should_skip(filename):
    """Check if a filename should be excluded from matching."""
    for pat in SKIP_PATTERNS:
        if re.match(pat, filename, re.IGNORECASE):
            return True
    return False


def build_skeleton(filename):
    """Strip date/timestamp components to get the structural skeleton."""
    name, ext = os.path.splitext(filename)
    skeleton = name
    for pat in DATE_PATTERNS:
        skeleton = re.sub(pat, '', skeleton)
    # Clean up resulting double underscores/dashes
    skeleton = re.sub(r'[_\-]{2,}', '_', skeleton)
    skeleton = skeleton.strip('_- ')
    return skeleton.lower(), ext.lower()


def compute_similarity(skel1, skel2):
    """Compute similarity ratio between two skeletons."""
    return SequenceMatcher(None, skel1, skel2).ratio()


def build_filename_mapping(prior_folder, current_folder):
    """Build mapping of prior filenames to current filenames.

    Returns:
        mapping: dict of {prior_filename: current_filename}
        unchanged: list of filenames that exist in both (no replacement needed)
        unmatched: list of prior filenames with no current counterpart
    """
    prior_files = [f for f in os.listdir(prior_folder)
                   if os.path.isfile(os.path.join(prior_folder, f)) and not should_skip(f)]
    current_files = [f for f in os.listdir(current_folder)
                     if os.path.isfile(os.path.join(current_folder, f)) and not should_skip(f)]

    # Step 1: Find exact matches (unchanged files)
    prior_set = set(prior_files)
    current_set = set(current_files)
    unchanged = list(prior_set & current_set)

    # Remove unchanged from consideration
    prior_to_match = [f for f in prior_files if f not in current_set]
    current_candidates = [f for f in current_files if f not in prior_set]

    # Step 2: Build skeletons
    prior_skeletons = {f: build_skeleton(f) for f in prior_to_match}
    current_skeletons = {f: build_skeleton(f) for f in current_candidates}

    mapping = {}
    matched_current = set()

    # Step 3: Match by skeleton similarity + same extension
    # Sort prior files by skeleton length (longer = more specific = match first)
    sorted_prior = sorted(prior_to_match, key=lambda f: len(prior_skeletons[f][0]), reverse=True)

    for prior_f in sorted_prior:
        p_skel, p_ext = prior_skeletons[prior_f]
        best_match = None
        best_score = 0.0

        for current_f in current_candidates:
            c_skel, c_ext = current_skeletons[current_f]

            # Must have same extension (case-insensitive)
            if p_ext != c_ext:
                continue

            # If already matched, only allow if skeleton is identical (e.g., stab_package)
            if current_f in matched_current and c_skel != p_skel:
                continue

            score = compute_similarity(p_skel, c_skel)
            if score > best_score:
                best_score = score
                best_match = current_f

        # Accept match if similarity is above threshold (0.6 avoids false positives)
        if best_match and best_score >= 0.6:
            mapping[prior_f] = best_match
            matched_current.add(best_match)

    unmatched = [f for f in prior_to_match if f not in mapping]

    return mapping, unchanged, unmatched


def expand_mapping_from_document(mapping, doc_content):
    """Expand the mapping to cover extension variants found in document text.

    When a .zip file maps to another .zip file, this discovers .docx and .xlsx
    references in the document that share the same base name and creates additional
    mappings for those variants.

    Since filenames may be split across multiple XML runs (e.g., base name in one
    <w:t> and extension in another), we join paragraph text to check for presence.

    Returns: expanded mapping dict
    """
    import xml.etree.ElementTree as ET

    # Build set of all paragraph texts for checking filename presence
    para_texts = set()
    try:
        root = ET.fromstring(doc_content)
        ns_w = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        for para in root.iter(f'{{{ns_w}}}p'):
            texts = []
            for t in para.iter(f'{{{ns_w}}}t'):
                if t.text:
                    texts.append(t.text)
            if texts:
                para_texts.add(''.join(texts))
    except ET.ParseError:
        para_texts = set()

    def filename_in_document(fn):
        """Check if filename appears in any paragraph (joined text)."""
        # First try raw content (fast path)
        if fn in doc_content:
            return True
        # Then check joined paragraph text (handles split runs)
        for pt in para_texts:
            if fn in pt:
                return True
        return False

    expanded = dict(mapping)

    for prior_f, current_f in list(mapping.items()):
        prior_base = os.path.splitext(prior_f)[0]
        current_base = os.path.splitext(current_f)[0]

        # Check for other extension variants of this base name in the document
        for ext in ['.docx', '.xlsx', '.zip', '.csv', '.jmp']:
            variant_prior = prior_base + ext
            variant_current = current_base + ext

            # Skip if this is the original mapping or already mapped
            if variant_prior == prior_f or variant_prior in expanded:
                continue

            # Only add if the prior variant actually appears in the document
            if filename_in_document(variant_prior):
                expanded[variant_prior] = variant_current

    return expanded


# --- XML Tracked Change Replacement ---

def replace_filename_tracked(content, old_filename, new_filename):
    """Replace all occurrences of old_filename with tracked changes in XML content.

    Uses two strategies:
    1. Single-run: filename contained entirely in one <w:t> element
    2. Paragraph-level: filename split across multiple <w:r> runs

    Handles both compact XML (from .docx zip) and pretty-printed XML (from unpack.py)
    by using \\s* between element boundaries.

    Returns: (modified_content, replacement_count)
    """
    if not old_filename or old_filename == new_filename:
        return content, 0

    count = 0
    escaped = re.escape(old_filename)

    # Strategy 1: Single-run match — filename is entirely within one <w:t>
    # The pattern allows for optional elements between rPr and <w:t> like
    # <w:lastRenderedPageBreak/>, <w:tab/>, <w:br/>, etc.
    # Note: \s* between tags handles pretty-printed XML (newlines + indentation)
    run_pattern = re.compile(
        r'(<w:r(?:\s[^>]*)?>)\s*'
        r'((?:<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?)\s*'
        r'(?:<w:[^/]*/>\s*)*'  # optional self-closing elements (lastRenderedPageBreak, tab, br)
        r'<w:t([^>]*)>' + escaped + r'</w:t>\s*</w:r>',
        re.DOTALL
    )

    def make_tracked_change_exact(m):
        nonlocal count
        rpr_xml = m.group(2)
        del_id, ins_id = get_next_ids()

        if not rpr_xml:
            rpr_xml = ''

        count += 1
        return (
            f'<w:del w:id="{del_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
            f'<w:r>{rpr_xml}<w:delText>{xml_escape(old_filename)}</w:delText></w:r>'
            f'</w:del>'
            f'<w:ins w:id="{ins_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
            f'<w:r>{rpr_xml}<w:t xml:space="preserve">{xml_escape(new_filename)}</w:t></w:r>'
            f'</w:ins>'
        )

    content = run_pattern.sub(make_tracked_change_exact, content)

    # Strategy 2: Filename contained within a <w:t> that has other text too
    # (e.g., "Refer to DIR_Pkg_OFG_....docx for details")
    if old_filename in content:
        mixed_pattern = re.compile(
            r'(<w:r(?:\s[^>]*)?>)\s*'
            r'((?:<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?)\s*'
            r'(?:<w:[^/]*/>\s*)*'  # optional self-closing elements
            r'<w:t([^>]*)>([^<]*?' + escaped + r'[^<]*?)</w:t>\s*</w:r>',
            re.DOTALL
        )

        def make_tracked_change_mixed(m):
            nonlocal count
            rpr_xml = m.group(2)
            t_attrs = m.group(3)
            full_text = m.group(4)

            if not rpr_xml:
                rpr_xml = ''

            idx = full_text.find(old_filename)
            before = full_text[:idx]
            after = full_text[idx + len(old_filename):]

            del_id, ins_id = get_next_ids()
            count += 1

            result = ''
            # Text before the filename (unchanged)
            if before:
                result += f'<w:r>{rpr_xml}<w:t{t_attrs}>{xml_escape(before)}</w:t></w:r>'
            # Tracked change for the filename
            result += (
                f'<w:del w:id="{del_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
                f'<w:r>{rpr_xml}<w:delText>{xml_escape(old_filename)}</w:delText></w:r>'
                f'</w:del>'
                f'<w:ins w:id="{ins_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
                f'<w:r>{rpr_xml}<w:t xml:space="preserve">{xml_escape(new_filename)}</w:t></w:r>'
                f'</w:ins>'
            )
            # Text after the filename (unchanged)
            if after:
                result += f'<w:r>{rpr_xml}<w:t{t_attrs}>{xml_escape(after)}</w:t></w:r>'
            return result

        content = mixed_pattern.sub(make_tracked_change_mixed, content)

    # Strategy 3: Paragraph-level fallback for text split across runs
    # Always try this — some occurrences may be in single runs (caught above)
    # while others in the same document are split across multiple runs
    content, para_count = _replace_split_runs(content, old_filename, new_filename)
    count += para_count

    return content, count


def _replace_split_runs(content, old_filename, new_filename):
    """Handle filenames split across multiple <w:r> runs within a paragraph."""
    para_pattern = re.compile(r'(<w:p\b[^>]*>)(.*?)(</w:p>)', re.DOTALL)
    t_pattern = re.compile(r'<w:t[^>]*>([^<]*)</w:t>')
    count = 0

    def process_paragraph(m):
        nonlocal count
        p_open = m.group(1)
        p_inner = m.group(2)
        p_close = m.group(3)

        # Join all <w:t> text to check if this paragraph contains the filename
        texts = t_pattern.findall(p_inner)
        joined = ''.join(texts)

        if old_filename not in joined:
            return m.group(0)

        # Find the runs that contain parts of the filename
        # Extract all runs with their text
        # Note: \s* between tags handles pretty-printed XML (newlines + indentation)
        run_pattern = re.compile(
            r'(<w:r(?:\s[^>]*)?>)\s*'
            r'((?:<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?)\s*'
            r'(<w:t[^>]*>[^<]*</w:t>)\s*'
            r'(</w:r>)',
            re.DOTALL
        )

        runs = list(run_pattern.finditer(p_inner))
        if not runs:
            return m.group(0)

        # Build cumulative text positions
        run_texts = []
        for r in runs:
            t_match = re.search(r'<w:t[^>]*>([^<]*)</w:t>', r.group(3))
            run_texts.append(t_match.group(1) if t_match else '')

        cumulative = ''.join(run_texts)
        fn_start = cumulative.find(old_filename)
        if fn_start == -1:
            return m.group(0)

        fn_end = fn_start + len(old_filename)

        # Find which runs span the filename
        pos = 0
        start_run_idx = None
        end_run_idx = None
        for i, txt in enumerate(run_texts):
            run_end = pos + len(txt)
            if start_run_idx is None and run_end > fn_start:
                start_run_idx = i
            if run_end >= fn_end:
                end_run_idx = i
                break
            pos = run_end

        if start_run_idx is None or end_run_idx is None:
            return m.group(0)

        # Get rPr from the first run containing the filename
        first_run = runs[start_run_idx]
        rpr_xml = first_run.group(2) or ''

        del_id, ins_id = get_next_ids()
        count += 1

        # Rebuild paragraph content:
        # - Keep runs before the filename span
        # - Replace the spanning runs with del/ins
        # - Keep runs after the filename span
        new_inner = p_inner[:runs[start_run_idx].start()]

        # Text before filename in the start run
        pos = 0
        for i in range(start_run_idx):
            pos += len(run_texts[i])
        before_in_run = run_texts[start_run_idx][:fn_start - pos]
        if before_in_run:
            new_inner += f'<w:r>{rpr_xml}<w:t xml:space="preserve">{xml_escape(before_in_run)}</w:t></w:r>'

        # The tracked change
        new_inner += (
            f'<w:del w:id="{del_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
            f'<w:r>{rpr_xml}<w:delText>{xml_escape(old_filename)}</w:delText></w:r>'
            f'</w:del>'
            f'<w:ins w:id="{ins_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
            f'<w:r>{rpr_xml}<w:t xml:space="preserve">{xml_escape(new_filename)}</w:t></w:r>'
            f'</w:ins>'
        )

        # Text after filename in the end run
        pos = 0
        for i in range(end_run_idx):
            pos += len(run_texts[i])
        after_start = fn_end - pos
        after_in_run = run_texts[end_run_idx][after_start:]
        if after_in_run:
            new_inner += f'<w:r>{rpr_xml}<w:t xml:space="preserve">{xml_escape(after_in_run)}</w:t></w:r>'

        # Keep the rest after the end run
        new_inner += p_inner[runs[end_run_idx].end():]

        return p_open + new_inner + p_close

    content = para_pattern.sub(process_paragraph, content)
    return content, count


# --- Main ---

def find_draft(folder):
    """Find DIR_Form_*_DRAFT.docx in folder."""
    pattern = os.path.join(folder, 'DIR_Form_*_DRAFT.docx')
    matches = glob.glob(pattern)
    if not matches:
        return None
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description='Update filename references in DIR with tracked changes')
    parser.add_argument('project_folder', nargs='?', default='.',
                        help='Project folder containing DIR_Form_*_DRAFT.docx')
    parser.add_argument('--prior-folder', required=True,
                        help='Path to prior vendor folder')
    parser.add_argument('--current-folder', required=True,
                        help='Path to current vendor folder')
    parser.add_argument('--xml-dir', default=None,
                        help='Pre-unpacked XML directory (skip unpack/repack)')
    args = parser.parse_args()

    project_folder = os.path.abspath(args.project_folder)
    prior_folder = os.path.abspath(args.prior_folder)
    current_folder = os.path.abspath(args.current_folder)

    # Validate inputs
    if not os.path.isdir(prior_folder):
        print(f"ERROR: Prior folder not found: {prior_folder}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(current_folder):
        print(f"ERROR: Current folder not found: {current_folder}", file=sys.stderr)
        sys.exit(1)

    draft = find_draft(project_folder)
    if not draft:
        print(f"ERROR: No DIR_Form_*_DRAFT.docx found in {project_folder}", file=sys.stderr)
        sys.exit(1)

    print(f"Draft: {os.path.basename(draft)}")
    print(f"Prior folder: {os.path.basename(prior_folder)}")
    print(f"Current folder: {os.path.basename(current_folder)}")
    print()

    # Build filename mapping
    mapping, unchanged, unmatched = build_filename_mapping(prior_folder, current_folder)

    print(f"Filename Mapping (from folder comparison):")
    print(f"  Matched: {len(mapping)}")
    print(f"  Unchanged (skip): {len(unchanged)}")
    print(f"  Unmatched: {len(unmatched)}")

    # Detect many-to-one mappings (multiple prior files → same current file)
    target_counts = {}
    for target in mapping.values():
        target_counts[target] = target_counts.get(target, 0) + 1
    many_to_one = {t: c for t, c in target_counts.items() if c > 1}
    if many_to_one:
        print(f"\n  WARNING: {len(many_to_one)} many-to-one mapping(s) detected:")
        for target, cnt in many_to_one.items():
            sources = [p for p, t in mapping.items() if t == target]
            print(f"    {cnt} prior files → {target}:")
            for s in sources:
                print(f"      - {s}")

    print()

    if not mapping:
        print("No filename replacements needed.")
        return

    # Get document XML content
    if args.xml_dir:
        doc_xml_path = os.path.join(args.xml_dir, 'word', 'document.xml')
        tmp_dir = None
        with open(doc_xml_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Set ID counter above any existing tracked changes
        global _next_id
        _next_id = find_max_id(content) + 100
    else:
        tmp_dir = tempfile.TemporaryDirectory(prefix='fn_update_')
        with zipfile.ZipFile(draft, 'r') as zf:
            zf.extractall(tmp_dir.name)
        doc_xml_path = os.path.join(tmp_dir.name, 'word', 'document.xml')
        if not os.path.exists(doc_xml_path):
            print("ERROR: word/document.xml not found in draft", file=sys.stderr)
            sys.exit(1)
        with open(doc_xml_path, 'r', encoding='utf-8') as f:
            content = f.read()

    try:
        # Expand mapping with extension variants found in document
        mapping = expand_mapping_from_document(mapping, content)

        if mapping:
            print("  Full mapping (including extension variants):")
            for old_f, new_f in sorted(mapping.items()):
                print(f"    {old_f}")
                print(f"      → {new_f}")
            print()

        if unmatched:
            print("  Unmatched prior files (no current counterpart found):")
            for f in sorted(unmatched):
                print(f"    {f}")
            print()

        # Apply replacements (longest filenames first to avoid partial matches)
        total_replacements = 0
        replacement_details = []

        sorted_mapping = sorted(mapping.items(), key=lambda x: len(x[0]), reverse=True)

        for old_filename, new_filename in sorted_mapping:
            content, count = replace_filename_tracked(content, old_filename, new_filename)

            # If no matches found, try case-variant extension (.JMP vs .jmp, etc.)
            if count == 0:
                base, ext = os.path.splitext(old_filename)
                alt_ext = ext.upper() if ext == ext.lower() else ext.lower()
                alt_old = base + alt_ext
                if alt_old != old_filename:
                    content, count = replace_filename_tracked(content, alt_old, new_filename)

            if count > 0:
                replacement_details.append((old_filename, new_filename, count))
                total_replacements += count

        # Write back
        with open(doc_xml_path, 'w', encoding='utf-8') as f:
            f.write(content)

        # Repack only in standalone mode
        if tmp_dir:
            with zipfile.ZipFile(draft, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(tmp_dir.name):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, tmp_dir.name)
                        zf.write(file_path, arcname)

        # Report
        print("=" * 60)
        print("Filename Update Summary:")
        print(f"  Mappings applied: {len(replacement_details)}")
        print(f"  Total replacements: {total_replacements}")
        print(f"  Unchanged files skipped: {len(unchanged)}")
        print(f"  Unmatched prior files: {len(unmatched)}")
        print()
        if replacement_details:
            print("  Details:")
            for old_f, new_f, cnt in replacement_details:
                print(f"    {old_f}")
                print(f"      → {new_f} ({cnt} occurrences)")
            print()
        print(f"  Output: {draft}")
        print("=" * 60)

    finally:
        if tmp_dir:
            tmp_dir.cleanup()


if __name__ == '__main__':
    main()
