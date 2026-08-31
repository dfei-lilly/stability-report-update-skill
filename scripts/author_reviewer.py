# Version: 1.01 - Added \s* whitespace tolerance for pretty-printed XML
#!/usr/bin/env python3
"""Update author and reviewer names/titles in a DIR draft with tracked changes.

Usage:
    python update_author_reviewer.py [project_folder] \
        --author "Name" --di-reviewer "Name" --tech-reviewer "Name"

If project_folder is not provided, uses current working directory.
Names in the personnel directory get title/org auto-filled.
"""

import argparse
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import date
from xml.etree import ElementTree as ET

# Import shared XML escape utility
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared_utils import xml_escape, find_max_id

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W = NS['w']
AUTHOR = "Claude"
TODAY = date.today().isoformat()

PERSONNEL = {
    # Under Jinxin Gao (Sr. Director)
    "Jinxin Gao": ("Sr. Director", "Development Statistics, 100AY57"),
    "Wenzhao Yang": ("Advisor", "Development Statistics, 100AY57"),
    "Adam Palmer Rauk": ("Director", "Development Statistics, 100AY57"),
    "Yueyun Zhang": ("Advisor", "Development Statistics, 100AY57"),
    "Max Xia": ("Sr. Statistician", "Development Statistics, 100AY57"),
    "Shu Zheng": ("Advisor", "Development Statistics, 100AY57"),
    # Under Brooke Marshall (Sr. Director)
    "Brooke Marshall": ("Sr. Director", "Development Statistics, 100AY57"),
    "Meng John Zhao": ("Director", "Development Statistics, 100AY57"),
    "Chad N. Wolfe": ("Director", "Development Statistics, 100AY57"),
    "Sam Gardner": ("Director", "Development Statistics, 100AY57"),
    "Dongling Fei": ("Sr. Principal Statistician", "Development Statistics, 100AY57"),
    # Under Aniruddha Deshmukh (Advisor)
    "Aniruddha Deshmukh": ("Advisor", "Statistics, Lilly Bengaluru"),
    "Jeevitha K M": ("Senior Statistician", "CMC Statistics, Lilly Bengaluru"),
    "Sakshi Shinde": ("Statistician", "CMC Statistics, Lilly Bengaluru"),
    "Jyothirmayi Alluvada": ("Senior Statistician", "CMC Statistics, Lilly Bengaluru"),
}

# Aliases for flexible matching (no middle initial, alternate spacing)
ALIASES = {
    "Chad Wolfe": "Chad N. Wolfe",
    "Chad N Wolfe": "Chad N. Wolfe",
    "Jeevitha KM": "Jeevitha K M",
    "Adam Rauk": "Adam Palmer Rauk",
    "Meng Zhao": "Meng John Zhao",
}

next_id = 3000


def get_next_ids():
    global next_id
    del_id = next_id
    ins_id = next_id + 1
    next_id += 2
    return del_id, ins_id


def lookup_personnel(name):
    """Look up name in directory. Handles aliases and case-insensitive matching."""
    # Direct match
    if name in PERSONNEL:
        title, org = PERSONNEL[name]
        return {'name': name, 'title': title, 'org': org}

    # Alias match
    if name in ALIASES:
        canonical = ALIASES[name]
        title, org = PERSONNEL[canonical]
        return {'name': canonical, 'title': title, 'org': org}

    # Case-insensitive match
    name_lower = name.lower()
    for known_name in PERSONNEL:
        if known_name.lower() == name_lower:
            title, org = PERSONNEL[known_name]
            return {'name': known_name, 'title': title, 'org': org}

    # Case-insensitive alias match
    for alias, canonical in ALIASES.items():
        if alias.lower() == name_lower:
            title, org = PERSONNEL[canonical]
            return {'name': canonical, 'title': title, 'org': org}

    # First-name match (if unique)
    first_name = name.split()[0].lower()
    matches = [k for k in PERSONNEL if k.split()[0].lower() == first_name]
    if len(matches) == 1:
        title, org = PERSONNEL[matches[0]]
        return {'name': matches[0], 'title': title, 'org': org}

    # Last-name match (if unique)
    last_name = name.split()[-1].lower()
    matches = [k for k in PERSONNEL if k.split()[-1].lower() == last_name]
    if len(matches) == 1:
        title, org = PERSONNEL[matches[0]]
        return {'name': matches[0], 'title': title, 'org': org}

    return None


def find_cover_author(body):
    """Find the cover page author paragraph (centered, near top)."""
    elem_idx = 0
    for elem in body:
        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if tag == 'p':
            if elem_idx > 20:
                break
            pPr = elem.find(f'{{{W}}}pPr')
            if pPr is not None:
                jc = pPr.find(f'{{{W}}}jc')
                if jc is not None and jc.get(f'{{{W}}}val') == 'center':
                    text = ''.join(t.text or '' for t in elem.iter(f'{{{W}}}t'))
                    text = text.strip()
                    if text and len(text) < 80 and not text.startswith('Eli Lilly'):
                        if any(c.isalpha() for c in text):
                            return elem, text
        elem_idx += 1
    return None, None


def find_review_tables(body):
    """Find first 3 tables (Author Review, DI Review, Tech Review)."""
    tables = []
    for elem in body:
        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if tag == 'tbl':
            tables.append(elem)
            if len(tables) >= 3:
                break
    return tables


def extract_table_info(table):
    """Extract name, title, org from a review table."""
    rows = list(table.iter(f'{{{W}}}tr'))
    if len(rows) < 2:
        return None

    # Row 0, Cell 0 = name
    row0_cells = list(rows[0].iter(f'{{{W}}}tc'))
    if not row0_cells:
        return None
    name = ''.join(t.text or '' for t in row0_cells[0].iter(f'{{{W}}}t')).strip()

    # Row 1, Cell 0 = title (para 0) + org (para 1)
    row1_cells = list(rows[1].iter(f'{{{W}}}tc'))
    if not row1_cells:
        return {'name': name, 'title': '', 'org': ''}

    cell = row1_cells[0]
    paras = list(cell.iter(f'{{{W}}}p'))
    title = ''
    org = ''
    if len(paras) >= 1:
        title = ''.join(t.text or '' for t in paras[0].iter(f'{{{W}}}t')).strip()
    if len(paras) >= 2:
        org = ''.join(t.text or '' for t in paras[1].iter(f'{{{W}}}t')).strip()

    return {'name': name, 'title': title, 'org': org}


def replace_text_tracked(content, old_text, new_text, start=0, end=None, max_count=0):
    """Replace text using tracked changes via regex on raw XML.

    Handles both single-run text and text split across multiple runs.

    Args:
        content: full XML string
        old_text: text to find and replace
        new_text: replacement text
        start: byte offset to start searching from
        end: byte offset to stop searching at (None = end of content)
        max_count: max replacements (0 = unlimited)

    Returns: (modified_content, replacement_count)
    """
    if not old_text or old_text == new_text:
        return content, 0

    if end is None:
        end = len(content)

    escaped = re.escape(old_text)
    count = 0

    # Strategy 1: Single-run match (with \s* for pretty-printed XML tolerance)
    run_pattern = re.compile(
        r'(<w:r(?:\s[^>]*)?>)\s*'
        r'((?:<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?)\s*'
        r'<w:t([^>]*)>' + escaped + r'</w:t>\s*</w:r>',
        re.DOTALL
    )

    def make_tracked_change(m):
        nonlocal count
        if m.start() < start or m.start() >= end:
            return m.group(0)
        if max_count and count >= max_count:
            return m.group(0)

        rpr_xml = m.group(2)
        del_id, ins_id = get_next_ids()

        if not rpr_xml:
            rpr_xml = ''

        count += 1
        return (
            f'<w:del w:id="{del_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
            f'<w:r>{rpr_xml}<w:delText>{xml_escape(old_text)}</w:delText></w:r>'
            f'</w:del>'
            f'<w:ins w:id="{ins_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
            f'<w:r>{rpr_xml}<w:t>{xml_escape(new_text)}</w:t></w:r>'
            f'</w:ins>'
        )

    content = run_pattern.sub(make_tracked_change, content)

    if count > 0:
        return content, count

    # Strategy 1b: Text is inside a run but with leading/trailing whitespace
    # (happens after merge-runs in unpack.py combines "Dongling Fei" + " " into "Dongling Fei ")
    run_pattern_partial = re.compile(
        r'(<w:r(?:\s[^>]*)?>)\s*'
        r'((?:<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?)\s*'
        r'<w:t([^>]*)>(\s*)' + escaped + r'(\s*)</w:t>\s*</w:r>',
        re.DOTALL
    )

    def make_tracked_change_partial(m):
        nonlocal count
        if m.start() < start or m.start() >= end:
            return m.group(0)
        if max_count and count >= max_count:
            return m.group(0)

        rpr_xml = m.group(2) or ''
        leading_ws = m.group(4)
        trailing_ws = m.group(5)

        # Only use this strategy if there's actual whitespace padding
        if not leading_ws and not trailing_ws:
            return m.group(0)

        del_id, ins_id = get_next_ids()
        count += 1

        # Build result: leading whitespace run + tracked del/ins + trailing whitespace run
        parts = []
        if leading_ws:
            parts.append(
                f'<w:r>{rpr_xml}<w:t xml:space="preserve">{leading_ws}</w:t></w:r>')
        parts.append(
            f'<w:del w:id="{del_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
            f'<w:r>{rpr_xml}<w:delText>{xml_escape(old_text)}</w:delText></w:r>'
            f'</w:del>'
            f'<w:ins w:id="{ins_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
            f'<w:r>{rpr_xml}<w:t>{xml_escape(new_text)}</w:t></w:r>'
            f'</w:ins>')
        if trailing_ws:
            parts.append(
                f'<w:r>{rpr_xml}<w:t xml:space="preserve">{trailing_ws}</w:t></w:r>')
        return ''.join(parts)

    content = run_pattern_partial.sub(make_tracked_change_partial, content)

    if count > 0:
        return content, count

    # Strategy 2: Paragraph-level replacement for text split across runs
    # Find <w:p> elements within the scoped region whose joined text matches
    para_pattern = re.compile(r'<w:p\b[^>]*>.*?</w:p>', re.DOTALL)
    t_pattern = re.compile(r'<w:t[^>]*>([^<]*)</w:t>')
    rpr_extract = re.compile(r'<w:rPr>((?:(?!</w:rPr>).)*)</w:rPr>', re.DOTALL)

    def replace_para(m):
        nonlocal count
        if m.start() < start or m.start() >= end:
            return m.group(0)
        if max_count and count >= max_count:
            return m.group(0)

        para_xml = m.group(0)
        para_text = ''.join(t_pattern.findall(para_xml))

        if para_text.strip() != old_text:
            return para_xml

        # Extract pPr (paragraph properties) to preserve
        ppr_match = re.search(r'(<w:pPr>.*?</w:pPr>)', para_xml, re.DOTALL)
        ppr_xml = ppr_match.group(1) if ppr_match else ''

        # Extract first rPr from runs for formatting
        rpr_match = rpr_extract.search(para_xml)
        rpr_xml = f'<w:rPr>{rpr_match.group(1)}</w:rPr>' if rpr_match else ''
        if not rpr_xml:
            rpr_xml = ''

        del_id, ins_id = get_next_ids()
        count += 1

        # Extract paragraph opening tag
        p_open_match = re.match(r'(<w:p\b[^>]*>)', para_xml)
        p_open = p_open_match.group(1) if p_open_match else '<w:p>'

        return (
            f'{p_open}{ppr_xml}'
            f'<w:del w:id="{del_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
            f'<w:r>{rpr_xml}<w:delText>{xml_escape(old_text)}</w:delText></w:r>'
            f'</w:del>'
            f'<w:ins w:id="{ins_id}" w:author="{AUTHOR}" w:date="{TODAY}T00:00:00Z">'
            f'<w:r>{rpr_xml}<w:t>{xml_escape(new_text)}</w:t></w:r>'
            f'</w:ins>'
            f'</w:p>'
        )

    content = para_pattern.sub(replace_para, content)

    return content, count


def find_table_boundaries(content):
    """Find byte positions of first 3 <w:tbl>...</w:tbl> in content."""
    boundaries = []
    search_from = 0
    for _ in range(3):
        tbl_start = content.find('<w:tbl', search_from)
        if tbl_start == -1:
            break
        tbl_end = content.find('</w:tbl>', tbl_start)
        if tbl_end == -1:
            break
        tbl_end += len('</w:tbl>')
        boundaries.append((tbl_start, tbl_end))
        search_from = tbl_end
    return boundaries


def find_cover_region_end(content):
    """Find the end of the cover page region (before first table)."""
    first_tbl = content.find('<w:tbl')
    if first_tbl == -1:
        return len(content)
    return first_tbl


def main():
    parser = argparse.ArgumentParser(description='Update author/reviewer in DIR draft')
    parser.add_argument('folder', nargs='?', default=os.getcwd(),
                        help='Project folder (default: current directory)')
    parser.add_argument('--author', help='New author name')
    parser.add_argument('--di-reviewer', help='New Data Integrity reviewer name')
    parser.add_argument('--tech-reviewer', help='New Technical reviewer name')
    parser.add_argument('--title', help='Title (if name not in directory)')
    parser.add_argument('--org', help='Organization (if name not in directory)')
    parser.add_argument('--xml-dir', default=None,
                        help='Pre-unpacked XML directory (skip unpack/repack)')
    parser.add_argument('--read-current', action='store_true',
                        help='Print current personnel as JSON and exit (no changes)')
    args = parser.parse_args()

    folder = os.path.abspath(args.folder)
    print(f"Project folder: {folder}")

    # --read-current: print current personnel as JSON and exit (no modifications)
    if args.read_current:
        draft_matches = glob.glob(os.path.join(folder, 'DIR_Form_*_DRAFT.docx'))
        draft_matches = [m for m in draft_matches
                         if not os.path.basename(m).startswith('~$')]
        if not draft_matches:
            print("ERROR: No DIR_Form_*_DRAFT.docx found")
            sys.exit(1)
        draft_path = draft_matches[0]

        tmp_dir = tempfile.mkdtemp(prefix='author_read_')
        try:
            with zipfile.ZipFile(draft_path, 'r') as zf:
                zf.extractall(tmp_dir)
            doc_xml_path = os.path.join(tmp_dir, 'word', 'document.xml')
            tree = ET.parse(doc_xml_path)
            root = tree.getroot()
            body = root.find(f'.//{{{W}}}body')

            _cover_elem, cover_author = find_cover_author(body)
            tables = find_review_tables(body)

            result = {
                "author": {"name": "", "title": "", "org": ""},
                "di_reviewer": {"name": "", "title": "", "org": ""},
                "tech_reviewer": {"name": "", "title": "", "org": ""},
            }
            labels = ['author', 'di_reviewer', 'tech_reviewer']
            for i, tbl in enumerate(tables[:3]):
                info = extract_table_info(tbl)
                if info:
                    result[labels[i]] = info

            # Use cover author name if author table name is empty
            if not result["author"]["name"] and cover_author:
                result["author"]["name"] = cover_author

            print("__CURRENT_PERSONNEL__")
            print(json.dumps(result, indent=2))
            print("__END_CURRENT_PERSONNEL__")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        sys.exit(0)

    if not args.author and not args.di_reviewer and not args.tech_reviewer:
        print("ERROR: Provide at least one of --author, --di-reviewer, --tech-reviewer")
        sys.exit(1)

    # Resolve personnel
    assignments = {}
    for role, name in [('author', args.author),
                       ('di_reviewer', args.di_reviewer),
                       ('tech_reviewer', args.tech_reviewer)]:
        if not name:
            continue
        info = lookup_personnel(name)
        if info:
            assignments[role] = info
            print(f"  {role}: {info['name']} — {info['title']}, {info['org']}")
        elif args.title and args.org:
            assignments[role] = {'name': name, 'title': args.title, 'org': args.org}
            print(f"  {role}: {name} — {args.title}, {args.org} (manual)")
        else:
            print(f"ERROR: '{name}' not in personnel directory.")
            print(f"  Add --title and --org flags, or add them to the PERSONNEL dict.")
            sys.exit(1)

    # Find draft
    draft_matches = glob.glob(os.path.join(folder, 'DIR_Form_*_DRAFT.docx'))
    if not draft_matches:
        print("ERROR: No DIR_Form_*_DRAFT.docx found")
        sys.exit(1)
    draft_path = draft_matches[0]
    print(f"\nDraft: {os.path.basename(draft_path)}")

    # Unpack (or use pre-unpacked dir)
    if args.xml_dir:
        doc_xml_path = os.path.join(args.xml_dir, 'word', 'document.xml')
        draft_tmp = None
    else:
        draft_tmp = tempfile.mkdtemp(prefix='author_')
        with zipfile.ZipFile(draft_path, 'r') as zf:
            zf.extractall(draft_tmp)
        doc_xml_path = os.path.join(draft_tmp, 'word', 'document.xml')
    with open(doc_xml_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Set ID counter above any existing tracked changes in the document
    global next_id
    next_id = find_max_id(content) + 100

    # Register namespaces
    for match in re.finditer(r'xmlns:(\w+)="([^"]+)"', content[:3000]):
        prefix, uri = match.group(1), match.group(2)
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass

    # Parse to find current values
    tree = ET.parse(doc_xml_path)
    root = tree.getroot()
    body = root.find(f'.//{{{W}}}body')

    # Find cover page author
    cover_elem, cover_author = find_cover_author(body)
    print(f"  Cover page author: {cover_author}")

    # Find tables
    tables = find_review_tables(body)
    if len(tables) < 3:
        print(f"ERROR: Found only {len(tables)} tables (need 3)")
        sys.exit(1)

    table_info = []
    labels = ['Author Review', 'Data Integrity Review', 'Technical Review']
    for i, tbl in enumerate(tables):
        info = extract_table_info(tbl)
        table_info.append(info)
        print(f"  {labels[i]}: {info['name']} — {info['title']}, {info['org']}")

    # Apply tracked changes — scoped to specific regions
    total_changes = 0
    changes_log = []

    # Find table boundaries for scoped replacement
    table_bounds = find_table_boundaries(content)
    cover_end = find_cover_region_end(content)

    if len(table_bounds) < 3:
        print(f"ERROR: Found only {len(table_bounds)} tables in XML (need 3)")
        sys.exit(1)

    # Author updates (cover page + table 0)
    if 'author' in assignments:
        new = assignments['author']
        old_name = cover_author
        old_info = table_info[0]

        # Cover page author (before first table)
        if old_name and old_name != new['name']:
            content, c = replace_text_tracked(content, old_name, new['name'],
                                              start=0, end=cover_end)
            total_changes += c
            changes_log.append(f"  Cover author: {old_name} → {new['name']} ({c})")
            # Recalculate boundaries after content change
            table_bounds = find_table_boundaries(content)

        # Table 0: name
        if old_info['name'] and old_info['name'] != new['name']:
            tbl_start, tbl_end = table_bounds[0]
            content, c = replace_text_tracked(content, old_info['name'], new['name'],
                                              start=tbl_start, end=tbl_end)
            total_changes += c
            changes_log.append(f"  Author table name: {old_info['name']} → {new['name']} ({c})")
            table_bounds = find_table_boundaries(content)

        # Table 0: title
        if old_info['title'] and old_info['title'] != new['title']:
            tbl_start, tbl_end = table_bounds[0]
            content, c = replace_text_tracked(content, old_info['title'], new['title'],
                                              start=tbl_start, end=tbl_end)
            total_changes += c
            changes_log.append(f"  Author title: {old_info['title']} → {new['title']} ({c})")
            table_bounds = find_table_boundaries(content)

        # Table 0: org
        if old_info['org'] and old_info['org'] != new['org']:
            tbl_start, tbl_end = table_bounds[0]
            content, c = replace_text_tracked(content, old_info['org'], new['org'],
                                              start=tbl_start, end=tbl_end)
            total_changes += c
            changes_log.append(f"  Author org: {old_info['org']} → {new['org']} ({c})")
            table_bounds = find_table_boundaries(content)

    # DI Reviewer updates (table 1 only)
    if 'di_reviewer' in assignments:
        new = assignments['di_reviewer']
        old_info = table_info[1]

        if old_info['name'] and old_info['name'] != new['name']:
            tbl_start, tbl_end = table_bounds[1]
            content, c = replace_text_tracked(content, old_info['name'], new['name'],
                                              start=tbl_start, end=tbl_end)
            total_changes += c
            changes_log.append(f"  DI Reviewer name: {old_info['name']} → {new['name']} ({c})")
            table_bounds = find_table_boundaries(content)

        if old_info['title'] and old_info['title'] != new['title']:
            tbl_start, tbl_end = table_bounds[1]
            content, c = replace_text_tracked(content, old_info['title'], new['title'],
                                              start=tbl_start, end=tbl_end)
            total_changes += c
            changes_log.append(f"  DI Reviewer title: {old_info['title']} → {new['title']} ({c})")
            table_bounds = find_table_boundaries(content)

        if old_info['org'] and old_info['org'] != new['org']:
            tbl_start, tbl_end = table_bounds[1]
            content, c = replace_text_tracked(content, old_info['org'], new['org'],
                                              start=tbl_start, end=tbl_end)
            total_changes += c
            changes_log.append(f"  DI Reviewer org: {old_info['org']} → {new['org']} ({c})")
            table_bounds = find_table_boundaries(content)

    # Technical Reviewer updates (table 2 only)
    if 'tech_reviewer' in assignments:
        new = assignments['tech_reviewer']
        old_info = table_info[2]

        if old_info['name'] and old_info['name'] != new['name']:
            tbl_start, tbl_end = table_bounds[2]
            content, c = replace_text_tracked(content, old_info['name'], new['name'],
                                              start=tbl_start, end=tbl_end)
            total_changes += c
            changes_log.append(f"  Tech Reviewer name: {old_info['name']} → {new['name']} ({c})")
            table_bounds = find_table_boundaries(content)

        if old_info['title'] and old_info['title'] != new['title']:
            tbl_start, tbl_end = table_bounds[2]
            content, c = replace_text_tracked(content, old_info['title'], new['title'],
                                              start=tbl_start, end=tbl_end)
            total_changes += c
            changes_log.append(f"  Tech Reviewer title: {old_info['title']} → {new['title']} ({c})")
            table_bounds = find_table_boundaries(content)

        if old_info['org'] and old_info['org'] != new['org']:
            tbl_start, tbl_end = table_bounds[2]
            content, c = replace_text_tracked(content, old_info['org'], new['org'],
                                              start=tbl_start, end=tbl_end)
            total_changes += c
            changes_log.append(f"  Tech Reviewer org: {old_info['org']} → {new['org']} ({c})")
            table_bounds = find_table_boundaries(content)

    # Write back
    with open(doc_xml_path, 'w', encoding='utf-8') as f:
        f.write(content)

    # Repack only in standalone mode
    if not args.xml_dir:
        with zipfile.ZipFile(draft_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root_dir, dirs, files in os.walk(draft_tmp):
                for file in files:
                    file_path = os.path.join(root_dir, file)
                    arc_name = os.path.relpath(file_path, draft_tmp)
                    zf.write(file_path, arc_name)

    # Cleanup
    if draft_tmp:
        shutil.rmtree(draft_tmp, ignore_errors=True)

    # Summary
    print(f"\n{'='*50}")
    print(f"Author/Reviewer Update Summary:")
    for line in changes_log:
        print(line)
    print(f"  Total replacements: {total_changes}")
    print(f"{'='*50}")

    if total_changes == 0:
        print("\nINFO: No changes needed (names already match)")


if __name__ == '__main__':
    main()
