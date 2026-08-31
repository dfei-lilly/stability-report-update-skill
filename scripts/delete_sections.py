#!/usr/bin/env python3
"""Delete non-target package sections from a DIR report using tracked changes.

DIR stability reports use Heading1-level sections to delineate package types.
This script identifies package-specific Heading1 sections and wraps non-target
sections in w:del tracked-change markup, so the user sees deletions in Word's
Track Changes view.

Usage (standalone):
    python delete_package_sections.py <working_dir> --packages "HDPE (125cc)"

Usage (orchestrated, with pre-unpacked XML):
    python delete_package_sections.py <working_dir> --packages "HDPE (125cc)" --xml-dir /tmp/dir_work_xyz

Package keyword mapping:
    "Bottle" or "HDPE" in heading → HDPE (125cc)
    "CFAF" in heading             → CFAF Blister
    "PCTFE" in heading            → PCTFE Blister
    "Bulk" in heading             → Bulk Simulator
    No keyword match              → not a package section (left untouched)
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

# Import shared utilities
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared_utils import find_max_id

TODAY = date.today().strftime('%Y-%m-%dT00:00:00Z')
AUTHOR = 'Claude'

UNPACK_SCRIPT = os.path.expanduser('~/.claude/skills/docx/scripts/office/unpack.py')
PACK_SCRIPT = os.path.expanduser('~/.claude/skills/docx/scripts/office/pack.py')

# Keywords in Heading1 text → package name
HEADING_TO_PACKAGE = {
    'bottle': 'HDPE (125cc)',
    'hdpe': 'HDPE (125cc)',
    'cfaf': 'CFAF Blister',
    'pctfe': 'PCTFE Blister',
    'bulk': 'Bulk Simulator',
}


def normalize_target_packages(user_packages):
    """Convert user-facing package names to internal canonical names.

    Users pass names like 'Bottles', 'CFAF', 'Bulk', 'Blisters' but the
    internal representation uses 'HDPE (125cc)', 'CFAF Blister', etc.
    This function maps user input to the canonical names so that the
    keep/delete comparison works correctly.

    If a user-provided name is already a canonical name (e.g., 'HDPE (125cc)'),
    it passes through unchanged. 'Blister' or 'Blisters' expands to both
    PCTFE Blister and CFAF Blister since both are blister package types.
    """
    # Compound keywords that expand to multiple canonical packages
    COMPOUND_KEYWORDS = {
        'blister': ['PCTFE Blister', 'CFAF Blister'],
        'blisters': ['PCTFE Blister', 'CFAF Blister'],
    }

    canonical_names = set(HEADING_TO_PACKAGE.values())
    normalized = []
    for pkg in user_packages:
        # Already a canonical name — pass through
        if pkg in canonical_names:
            if pkg not in normalized:
                normalized.append(pkg)
            continue
        # Check compound keywords first (e.g., 'Blisters' → both blister types)
        pkg_lower = pkg.lower()
        if pkg_lower in COMPOUND_KEYWORDS:
            for canonical in COMPOUND_KEYWORDS[pkg_lower]:
                if canonical not in normalized:
                    normalized.append(canonical)
            continue
        # Try keyword lookup (same logic as heading detection)
        matched = False
        for keyword, canonical in HEADING_TO_PACKAGE.items():
            if keyword in pkg_lower or pkg_lower in keyword:
                if canonical not in normalized:
                    normalized.append(canonical)
                matched = True
                break
        if not matched:
            # Keep as-is (fallback for future package types)
            normalized.append(pkg)
    return normalized


def identify_package_from_heading(heading_text):
    """Determine which package a Heading1 belongs to based on keywords.

    Returns the package name (e.g., 'HDPE (125cc)') or None if the heading
    is not package-specific (e.g., 'Description of Project').
    """
    text_lower = heading_text.lower()
    for keyword, package in HEADING_TO_PACKAGE.items():
        if keyword in text_lower:
            return package
    return None


def find_heading1_sections(content):
    """Find all Heading1 paragraphs and their byte positions in document.xml.

    Returns a list of dicts:
        {
            'start': byte offset of the <w:p> opening tag,
            'end': byte offset after </w:p> closing tag,
            'text': extracted text from the heading,
            'package': identified package or None
        }

    The "section" owned by a Heading1 runs from that heading's <w:p> start
    through (but not including) the next Heading1's <w:p> start.
    """
    # Find all paragraphs
    para_pattern = re.compile(r'<w:p\b[^>]*>(.*?)</w:p>', re.DOTALL)

    headings = []
    for m in para_pattern.finditer(content):
        body = m.group(1)

        # Check if this paragraph has Heading1 style
        style_match = re.search(r'<w:pStyle\s+w:val="Heading1"', body)
        if not style_match:
            continue

        # Extract text
        text = ''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', body))
        if not text.strip():
            continue

        package = identify_package_from_heading(text)
        headings.append({
            'start': m.start(),
            'end': m.end(),
            'text': text.strip(),
            'package': package,
        })

    return headings


def delete_sections_tracked(content, headings, target_packages):
    """Wrap non-target package sections in w:del tracked-change markup.

    A "section" is everything from a Heading1's start position to the next
    Heading1's start position (or end of <w:body> if it's the last heading).

    Only sections with an identified package that is NOT in target_packages
    are deleted. Sections with no package (e.g., "Summary") are left alone.

    Returns (modified_content, count_of_deleted_sections).
    """
    if not headings:
        return content, 0

    # Find the end of <w:body> content (before </w:body> or </w:document>)
    body_end_match = re.search(r'</w:body>', content)
    body_end = body_end_match.start() if body_end_match else len(content)

    # Build list of sections to delete (in reverse order for safe splicing)
    sections_to_delete = []

    for i, heading in enumerate(headings):
        # Skip if not a package section or if it's a target package
        if heading['package'] is None:
            continue
        if heading['package'] in target_packages:
            continue

        # Section runs from this heading's start to the next heading's start
        section_start = heading['start']
        if i + 1 < len(headings):
            section_end = headings[i + 1]['start']
        else:
            # Last heading — section runs to end of body
            section_end = body_end

        sections_to_delete.append({
            'start': section_start,
            'end': section_end,
            'heading_text': heading['text'],
            'package': heading['package'],
        })

    if not sections_to_delete:
        return content, 0

    # Get starting ID above any existing tracked changes
    change_id = find_max_id(content) + 100

    # Apply deletions in reverse order (preserves earlier offsets)
    deleted_count = 0
    for section in reversed(sections_to_delete):
        section_xml = content[section['start']:section['end']]

        # Instead of wrapping the entire section in one w:del (which produces
        # invalid XML because w:del cannot contain block-level elements like
        # w:p or w:tbl), we wrap the runs inside each paragraph with w:del,
        # and mark each paragraph as a deleted paragraph via w:rPr + w:del on
        # the paragraph mark (pPr). This is how Word represents tracked
        # deletions of entire paragraphs.
        #
        # Strategy: wrap each <w:r>...</w:r> in <w:del> and add a
        # <w:pPr><w:rPr><w:del .../></w:rPr></w:pPr> to signal paragraph
        # deletion (paragraph mark deletion). For tables, we wrap runs inside
        # table cells similarly.

        def wrap_runs_in_del(xml_fragment, start_id):
            """Wrap all w:r elements in w:del and mark paragraph deletions."""
            result = []
            pos = 0
            cur_id = start_id

            # Process paragraph by paragraph — handle both <w:p> and <w:tbl>
            # For paragraphs: wrap all <w:r> in <w:del> and add delParagraph mark
            # For tables: wrap all <w:r> within table cells

            # Find all <w:r>...</w:r> and wrap each in w:del
            run_pattern = re.compile(r'<w:r\b[^>]*>.*?</w:r>', re.DOTALL)

            for m in run_pattern.finditer(xml_fragment):
                # Add content before this run unchanged
                result.append(xml_fragment[pos:m.start()])
                # Wrap the run in w:del
                result.append(
                    f'<w:del w:id="{cur_id}" w:author="{AUTHOR}" w:date="{TODAY}">'
                )
                result.append(m.group(0))
                result.append('</w:del>')
                cur_id += 1
                pos = m.end()

            # Add remaining content
            result.append(xml_fragment[pos:])

            # Now mark paragraph deletions: insert w:del paragraph mark
            # after each <w:pPr>...</w:pPr> (or create one if absent)
            para_result = ''.join(result)

            # For each <w:p ...>...</w:p>, add a paragraph-deletion run
            # (w:r with w:rPr/w:del) before </w:p> — this is the paragraph mark
            def add_para_del_mark(para_match):
                nonlocal cur_id
                para_xml = para_match.group(0)
                outer_id = cur_id
                inner_id = cur_id + 1
                cur_id += 2
                del_mark = (
                    f'<w:del w:id="{outer_id}" w:author="{AUTHOR}" w:date="{TODAY}">'
                    f'<w:r><w:rPr><w:del w:id="{inner_id}" w:author="{AUTHOR}" '
                    f'w:date="{TODAY}"/></w:rPr></w:r></w:del>'
                )
                # Insert before the closing </w:p>
                return para_xml[:-len('</w:p>')] + del_mark + '</w:p>'

            para_pattern = re.compile(r'<w:p\b[^>]*>.*?</w:p>', re.DOTALL)
            final_result = para_pattern.sub(add_para_del_mark, para_result)

            # Mark table rows for deletion: insert <w:del> into each <w:trPr>
            # (or create <w:trPr><w:del.../></w:trPr> if none exists).
            # This tells Word to remove the entire row when accepting changes.
            def add_row_del_mark(tr_match):
                nonlocal cur_id
                tr_xml = tr_match.group(0)
                del_attr = (
                    f'<w:del w:id="{cur_id}" w:author="{AUTHOR}" '
                    f'w:date="{TODAY}"/>'
                )
                cur_id += 1

                # Check if <w:trPr> already exists
                trpr_match = re.search(r'<w:trPr>(.*?)</w:trPr>', tr_xml, re.DOTALL)
                if trpr_match:
                    # Insert w:del inside existing trPr
                    insert_pos = trpr_match.end() - len('</w:trPr>')
                    return tr_xml[:insert_pos] + del_attr + tr_xml[insert_pos:]
                else:
                    # Create trPr after <w:tr...>
                    tr_open_end = tr_xml.find('>') + 1
                    return (tr_xml[:tr_open_end] +
                            f'<w:trPr>{del_attr}</w:trPr>' +
                            tr_xml[tr_open_end:])

            tr_pattern = re.compile(r'<w:tr\b[^>]*>.*?</w:tr>', re.DOTALL)
            final_result = tr_pattern.sub(add_row_del_mark, final_result)

            return final_result, cur_id

        wrapped, change_id = wrap_runs_in_del(section_xml, change_id)

        content = content[:section['start']] + wrapped + content[section['end']:]
        deleted_count += 1

    return content, deleted_count


def main():
    parser = argparse.ArgumentParser(
        description='Delete non-target package sections from DIR report with tracked changes'
    )
    parser.add_argument('working_dir', help='Directory containing DIR_Form_*_DRAFT.docx')
    parser.add_argument('--packages', required=True,
                        help='Comma-separated target packages to KEEP (e.g., "HDPE (125cc)")')
    parser.add_argument('--xml-dir', default=None,
                        help='Pre-unpacked XML directory (skip unpack/repack)')
    args = parser.parse_args()

    target_packages = [p.strip() for p in args.packages.split(',')]
    target_packages = normalize_target_packages(target_packages)
    print(f"Target packages to keep: {target_packages}")
    print(f"All other package sections will be marked for deletion.")

    if args.xml_dir:
        # Orchestrated mode: work on pre-unpacked XML
        doc_xml_path = os.path.join(args.xml_dir, 'word', 'document.xml')

        with open(doc_xml_path, 'r', encoding='utf-8') as f:
            content = f.read()

        headings = find_heading1_sections(content)
        print(f"\nFound {len(headings)} Heading1 sections:")
        for h in headings:
            status = '✓ KEEP' if (h['package'] is None or h['package'] in target_packages) else '✗ DELETE'
            pkg_label = h['package'] or '(no package)'
            print(f"  {status} [{pkg_label}] {h['text'][:80]}")

        new_content, deleted_count = delete_sections_tracked(content, headings, target_packages)

        if deleted_count == 0:
            print("\nNo sections to delete.")
        else:
            with open(doc_xml_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"\nDeleted {deleted_count} section(s) with tracked changes")

    else:
        # Standalone mode: find DRAFT, unpack, modify, repack
        import subprocess

        pattern = os.path.join(args.working_dir, 'DIR_Form_*_DRAFT.docx')
        matches = glob.glob(pattern)
        if not matches:
            print(f"ERROR: No DIR_Form_*_DRAFT.docx found in {args.working_dir}", file=sys.stderr)
            sys.exit(1)

        docx_path = matches[0]
        print(f"Processing: {os.path.basename(docx_path)}")

        xml_dir = tempfile.mkdtemp(prefix='del_pkg_')
        try:
            # Unpack
            result = subprocess.run(
                [sys.executable, UNPACK_SCRIPT, docx_path, xml_dir, '--no-indent'],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                print(f"ERROR unpacking: {result.stderr[:200]}", file=sys.stderr)
                sys.exit(1)

            doc_xml_path = os.path.join(xml_dir, 'word', 'document.xml')
            with open(doc_xml_path, 'r', encoding='utf-8') as f:
                content = f.read()

            headings = find_heading1_sections(content)
            print(f"\nFound {len(headings)} Heading1 sections:")
            for h in headings:
                status = '✓ KEEP' if (h['package'] is None or h['package'] in target_packages) else '✗ DELETE'
                pkg_label = h['package'] or '(no package)'
                print(f"  {status} [{pkg_label}] {h['text'][:80]}")

            new_content, deleted_count = delete_sections_tracked(content, headings, target_packages)

            if deleted_count == 0:
                print("\nNo sections to delete.")
            else:
                with open(doc_xml_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)

                # Repack
                result = subprocess.run(
                    [sys.executable, PACK_SCRIPT, xml_dir, docx_path, '--validate', 'false'],
                    capture_output=True, text=True, timeout=60
                )
                if result.returncode != 0:
                    print(f"ERROR repacking: {result.stderr[:200]}", file=sys.stderr)
                    sys.exit(1)

                print(f"\nDeleted {deleted_count} section(s) with tracked changes")
                print(f"Updated: {os.path.basename(docx_path)}")

        finally:
            shutil.rmtree(xml_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
