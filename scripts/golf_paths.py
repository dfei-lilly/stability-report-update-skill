#!/usr/bin/env python3
# Version: 1.01 - Fixed whitespace between XML tags, space-after-backslash, and Strategy 2 gating
"""Update golf:\\golf.grp\\CMC_STATS\\ folder path references in a DIR report.

Finds all occurrences of golf:\\golf.grp\\CMC_STATS\\<folder_name> in the
document XML and replaces the folder name portion with the current vendor
folder name, using tracked changes (del/ins markup).

Usage:
    python update_golf_paths.py <working_dir> --new-folder-name <name>
"""

import argparse
import glob
import os
import re
import sys
import tempfile
import zipfile
from datetime import date

# Import shared XML escape utility
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared_utils import xml_escape, find_max_id


GOLF_PREFIX = r'golf:\\golf\.grp\\CMC_STATS\\'
TODAY = date.today().strftime('%Y-%m-%dT00:00:00Z')
AUTHOR = 'Claude'

_next_id = 5000


def get_next_ids(count=2):
    global _next_id
    ids = list(range(_next_id, _next_id + count))
    _next_id += count
    return ids


def make_tracked_replacement(old_text, new_text, rpr_xml=''):
    """Create del/ins tracked change XML for a text replacement."""
    del_id, ins_id = get_next_ids(2)

    del_xml = (
        f'<w:del w:id="{del_id}" w:author="{AUTHOR}" w:date="{TODAY}">'
        f'<w:r>{rpr_xml}<w:delText xml:space="preserve">{xml_escape(old_text)}</w:delText></w:r>'
        f'</w:del>'
    )
    ins_xml = (
        f'<w:ins w:id="{ins_id}" w:author="{AUTHOR}" w:date="{TODAY}">'
        f'<w:r>{rpr_xml}<w:t xml:space="preserve">{xml_escape(new_text)}</w:t></w:r>'
        f'</w:ins>'
    )
    return del_xml + ins_xml


def replace_golf_paths(content, new_folder_name):
    """Find and replace golf path folder names with tracked changes.

    Strategy 1: Find <w:r> runs containing a golf path, replace with tracked change.
    Strategy 2: Paragraph-level pass for remaining paths (split across runs or missed by Strategy 1).
    """
    count = 0

    # Strategy 1: run-level — golf path entirely within one <w:r>
    run_pattern = re.compile(
        r'(<w:r(?:\s[^>]*)?>)\s*'                          # run start tag + optional whitespace
        r'((?:<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?)\s*'    # optional rPr + optional whitespace
        r'((?:<w:[^/]*/>)*)\s*'                            # optional self-closing elements + optional whitespace
        r'(<w:t[^>]*>)'                                    # <w:t> open
        r'([^<]*golf:\\\\golf\.grp\\\\CMC_STATS\\\\[^<]*)' # text with golf path
        r'(</w:t>)\s*'                                     # </w:t> + optional whitespace
        r'(</w:r>)',                                       # </w:r>
        re.DOTALL
    )

    def replace_run(match):
        nonlocal count
        run_open = match.group(1)
        rpr = match.group(2)
        self_closing = match.group(3)
        wt_open = match.group(4)
        text_content = match.group(5)
        wt_close = match.group(6)
        run_close = match.group(7)

        # Find folder name in text (handle optional space after backslash)
        folder_re = re.compile(
            r'(golf:\\\\golf\.grp\\\\CMC_STATS\\\\)\s*'
            r'([^\s<(]+)'
        )
        folder_match = folder_re.search(text_content)
        if not folder_match:
            return match.group(0)

        old_folder = folder_match.group(2)
        if old_folder == new_folder_name:
            return match.group(0)

        # Build replacement: full old text → full new text with folder swapped
        old_full_text = text_content
        new_full_text = (text_content[:folder_match.start(2)] +
                        new_folder_name +
                        text_content[folder_match.end(2):])

        count += 1
        return make_tracked_replacement(old_full_text, new_full_text, rpr)

    result = run_pattern.sub(replace_run, content)

    # Strategy 2: paragraph-level pass for remaining paths (split across runs or missed by Strategy 1)
    # Try paragraph-level approach: join text from paragraph, find golf paths
    para_pattern = re.compile(r'(<w:p\b[^>]*>)(.*?)(</w:p>)', re.DOTALL)

    def check_paragraph(para_match):
        nonlocal count
        para_open = para_match.group(1)
        para_body = para_match.group(2)
        para_close = para_match.group(3)

        # Extract all text from runs in this paragraph
        text_parts = re.findall(r'<w:t[^>]*>([^<]*)</w:t>', para_body)
        full_text = ''.join(text_parts)

        if 'golf:\\golf.grp\\CMC_STATS\\' not in full_text:
            return para_match.group(0)

        # Found a split golf path — handle with full paragraph replacement
        folder_re = re.compile(
            r'(golf:\\golf\.grp\\CMC_STATS\\)\s*'
            r'([^\s<(]+)'
        )
        folder_match = folder_re.search(full_text)
        if not folder_match or folder_match.group(2) == new_folder_name:
            return para_match.group(0)

        old_folder = folder_match.group(2)
        new_full_text = full_text.replace(
            f'golf:\\golf.grp\\CMC_STATS\\ {old_folder}',
            f'golf:\\golf.grp\\CMC_STATS\\{new_folder_name}'
        ).replace(
            f'golf:\\golf.grp\\CMC_STATS\\{old_folder}',
            f'golf:\\golf.grp\\CMC_STATS\\{new_folder_name}'
        )

        # Get paragraph properties
        ppr_match = re.search(r'<w:pPr>.*?</w:pPr>', para_body, re.DOTALL)
        ppr = ppr_match.group(0) if ppr_match else ''

        # Get rPr from first run
        rpr_match = re.search(r'<w:rPr>(.*?)</w:rPr>', para_body, re.DOTALL)
        rpr = f'<w:rPr>{rpr_match.group(1)}</w:rPr>' if rpr_match else ''

        count += 1
        tracked = make_tracked_replacement(full_text, new_full_text, rpr)
        return f'{para_open}{ppr}{tracked}{para_close}'

    result = para_pattern.sub(check_paragraph, result)

    return result, count


def main():
    parser = argparse.ArgumentParser(description='Update golf path references in DIR report')
    parser.add_argument('working_dir', help='Directory containing DIR_Form_*_DRAFT.docx')
    parser.add_argument('--new-folder-name', required=True,
                       help='New vendor folder name to substitute into golf paths')
    parser.add_argument('--xml-dir', default=None,
                       help='Pre-unpacked XML directory (skip unpack/repack)')
    args = parser.parse_args()

    if args.xml_dir:
        doc_xml_path = os.path.join(args.xml_dir, 'word', 'document.xml')
        print(f"Updating golf paths in: {os.path.basename(args.working_dir)} (pre-unpacked)")
        print(f"New folder name: {args.new_folder_name}")

        with open(doc_xml_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Set ID counter above any existing tracked changes
        global _next_id
        _next_id = find_max_id(content) + 100

        new_content, count = replace_golf_paths(content, args.new_folder_name)

        if count == 0:
            print("No golf paths found to update.")
        else:
            print(f"Replaced {count} golf path reference(s)")
            with open(doc_xml_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Updated: {os.path.basename(args.working_dir)}")
        return

    # Standalone mode: find DRAFT, unpack, modify, repack
    pattern = os.path.join(args.working_dir, 'DIR_Form_*_DRAFT.docx')
    matches = glob.glob(pattern)
    if not matches:
        print(f"ERROR: No DIR_Form_*_DRAFT.docx found in {args.working_dir}", file=sys.stderr)
        sys.exit(1)

    docx_path = matches[0]
    print(f"Updating golf paths in: {os.path.basename(docx_path)}")
    print(f"New folder name: {args.new_folder_name}")

    with tempfile.TemporaryDirectory(prefix='golf_paths_') as tmp_dir:
        with zipfile.ZipFile(docx_path, 'r') as zf:
            zf.extractall(tmp_dir)

        doc_xml_path = os.path.join(tmp_dir, 'word', 'document.xml')
        with open(doc_xml_path, 'r', encoding='utf-8') as f:
            content = f.read()

        new_content, count = replace_golf_paths(content, args.new_folder_name)

        if count == 0:
            print("No golf paths found to update.")
        else:
            print(f"Replaced {count} golf path reference(s)")

            with open(doc_xml_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            with zipfile.ZipFile(docx_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(tmp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, tmp_dir)
                        zf.write(file_path, arcname)

            print(f"Updated: {os.path.basename(docx_path)}")


if __name__ == '__main__':
    main()
