#!/usr/bin/env python3
# Version: 1.01 - Added \s* whitespace tolerance for pretty-printed XML
"""Extract data hashes from DIR_Pkg and stab_package, update DIR draft with tracked changes.

Usage:
    python update_hash.py [project_folder]

If project_folder is not provided, uses current working directory.
Discovers all files by pattern matching — no hardcoded paths.
"""

import glob
import os
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import date
from xml.etree import ElementTree as ET

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W = NS['w']
AUTHOR = "Claude"
TODAY = date.today().isoformat()


def find_zip(folder, pattern):
    """Find zip file matching pattern. If multiple, pick latest timestamp."""
    matches = glob.glob(os.path.join(folder, pattern))
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    # Multiple: sort by timestamp in filename (last numeric segment before .zip)
    def extract_ts(path):
        nums = re.findall(r'(\d{14})', os.path.basename(path))
        return nums[-1] if nums else '0'
    return sorted(matches, key=extract_ts)[-1]


def extract_hash_from_docx_xml(docx_path, pattern):
    """Extract hash from a .docx file by parsing its document.xml.

    Also searches embedded .docx files (word/file*.docx) which Word renders
    inline as part of the visible document content.
    """
    with tempfile.TemporaryDirectory(prefix='hash_extract_') as tmp:
        with zipfile.ZipFile(docx_path, 'r') as zf:
            zf.extractall(tmp)

            # First: search main document.xml
            doc_xml = os.path.join(tmp, 'word', 'document.xml')
            if os.path.exists(doc_xml):
                tree = ET.parse(doc_xml)
                root = tree.getroot()
                body = root.find(f'.//{{{W}}}body')

                for p in body.iter(f'{{{W}}}p'):
                    text = ''.join(t.text or '' for t in p.iter(f'{{{W}}}t'))
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        return match.group(1)

            # Fallback: search embedded docx files (word/file*.docx)
            embedded = [n for n in zf.namelist()
                        if n.startswith('word/file') and n.endswith('.docx')]
            for name in embedded:
                data = zf.read(name)
                try:
                    inner_tmp = tempfile.mkdtemp(prefix='embed_')
                    inner_path = os.path.join(inner_tmp, 'inner.docx')
                    with open(inner_path, 'wb') as f:
                        f.write(data)
                    with zipfile.ZipFile(inner_path, 'r') as inner_zf:
                        if 'word/document.xml' in inner_zf.namelist():
                            inner_xml = inner_zf.read('word/document.xml')
                            inner_root = ET.fromstring(inner_xml)
                            for p in inner_root.iter(f'{{{W}}}p'):
                                text = ''.join(
                                    t.text or '' for t in p.iter(f'{{{W}}}t'))
                                match = re.search(pattern, text, re.IGNORECASE)
                                if match:
                                    shutil.rmtree(inner_tmp, ignore_errors=True)
                                    return match.group(1)
                    shutil.rmtree(inner_tmp, ignore_errors=True)
                except (zipfile.BadZipFile, ET.ParseError):
                    pass

        return None
    return None


def find_old_hash_in_dir(doc_xml_content):
    """Find existing 32-char hex hash values near 'Hash' text in DIR XML."""
    # Parse to find hash values via element tree
    tmp = tempfile.mkdtemp(prefix='dir_parse_')
    doc_path = os.path.join(tmp, 'doc.xml')
    with open(doc_path, 'w', encoding='utf-8') as f:
        f.write(doc_xml_content)

    tree = ET.parse(doc_path)
    root = tree.getroot()
    body = root.find(f'.//{{{W}}}body')
    shutil.rmtree(tmp, ignore_errors=True)

    hashes = set()
    for p in body.iter(f'{{{W}}}p'):
        text = ''.join(t.text or '' for t in p.iter(f'{{{W}}}t'))
        if 'hash' in text.lower():
            found = re.findall(r'[0-9a-fA-F]{32}', text)
            hashes.update(found)

    return hashes


def replace_hash_tracked(content, old_hash, new_hash):
    """Replace all occurrences of old_hash with tracked changes in XML content.

    Uses regex to find <w:r ...><w:rPr>...</w:rPr><w:t...>OLD_HASH</w:t></w:r>
    and replaces the entire run with del+ins tracked change markup.
    """
    next_id = 2000
    count = 0

    # Pattern: a <w:r> element containing the hash in its <w:t>
    # Captures: (1) full run opening tag, (2) rPr content if present, (3) t tag attrs
    # NOTE: rPr uses negative lookahead (?:(?!</w:rPr>).)* to prevent catastrophic
    # backtracking — without it, .*? can expand across 100KB+ of unrelated content
    run_pattern = re.compile(
        r'(<w:r(?:\s[^>]*)?>)\s*'                      # group 1: <w:r> or <w:r attrs> + whitespace
        r'((?:<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?)\s*' # group 2: optional rPr (bounded) + whitespace
        r'<w:t([^>]*)>'                                 # group 3: <w:t> attributes
        + re.escape(old_hash) +                         # literal hash
        r'</w:t>\s*</w:r>',                             # closing tags with whitespace tolerance
        re.DOTALL
    )

    def make_tracked_change(m):
        nonlocal next_id, count
        rpr_xml = m.group(2)  # existing rPr (may be empty string)

        if not rpr_xml:
            rpr_xml = ''

        del_id = next_id
        ins_id = next_id + 1
        next_id += 2
        count += 1

        return (
            f'<w:del w:id="{del_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
            f'<w:r>{rpr_xml}<w:delText>{old_hash}</w:delText></w:r>'
            f'</w:del>'
            f'<w:ins w:id="{ins_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
            f'<w:r>{rpr_xml}<w:t>{new_hash}</w:t></w:r>'
            f'</w:ins>'
        )

    content = run_pattern.sub(make_tracked_change, content)

    # Fallback: if hash appears in <w:t> that also contains other text
    # (e.g., "Data Hash: abc123..." all in one <w:t>)
    if old_hash in content:
        mixed_pattern = re.compile(
            r'(<w:r(?:\s[^>]*)?>)\s*'
            r'((?:<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?)\s*'
            r'<w:t([^>]*)>([^<]*?' + re.escape(old_hash) + r'[^<]*?)</w:t>\s*</w:r>',
            re.DOTALL
        )

        def make_split_change(m):
            nonlocal next_id, count
            rpr_xml = m.group(2)
            t_attrs = m.group(3)
            full_text = m.group(4)

            if not rpr_xml:
                rpr_xml = ''

            before = full_text[:full_text.find(old_hash)]
            after = full_text[full_text.find(old_hash) + len(old_hash):]

            del_id = next_id
            ins_id = next_id + 1
            next_id += 2
            count += 1

            parts = []
            if before:
                parts.append(f'<w:r>{rpr_xml}<w:t xml:space="preserve">{before}</w:t></w:r>')
            parts.append(
                f'<w:del w:id="{del_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
                f'<w:r>{rpr_xml}<w:delText>{old_hash}</w:delText></w:r>'
                f'</w:del>'
                f'<w:ins w:id="{ins_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
                f'<w:r>{rpr_xml}<w:t>{new_hash}</w:t></w:r>'
                f'</w:ins>'
            )
            if after:
                parts.append(f'<w:r>{rpr_xml}<w:t xml:space="preserve">{after}</w:t></w:r>')

            return ''.join(parts)

        content = mixed_pattern.sub(make_split_change, content)

    return content, count


def main():
    import argparse as _argparse
    parser = _argparse.ArgumentParser(description='Update data hashes in DIR draft')
    parser.add_argument('folder', nargs='?', default=os.getcwd(),
                        help='Project folder (default: current directory)')
    parser.add_argument('--xml-dir', default=None,
                        help='Pre-unpacked XML directory (skip draft unpack/repack)')
    _args = parser.parse_args()

    folder = os.path.abspath(_args.folder)
    print(f"Project folder: {folder}")

    # Step 1: Find draft copy
    draft_matches = glob.glob(os.path.join(folder, 'DIR_Form_*_DRAFT.docx'))
    if not draft_matches:
        print("ERROR: No DIR_Form_*_DRAFT.docx found")
        sys.exit(1)
    draft_path = draft_matches[0]
    print(f"Draft DIR: {os.path.basename(draft_path)}")

    # Step 1: Find ZIP files
    dir_pkg_zip = find_zip(folder, 'DIR_[Pp]kg_*.zip')
    if not dir_pkg_zip:
        # Also check for DIR_Pkg pattern
        dir_pkg_zip = find_zip(folder, 'DIR_Pkg_*.zip')
    if not dir_pkg_zip:
        print("ERROR: No DIR_Pkg_*.zip found in project folder")
        sys.exit(1)
    print(f"DIR_Pkg zip: {os.path.basename(dir_pkg_zip)}")

    stab_zip = find_zip(folder, 'stab_package_*.zip')
    if not stab_zip:
        print("ERROR: No stab_package_*.zip found in project folder")
        sys.exit(1)
    print(f"stab_package zip: {os.path.basename(stab_zip)}")

    # Unzip both
    dir_pkg_td = tempfile.TemporaryDirectory(prefix='dir_pkg_')
    stab_td = tempfile.TemporaryDirectory(prefix='stab_pkg_')
    dir_pkg_tmp = dir_pkg_td.name
    stab_tmp = stab_td.name

    with zipfile.ZipFile(dir_pkg_zip, 'r') as zf:
        zf.extractall(dir_pkg_tmp)
    with zipfile.ZipFile(stab_zip, 'r') as zf:
        zf.extractall(stab_tmp)

    # Step 2: Extract hash from DIR_Pkg
    dir_pkg_docx = glob.glob(os.path.join(dir_pkg_tmp, 'DIR_[Pp]kg*.docx'))
    if not dir_pkg_docx:
        dir_pkg_docx = glob.glob(os.path.join(dir_pkg_tmp, '*.docx'))
    if not dir_pkg_docx:
        print(f"ERROR: No .docx found in DIR_Pkg zip. Contents: {os.listdir(dir_pkg_tmp)}")
        sys.exit(1)

    hash1 = extract_hash_from_docx_xml(
        dir_pkg_docx[0],
        r'(?:Final\s+)?(?:Data(?:set)?)\s*Hash[:\s]+([0-9a-fA-F]{32})'
    )
    if not hash1:
        print("ERROR: No 'Final Dataset Hash' found in DIR_Pkg docx")
        sys.exit(1)
    print(f"\nhash1 (DIR_Pkg):      {hash1}")

    # Step 3: Extract hash from stability_plots
    stab_plots = glob.glob(os.path.join(stab_tmp, 'stability_plots.docx'))
    if not stab_plots:
        stab_plots = glob.glob(os.path.join(stab_tmp, '*.docx'))
    if not stab_plots:
        print(f"ERROR: No .docx found in stab_package. Contents: {os.listdir(stab_tmp)}")
        sys.exit(1)

    hash2 = extract_hash_from_docx_xml(
        stab_plots[0],
        r'Data\s+Hash[:\s]+([0-9a-fA-F]{32})'
    )
    if not hash2:
        print("ERROR: No 'Data Hash' found in stability_plots.docx")
        sys.exit(1)
    print(f"hash2 (stab_package): {hash2}")

    # Preserve files for later skills
    preserved = []
    for filename in ['stability_plots.docx', 'stability_plot_data.xlsx',
                     'Stability_plot_data.xlsx', 'stability_plot_settings.xlsx']:
        src = os.path.join(stab_tmp, filename)
        if os.path.exists(src):
            dst = os.path.join(folder, filename)
            shutil.copy2(src, dst)
            preserved.append(filename)

    # Step 6: Verify match
    match_status = hash1 == hash2
    if match_status:
        print(f"\n✓ Hashes MATCH")
    else:
        print(f"\n✗ Hashes DO NOT MATCH — verify data integrity!")

    new_hash = hash1  # Use DIR_Pkg hash as authoritative

    # Step 4-5: Update draft DIR
    if _args.xml_dir:
        doc_xml_path = os.path.join(_args.xml_dir, 'word', 'document.xml')
        draft_td = None
    else:
        draft_td = tempfile.TemporaryDirectory(prefix='draft_')
        with zipfile.ZipFile(draft_path, 'r') as zf:
            zf.extractall(draft_td.name)
        doc_xml_path = os.path.join(draft_td.name, 'word', 'document.xml')

    with open(doc_xml_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find old hash
    old_hashes = find_old_hash_in_dir(content)
    if not old_hashes:
        print("\nWARNING: No existing hash values found in DIR — nothing to update")
        dir_pkg_td.cleanup()
        stab_td.cleanup()
        if draft_td:
            draft_td.cleanup()
        return

    if len(old_hashes) > 1:
        print(f"\nWARNING: Multiple distinct hashes in DIR: {old_hashes}")

    old_hash = old_hashes.pop()
    print(f"Old hash in DIR:      {old_hash}")

    if old_hash == new_hash:
        print("\nINFO: Old hash equals new hash — no update needed")
    else:
        content, count = replace_hash_tracked(content, old_hash, new_hash)
        print(f"\nUpdated {count} hash occurrences with tracked changes")

        with open(doc_xml_path, 'w', encoding='utf-8') as f:
            f.write(content)

        # Repack only in standalone mode
        if not _args.xml_dir:
            with zipfile.ZipFile(draft_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root_dir, dirs, files in os.walk(draft_td.name):
                    for file in files:
                        file_path = os.path.join(root_dir, file)
                        arc_name = os.path.relpath(file_path, draft_td.name)
                        zf.write(file_path, arc_name)

    # Step 7: Cleanup
    dir_pkg_td.cleanup()
    stab_td.cleanup()
    if draft_td:
        draft_td.cleanup()

    # Summary
    print(f"\n{'='*50}")
    print(f"Data Hash Update Summary:")
    print(f"  hash1 (DIR_Pkg):      {hash1}")
    print(f"  hash2 (stab_package): {hash2}")
    print(f"  Match status:         {'✓ Match' if match_status else '✗ MISMATCH'}")
    print(f"  Old hash:             {old_hash}")
    print(f"  New hash:             {new_hash}")
    if old_hash != new_hash:
        print(f"  Occurrences updated:  {count}")
    print(f"  Files preserved:      {', '.join(preserved)}")


if __name__ == '__main__':
    main()
