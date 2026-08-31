#!/usr/bin/env python3
# Version: 1.01 - Added \s* whitespace tolerance for pretty-printed XML
"""Update timepoint text references in a DIR report.

Replaces written-out and numeric forms of the old timepoint with the new one.
E.g., when going from 12M to 18M:
  "Twelve Month" → "Eighteen Month"
  "twelve months" → "eighteen months"
  "12 months" → "18 months"
  "12 month" → "18 month"

Uses tracked changes (del/ins markup).

Usage:
    python update_timepoint_text.py <working_dir> --old-timepoint 12M --new-timepoint 18M
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

# Import shared XML escape utility
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared_utils import xml_escape, find_max_id


TODAY = date.today().strftime('%Y-%m-%dT00:00:00Z')
AUTHOR = 'Claude'

_next_id = 6000

NUMBER_WORDS = {
    1: 'One', 2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five',
    6: 'Six', 7: 'Seven', 8: 'Eight', 9: 'Nine', 10: 'Ten',
    11: 'Eleven', 12: 'Twelve', 13: 'Thirteen', 14: 'Fourteen',
    15: 'Fifteen', 16: 'Sixteen', 17: 'Seventeen', 18: 'Eighteen',
    19: 'Nineteen', 20: 'Twenty', 21: 'Twenty-One', 22: 'Twenty-Two',
    23: 'Twenty-Three', 24: 'Twenty-Four', 25: 'Twenty-Five',
    26: 'Twenty-Six', 27: 'Twenty-Seven', 28: 'Twenty-Eight',
    29: 'Twenty-Nine', 30: 'Thirty', 36: 'Thirty-Six',
    42: 'Forty-Two', 48: 'Forty-Eight', 60: 'Sixty',
}


def get_next_ids(count=2):
    global _next_id
    ids = list(range(_next_id, _next_id + count))
    _next_id += count
    return ids


def make_tracked_replacement(old_text, new_text, rpr_xml=''):
    """Create del/ins tracked change XML."""
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


def build_replacements(old_months, new_months):
    """Build list of (old_text, new_text) pairs for all case variants."""
    old_word = NUMBER_WORDS.get(old_months)
    new_word = NUMBER_WORDS.get(new_months)

    replacements = []

    if old_word and new_word:
        # Title case: "Twelve Month" → "Eighteen Month"
        replacements.append((f'{old_word} Month', f'{new_word} Month'))
        # Title case plural: "Twelve Months" → "Eighteen Months"
        replacements.append((f'{old_word} Months', f'{new_word} Months'))
        # Lowercase: "twelve month" → "eighteen month"
        replacements.append((f'{old_word.lower()} month', f'{new_word.lower()} month'))
        # Lowercase plural: "twelve months" → "eighteen months"
        replacements.append((f'{old_word.lower()} months', f'{new_word.lower()} months'))
        # Sentence case (first word): "Twelve month" → "Eighteen month"
        replacements.append((f'{old_word} month', f'{new_word} month'))

    # Numeric: "12 months" → "18 months"
    replacements.append((f'{old_months} months', f'{new_months} months'))
    # Numeric singular: "12 month" → "18 month"
    replacements.append((f'{old_months} month', f'{new_months} month'))
    # Numeric with hyphen: "12-month" → "18-month"
    replacements.append((f'{old_months}-month', f'{new_months}-month'))
    replacements.append((f'{old_months}-Month', f'{new_months}-Month'))

    return replacements


def replace_timepoint_in_run(content, old_text, new_text):
    """Find <w:r> elements containing old_text and replace with tracked changes."""
    # Match a run containing the target text
    escaped = re.escape(old_text)
    run_pattern = re.compile(
        r'(<w:r(?:\s[^>]*)?>)\s*'                       # run start + whitespace tolerance
        r'((?:<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?)\s*' # optional rPr + whitespace tolerance
        r'((?:<w:[^/]*/>)*)\s*'                         # optional self-closing elements + whitespace tolerance
        r'(<w:t[^>]*>)'                                 # <w:t> open
        r'([^<]*' + escaped + r'[^<]*)'                 # text containing target
        r'(</w:t>)\s*'                                  # </w:t> + whitespace tolerance
        r'(</w:r>)',                                    # </w:r>
        re.DOTALL
    )

    count = 0

    def replace_match(match):
        nonlocal count
        run_open = match.group(1)
        rpr = match.group(2)
        self_closing = match.group(3)
        wt_open = match.group(4)
        text_content = match.group(5)
        wt_close = match.group(6)
        run_close = match.group(7)

        # Replace the target text within the full text content
        new_full_text = text_content.replace(old_text, new_text)
        if new_full_text == text_content:
            return match.group(0)

        count += 1
        return make_tracked_replacement(text_content, new_full_text, rpr)

    result = run_pattern.sub(replace_match, content)
    return result, count


def replace_timepoint_text(content, old_months, new_months):
    """Replace all timepoint text variants with tracked changes."""
    replacements = build_replacements(old_months, new_months)
    total_count = 0

    for old_text, new_text in replacements:
        if old_text in content:
            content, count = replace_timepoint_in_run(content, old_text, new_text)
            if count > 0:
                total_count += count
                print(f"    \"{old_text}\" → \"{new_text}\" ({count})")

    return content, total_count


def main():
    parser = argparse.ArgumentParser(description='Update timepoint text in DIR report')
    parser.add_argument('working_dir', help='Directory containing DIR_Form_*_DRAFT.docx')
    parser.add_argument('--old-timepoint', required=True,
                       help='Old timepoint (e.g., "12M")')
    parser.add_argument('--new-timepoint', required=True,
                       help='New timepoint (e.g., "18M")')
    parser.add_argument('--xml-dir', default=None,
                       help='Pre-unpacked XML directory (skip unpack/repack)')
    args = parser.parse_args()

    # Parse numeric months
    old_match = re.match(r'(\d+)M', args.old_timepoint)
    new_match = re.match(r'(\d+)M', args.new_timepoint)
    if not old_match or not new_match:
        print("ERROR: Timepoints must be in format like '12M', '18M'", file=sys.stderr)
        sys.exit(1)

    old_months = int(old_match.group(1))
    new_months = int(new_match.group(1))

    if args.xml_dir:
        doc_xml_path = os.path.join(args.xml_dir, 'word', 'document.xml')
        print(f"Updating timepoint text in: {os.path.basename(args.working_dir)} (pre-unpacked)")
        print(f"Timepoint: {args.old_timepoint} → {args.new_timepoint}")
        print(f"  Replacements:")

        with open(doc_xml_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Set ID counter above any existing tracked changes
        global _next_id
        _next_id = find_max_id(content) + 100

        new_content, count = replace_timepoint_text(content, old_months, new_months)

        if count == 0:
            print("  No timepoint text found to update.")
        else:
            print(f"  Total: {count} replacement(s)")
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
    print(f"Updating timepoint text in: {os.path.basename(docx_path)}")
    print(f"Timepoint: {args.old_timepoint} → {args.new_timepoint}")
    print(f"  Replacements:")

    tmp_dir = tempfile.mkdtemp(prefix='timepoint_text_')
    try:
        with zipfile.ZipFile(docx_path, 'r') as zf:
            zf.extractall(tmp_dir)

        doc_xml_path = os.path.join(tmp_dir, 'word', 'document.xml')
        with open(doc_xml_path, 'r', encoding='utf-8') as f:
            content = f.read()

        new_content, count = replace_timepoint_text(content, old_months, new_months)

        if count == 0:
            print("  No timepoint text found to update.")
        else:
            print(f"  Total: {count} replacement(s)")

            with open(doc_xml_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            with zipfile.ZipFile(docx_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(tmp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, tmp_dir)
                        zf.write(file_path, arcname)

            print(f"Updated: {os.path.basename(docx_path)}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
