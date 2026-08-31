#!/usr/bin/env python3
"""Replace figures in a DIR stability report with updated vendor plots.

Uses title-based matching: parses each DIR figure's caption into semantic
fields (Property, Package, Temperature, Humidity, Strength_Group) and matches
directly against the structured headings in the current stability_plots.docx.

Supports package-based filtering via --packages flag.
All replacements use Word tracked changes (w:del/w:ins).

Usage:
    python update_figures.py <working_dir>
    python update_figures.py <working_dir> --packages "HDPE (125cc)"
    python update_figures.py <working_dir> --xml-dir /tmp/dir_xml --packages "HDPE (125cc)"

Expects in working_dir:
  - DIR_Form_*_DRAFT.docx (standalone mode only)
  - stability_plots.docx (current vendor plots)
"""

import argparse
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared_utils import find_max_id

TODAY = date.today().strftime('%Y-%m-%dT00:00:00Z')
AUTHOR = 'Claude'
UNPACK_SCRIPT = os.path.expanduser('~/.claude/skills/docx/scripts/office/unpack.py')
PACK_SCRIPT = os.path.expanduser('~/.claude/skills/docx/scripts/office/pack.py')


def parse_rels(rels_path):
    """Parse document.xml.rels to map rId → media filename."""
    with open(rels_path, 'r', encoding='utf-8') as f:
        content = f.read()
    rels = {}
    for m in re.finditer(r'Id="(rId\d+)"[^>]*Target="([^"]*media/[^"]*)"', content):
        rels[m.group(1)] = m.group(2).replace('media/', '')
    return rels


def extract_images(doc_xml_path, rels_path, media_dir):
    """Extract all images from a document with their captions and headings.

    Skips images inside <w:del> blocks (tracked-change deletions) since those
    are ghost images from prior runs that are no longer "live" in the document.
    """
    with open(doc_xml_path, 'r', encoding='utf-8') as f:
        content = f.read()
    rels = parse_rels(rels_path)

    images = []
    paras = list(re.finditer(r'<w:p\b[^>]*>(.*?)</w:p>', content, re.DOTALL))

    for i, pm in enumerate(paras):
        para_content = pm.group(1)
        if '<w:drawing>' not in para_content:
            continue

        # Strip <w:del>...</w:del> blocks to ignore deleted images
        live_content = re.sub(r'<w:del\b[^>]*>.*?</w:del>', '', para_content, flags=re.DOTALL)
        if '<w:drawing>' not in live_content:
            continue

        for dm in re.finditer(r'<w:drawing>(.*?)</w:drawing>', live_content, re.DOTALL):
            bm = re.search(r'<a:blip[^>]*r:embed="(rId\d+)"', dm.group(1))
            if not bm:
                continue
            rid = bm.group(1)
            mf = rels.get(rid)
            if not mf:
                continue
            mp = os.path.join(media_dir, mf)
            if not os.path.exists(mp):
                continue

            # Caption: look forward up to 5 paragraphs
            caption = ''
            for j in range(i + 1, min(i + 5, len(paras))):
                t = ''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', paras[j].group(1)))
                if re.search(r'Figure\s+\d', t):
                    caption = t
                    break
                if '<w:drawing>' in paras[j].group(1):
                    break

            # Heading: look backward up to 5 paragraphs
            heading = ''
            for j in range(i - 1, max(i - 5, -1), -1):
                t = ''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', paras[j].group(1)))
                if t.strip() and '<w:drawing>' not in paras[j].group(1):
                    heading = t.strip()
                    break

            images.append({
                'media_file': mf,
                'rId': rid,
                'caption': caption,
                'heading': heading,
                'hash': hashlib.sha256(Path(mp).read_bytes()).hexdigest(),
                'media_path': mp
            })

    return images


def parse_vendor_heading(heading):
    """Parse a structured vendor heading into canonical fields.

    Input: 'Property: Assay (% Label Claim), Temperature: 30 °C, Humidity: 75%,
            Package: Blister-CFF, Strength_Group: Group 1: 0.8 mg & 2.5 mg'
    Returns dict with keys: property, package, temperature, humidity, strength_group
    """
    _field_pat = re.compile(
        r'(Package|Property|Temperature|Humidity|Stability_Condition|Strength_Group):\s*')
    parts = _field_pat.split(heading)
    raw = {}
    for i in range(1, len(parts) - 1, 2):
        raw[parts[i]] = parts[i + 1].rstrip(', ').strip()

    # Decompose Stability_Condition into Temperature + Humidity
    if 'Stability_Condition' in raw and 'Temperature' not in raw:
        sc = raw.pop('Stability_Condition')
        m = re.match(r'(\d+)\s*°?\s*C(?:\s*/\s*(\d+)\s*%)?', sc)
        if m:
            raw['Temperature'] = m.group(1)
            if m.group(2):
                raw['Humidity'] = m.group(2)

    fields = {}
    if 'Property' in raw:
        fields['property'] = raw['Property']
    if 'Temperature' in raw:
        fields['temperature'] = re.sub(r'[^\d]', '', raw['Temperature'])
    if 'Humidity' in raw:
        fields['humidity'] = re.sub(r'[^\d]', '', raw['Humidity'])
    if 'Package' in raw:
        # Normalize vendor package names to canonical forms
        pkg_lower = raw['Package'].lower().strip()
        if 'hdpe' in pkg_lower or pkg_lower == 'bottle' or 'bottles' in pkg_lower:
            fields['package'] = 'bottle'
        elif 'cff' in pkg_lower or 'cfaf' in pkg_lower:
            fields['package'] = 'blister-cff'
        elif 'pctfe' in pkg_lower:
            fields['package'] = 'blister-pctfe'
        elif 'bulk' in pkg_lower:
            fields['package'] = 'bulk'
        else:
            fields['package'] = pkg_lower
    if 'Strength_Group' in raw:
        fields['strength_group'] = raw['Strength_Group']
    return fields


def parse_dir_caption(caption):
    """Parse a DIR figure caption into canonical fields for matching.

    Input examples:
      'Figure 2.1.1-1.Assay Results for 0.8 mg and 2.5 mg Batches Packaged
       in CFAF Blisters at 30°C/75% RH'
      'Figure 2.2.1-1.Dissolution Average Percent Dissolved Results at 15 Minutes
       for 0.8 mg and 2.5 mg Batches Packaged in CFAF Blisters at 30°C/75% RH'

    Returns dict with keys: property, package, temperature, humidity, strengths (list of floats)
    """
    # Strip "Figure X.Y.Z-N." prefix
    text = re.sub(r'^Figure\s+[\d\.\-]+\s*\.?\s*', '', caption).strip()

    fields = {}

    # Extract temperature and humidity: "at XX°C/YY% RH" or "at XX°C"
    cond_m = re.search(r'at\s+(\d+)\s*°?\s*C(?:\s*/\s*(\d+)\s*%\s*(?:RH)?)?', text)
    if cond_m:
        fields['temperature'] = cond_m.group(1)
        if cond_m.group(2):
            fields['humidity'] = cond_m.group(2)

    # Extract package: "Packaged in <Package>" or "in <Package> at"
    pkg_m = re.search(r'(?:Packaged\s+in|in)\s+(.+?)\s+at\s+\d+\s*°', text)
    if pkg_m:
        pkg_text = pkg_m.group(1).strip()
        # Normalize DIR package names to vendor format
        pkg_lower = pkg_text.lower()
        if 'cfaf' in pkg_lower or 'cff' in pkg_lower:
            fields['package'] = 'blister-cff'
        elif 'pctfe' in pkg_lower:
            fields['package'] = 'blister-pctfe'
        elif 'bottle' in pkg_lower or 'hdpe' in pkg_lower:
            fields['package'] = 'bottle'
        elif 'bulk' in pkg_lower:
            fields['package'] = 'bulk'
        else:
            fields['package'] = pkg_lower

    # Extract strength values: "for X mg and Y mg Batches" or "for X mg, Y mg, ... Batches"
    str_m = re.search(r'for\s+(.+?)\s+Batch', text)
    if str_m:
        str_text = str_m.group(1)
        mg_values = [float(v) for v in re.findall(r'([\d.]+)\s*mg', str_text)]
        if mg_values:
            fields['strengths'] = mg_values

    # Extract property: everything before "Results for" or "for ... Batches"
    # Handle "Dissolution Average Percent Dissolved Results at 15 Minutes for ..."
    # Handle "Assay Results for ..."
    # Handle "Water Activity Results for ..."
    prop_m = re.match(r'^(.+?)\s+(?:Results?\s+)?for\s+[\d.]', text)
    if not prop_m:
        # Try without "for" (some captions may differ)
        prop_m = re.match(r'^(.+?)\s+(?:Results?\s+)(?:at|in)', text)
    if prop_m:
        prop_text = prop_m.group(1).strip()
        # Remove trailing "Results" if present
        prop_text = re.sub(r'\s+Results?$', '', prop_text).strip()
        fields['property_raw'] = prop_text

        # Normalize to vendor Property format
        prop_lower = prop_text.lower()
        if prop_lower == 'assay':
            fields['property'] = 'Assay (% Label Claim)'
        elif 'water activity' in prop_lower:
            fields['property'] = 'Aw'
        elif 'moisture' in prop_lower:
            fields['property'] = 'Moisture Content (%)'
        elif 'total degradation' in prop_lower:
            fields['property'] = 'Total Degradation Products (% w/w)'
        elif 'individual' in prop_lower and 'degradation' in prop_lower:
            fields['property'] = 'Individual Maximum Degradation Product (% w/w)'
        else:
            # Dissolution patterns: "Dissolution Average Percent Dissolved at X Minutes"
            # → "Average % Dissolved at X Minutes"
            # "Dissolution Minimum Percent Dissolved at X Minutes"
            # → "Minimum % Dissolved at X Minutes"
            diss_m = re.match(
                r'Dissolution\s+(Average|Minimum)\s+Percent\s+Dissolved'
                r'(?:\s+Results?)?\s+at\s+(\d+)\s+Minutes',
                prop_text, re.IGNORECASE)
            if diss_m:
                kind = diss_m.group(1).capitalize()
                minutes = diss_m.group(2)
                fields['property'] = f'{kind} % Dissolved at {minutes} Minutes'
            else:
                # Fallback: keep raw text for fuzzy matching
                fields['property'] = prop_text

    return fields


def fields_match(dir_fields, vendor_fields, ignore_package=False):
    """Compare parsed DIR caption fields against parsed vendor heading fields.

    Returns a score from 0.0 to 1.0 based on field-by-field matching.
    All present fields must match for a high score.

    In cross-package mode (ignore_package=True), humidity is also relaxed because
    different packages have different storage conditions at the same temperature
    (e.g., Bottles at 30°C/65% vs CFAF at 30°C/75%).
    """
    if not dir_fields or not vendor_fields:
        return 0.0

    matched = 0
    total = 0

    # Property match
    if 'property' in dir_fields and 'property' in vendor_fields:
        total += 1
        dp = dir_fields['property'].lower().strip()
        vp = vendor_fields['property'].lower().strip()
        if dp == vp:
            matched += 1
        else:
            # Normalize: strip common prefixes/suffixes for comparison
            # "Average % Dissolved at 15 Minutes" should match
            # "Dissolution Average % Dissolved at 15 Minutes"
            dp_norm = re.sub(r'^dissolution\s+', '', dp)
            vp_norm = re.sub(r'^dissolution\s+', '', vp)
            if dp_norm == vp_norm:
                matched += 1
            else:
                # Fuzzy: check if key tokens overlap (for unknown property names)
                stop = {'the', 'at', 'for', 'of', 'in', 'and', 'or', 'a', 'an', 'to', 'is',
                        'percent', '%', 'results', 'dissolution'}
                dw = set(re.findall(r'\w+', dp)) - stop
                vw = set(re.findall(r'\w+', vp)) - stop
                if dw and vw:
                    overlap = len(dw & vw) / max(len(dw), len(vw))
                    if overlap >= 0.6:
                        matched += overlap

    # Temperature match (exact numeric)
    if 'temperature' in dir_fields and 'temperature' in vendor_fields:
        total += 1
        if dir_fields['temperature'] == vendor_fields['temperature']:
            matched += 1

    # Humidity match (exact numeric)
    # In cross-package mode, skip humidity comparison entirely — different packages
    # have different storage conditions at the same temperature (e.g., Bottles
    # stored at 30°C/65% while CFAF stored at 30°C/75%)
    if not ignore_package:
        if 'humidity' in dir_fields and 'humidity' in vendor_fields:
            total += 1
            if dir_fields['humidity'] == vendor_fields['humidity']:
                matched += 1
        elif 'humidity' in dir_fields or 'humidity' in vendor_fields:
            # One has humidity, the other doesn't — only penalize if both should have it
            # (refrigerator conditions like 5°C may legitimately lack humidity)
            pass

    # Package match
    if 'package' in dir_fields and 'package' in vendor_fields:
        total += 1
        if ignore_package:
            matched += 1
        elif dir_fields['package'] == vendor_fields['package']:
            matched += 1

    # Strength group match: check if DIR mg values appear in vendor's Strength_Group
    if 'strengths' in dir_fields and 'strength_group' in vendor_fields:
        total += 1
        sg = vendor_fields['strength_group']
        # Extract mg values from vendor strength group (e.g., "Group 1: 0.8 mg & 2.5 mg")
        vendor_mg = [float(v) for v in re.findall(r'([\d.]+)\s*mg', sg)]
        dir_mg = dir_fields['strengths']
        if vendor_mg and dir_mg:
            # Check if the first DIR mg value appears in vendor mg values
            if dir_mg[0] in vendor_mg:
                matched += 1

    if total == 0:
        return 0.0
    return matched / total


def heading_similarity(h1, h2, ignore_package=False):
    """Compute similarity between two stability-plot headings.

    Stability plot headings are structured with labeled fields like:
      'Package: X, Property: Y, Temperature: Z, Humidity: W, Strength_Group: V'

    When both headings have this structure, compare field-by-field so that
    numeric values in one field (e.g., '75' in 'Humidity: 75%') don't get
    confused with the same number in another field (e.g., '75 Minutes' in
    the Property field).  Falls back to token overlap for unstructured headings.

    Args:
        ignore_package: If True, treat Package field as always matching.
            Used in cross-package mode where Bottle plots are replaced with CFAF data.
    """
    FIELDS = ['Package', 'Property', 'Temperature', 'Humidity', 'Strength_Group']
    _field_pat = re.compile(
        r'(Package|Property|Temperature|Humidity|Stability_Condition|Strength_Group):\s*')

    def _parse_fields(h):
        parts = _field_pat.split(h)
        fields = {}
        for i in range(1, len(parts) - 1, 2):
            fields[parts[i]] = parts[i + 1].rstrip(', ').strip()
        # Decompose Stability_Condition into Temperature + Humidity
        # e.g. "30°C/75% RH" → Temperature: "30 °C", Humidity: "75%"
        # e.g. "5°C" → Temperature: "5 °C" (no Humidity)
        if 'Stability_Condition' in fields and 'Temperature' not in fields:
            sc = fields.pop('Stability_Condition')
            m = re.match(r'(\d+)\s*°?\s*C(?:\s*/\s*(\d+)\s*%)?', sc)
            if m:
                fields['Temperature'] = f"{m.group(1)} °C"
                if m.group(2):
                    fields['Humidity'] = f"{m.group(2)}%"
        return fields

    f1 = _parse_fields(h1)
    f2 = _parse_fields(h2)

    # Field-aware comparison when both headings are structured
    if len(f1) >= 2 and len(f2) >= 2:
        matched_fields = 0
        total_fields = 0
        for field in FIELDS:
            v1 = f1.get(field)
            v2 = f2.get(field)
            if v1 is None and v2 is None:
                continue
            # Humidity can legitimately be absent (refrigerator conditions like
            # "5°C" have no specified RH). Don't penalize the missing field.
            if field == 'Humidity' and (v1 is None or v2 is None):
                continue
            total_fields += 1
            if v1 is None or v2 is None:
                continue
            if field == 'Property':
                # Token overlap within Property (contains measurement name + timepoint)
                stop = {'the', 'at', 'for', 'of', 'in', 'and', 'or', 'a', 'an',
                        'to', 'is'}
                w1 = set(re.findall(r'\w+', v1.lower())) - stop
                w2 = set(re.findall(r'\w+', v2.lower())) - stop
                if w1 and w2:
                    matched_fields += len(w1 & w2) / max(len(w1), len(w2))
            elif field == 'Package':
                if ignore_package:
                    matched_fields += 1  # Always match in cross-package mode
                elif v1.lower().strip() == v2.lower().strip():
                    matched_fields += 1
                else:
                    p1 = v1.lower().split()[0] if v1 else ''
                    p2 = v2.lower().split()[0] if v2 else ''
                    if p1 and p1 == p2:
                        matched_fields += 0.9
            else:
                # Temperature, Humidity, Strength_Group: exact match
                if v1.lower().strip() == v2.lower().strip():
                    matched_fields += 1

        if total_fields == 0:
            return 0.0
        return matched_fields / total_fields

    # Fallback: token-based matching for unstructured headings
    # Strip field labels (e.g., "Package:", "Property:") so structured headings
    # can still match against unstructured narrative headings from the DIR.
    _label_pat = re.compile(
        r'(Package|Property|Temperature|Humidity|Stability_Condition|Strength_Group):\s*')
    h1_clean = _label_pat.sub('', h1)
    h2_clean = _label_pat.sub('', h2)

    stop = {'the', 'at', 'for', 'of', 'in', 'and', 'or', 'a', 'an', 'to', 'is'}
    w1 = set(re.findall(r'\w+', h1_clean.lower())) - stop
    w2 = set(re.findall(r'\w+', h2_clean.lower())) - stop
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / max(len(w1), len(w2))


def condition_matches_skip(heading, skip_conditions):
    """Check if a figure's heading matches a skipped storage condition.

    Handles both structured headings ('Temperature: 40 °C, Humidity: 75%')
    and DIR document headings ('... at 40°C/75% RH').
    """
    if not skip_conditions:
        return False
    # Structured heading format: 'Temperature: 40 °C, Humidity: 75%'
    temp_m = re.search(r'Temperature:\s*(\d+)', heading)
    hum_m = re.search(r'Humidity:\s*(\d+)', heading)
    if temp_m and hum_m:
        return (int(temp_m.group(1)), int(hum_m.group(1))) in skip_conditions
    # DIR heading format: '... at 40°C/75% RH'
    cond_m = re.search(r'(\d+)\s*°?\s*C\s*/\s*(\d+)\s*%', heading)
    if cond_m:
        return (int(cond_m.group(1)), int(cond_m.group(2))) in skip_conditions
    return False


def caption_matches_packages(caption, heading, target_packages):
    """Check if a figure's caption/heading matches the target package scope.

    Returns True if:
      - target_packages is None (no filter)
      - caption/heading contains a keyword for a target package
      - caption/heading has NO package keywords at all (assumed general figure)
    """
    if not target_packages:
        return True

    text = (caption + ' ' + heading).lower()

    PACKAGE_CAPTION_KEYWORDS = {
        'HDPE (125cc)': ['hdpe', 'bottles', 'bottle'],
        'CFAF Blister': ['cfaf', 'cfaf blister'],
        'PCTFE Blister': ['pctfe', 'pctfe blister'],
        'Bulk Simulator': ['bulk simulator', 'bulk bag'],
    }

    # Check if any target package keyword is present
    for pkg in target_packages:
        keywords = PACKAGE_CAPTION_KEYWORDS.get(pkg, [pkg.lower()])
        for kw in keywords:
            if kw in text:
                return True

    # Check if ANY package keyword is present (to distinguish "other package" from "no package")
    has_any_package_keyword = False
    for keywords in PACKAGE_CAPTION_KEYWORDS.values():
        for kw in keywords:
            if kw in text:
                has_any_package_keyword = True
                break
        if has_any_package_keyword:
            break

    # No package keyword at all → general figure, include it
    if not has_any_package_keyword:
        return True

    # Has a non-target package keyword → skip
    return False


def update_figures(dir_work, current_plots_dir, target_packages=None,
                   skip_conditions=None, cross_package=False):
    """Match DIR figures to current vendor plots by title and replace. Returns count."""
    dir_media = os.path.join(dir_work, 'word', 'media')
    current_media = os.path.join(current_plots_dir, 'word', 'media')

    dir_imgs = extract_images(
        os.path.join(dir_work, 'word', 'document.xml'),
        os.path.join(dir_work, 'word', '_rels', 'document.xml.rels'),
        dir_media)
    current_imgs = extract_images(
        os.path.join(current_plots_dir, 'word', 'document.xml'),
        os.path.join(current_plots_dir, 'word', '_rels', 'document.xml.rels'),
        current_media)

    if not dir_imgs:
        print("  No figures found in DIR")
        return 0

    # Parse all current vendor headings into structured fields
    current_parsed = []
    for ci, c in enumerate(current_imgs):
        fields = parse_vendor_heading(c['heading'])
        current_parsed.append(fields)

    # Match each DIR figure to current by parsing its caption
    matches = {}  # di → ci
    matched_current = set()
    skipped_pkg = 0
    skipped_cond = 0
    unmatched_captions = []

    for di, d in enumerate(dir_imgs):
        caption = d.get('caption', '')
        heading = d.get('heading', '')

        # Package filter: skip figures outside target scope
        if target_packages and not cross_package:
            if not caption_matches_packages(caption, heading, target_packages):
                skipped_pkg += 1
                continue

        # Parse DIR caption into structured fields
        dir_fields = parse_dir_caption(caption)
        if not dir_fields:
            # Fallback: try parsing the heading (for section-heading-only figures)
            dir_fields = parse_dir_caption(heading)
        if not dir_fields:
            unmatched_captions.append(caption[:80] if caption else heading[:80])
            continue

        # Condition filter: skip accelerated conditions
        if skip_conditions:
            temp = dir_fields.get('temperature')
            hum = dir_fields.get('humidity')
            if temp and hum:
                try:
                    if (int(temp), int(hum)) in skip_conditions:
                        skipped_cond += 1
                        continue
                except ValueError:
                    pass

        # Find best matching current image
        best_score, best_ci = 0, None
        for ci in range(len(current_imgs)):
            if ci in matched_current:
                continue
            score = fields_match(dir_fields, current_parsed[ci],
                                 ignore_package=cross_package)
            if score > best_score:
                best_score = score
                best_ci = ci

        if best_score >= 0.9 and best_ci is not None:
            matches[di] = best_ci
            matched_current.add(best_ci)
        else:
            unmatched_captions.append(
                f"{caption[:60]}... (best={best_score:.2f})" if caption
                else f"{heading[:60]}... (best={best_score:.2f})")

    print(f"  DIR→Current match: {len(matches)}/{len(dir_imgs)} (title-based)")
    if skipped_pkg > 0:
        print(f"  Skipped (outside package scope): {skipped_pkg}")
    if skipped_cond > 0:
        print(f"  Skipped (accelerated condition): {skipped_cond}")
    if unmatched_captions:
        print(f"  Unmatched: {len(unmatched_captions)}")
        for uc in unmatched_captions[:5]:
            print(f"    - {uc}")

    # Build replacement map and update rels
    rels_path = os.path.join(dir_work, 'word', '_rels', 'document.xml.rels')
    with open(rels_path, 'r', encoding='utf-8') as f:
        rels_content = f.read()

    existing_rids = [int(m.group(1)) for m in re.finditer(r'Id="rId(\d+)"', rels_content)]
    next_rid = max(existing_rids) + 1

    new_rids = {}
    new_rels = []
    for di in sorted(matches.keys()):
        ci = matches[di]
        src = current_imgs[ci]['media_path']
        ext = os.path.splitext(current_imgs[ci]['media_file'])[1]
        new_name = f"new_img{di}{ext}"
        shutil.copy2(src, os.path.join(dir_media, new_name))
        rid = f"rId{next_rid}"
        next_rid += 1
        new_rids[di] = (dir_imgs[di]['rId'], rid, current_imgs[ci]['media_path'])
        new_rels.append(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{new_name}"/>')

    rels_content = rels_content.replace('</Relationships>', '\n'.join(new_rels) + '\n</Relationships>')
    with open(rels_path, 'w', encoding='utf-8') as f:
        f.write(rels_content)

    # Replace in document.xml
    doc_path = os.path.join(dir_work, 'word', 'document.xml')
    with open(doc_path, 'r', encoding='utf-8') as f:
        content = f.read()

    change_id = find_max_id(content) + 100
    figs_replaced = 0
    run_pat = re.compile(r'(<w:r(?:\s[^>]*)?>)(.*?)(</w:r>)', re.DOTALL)

    def repl_run(m):
        nonlocal change_id, figs_replaced
        ro, rb, rc = m.group(1), m.group(2), m.group(3)
        bm = re.search(r'<a:blip[^>]*r:embed="(rId\d+)"', rb)
        if not bm:
            return m.group(0)
        rid = bm.group(1)
        for di, (old_rid, new_rid, new_path) in new_rids.items():
            if rid == old_rid:
                new_hash = hashlib.sha256(Path(new_path).read_bytes()).hexdigest()
                if dir_imgs[di]['hash'] == new_hash:
                    return m.group(0)
                new_rb = rb.replace(f'r:embed="{rid}"', f'r:embed="{new_rid}"')
                did = change_id
                iid = change_id + 1
                change_id += 2
                figs_replaced += 1
                return (f'<w:del w:id="{did}" w:author="{AUTHOR}" w:date="{TODAY}">{ro}{rb}{rc}</w:del>'
                        f'<w:ins w:id="{iid}" w:author="{AUTHOR}" w:date="{TODAY}">{ro}{new_rb}{rc}</w:ins>')
        return m.group(0)

    content = run_pat.sub(repl_run, content)
    with open(doc_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return figs_replaced


def main():
    parser = argparse.ArgumentParser(description='Replace figures in DIR report with updated vendor plots')
    parser.add_argument('working_dir', help='Directory containing vendor files')
    parser.add_argument('--xml-dir', default=None,
                        help='Pre-unpacked XML directory for the DIR (skip unpack/repack)')
    parser.add_argument('--packages', default=None,
                        help='Comma-separated package filter (e.g., "HDPE (125cc)")')
    parser.add_argument('--skip-conditions', default=None,
                        help='Comma-separated temp/humidity conditions to skip (e.g., "40/75")')
    parser.add_argument('--cross-package', action='store_true', default=False,
                        help='Cross-package mode: ignore Package field in heading matching')
    args = parser.parse_args()

    working_dir = os.path.abspath(args.working_dir)
    target_packages = None
    if args.packages:
        target_packages = [p.strip() for p in args.packages.split(',')]
        print(f"Package filter: {target_packages}")
    if args.cross_package:
        print(f"Cross-package mode: ignoring Package field in heading matching")

    skip_conditions = None
    if args.skip_conditions:
        skip_conditions = set()
        for cond in args.skip_conditions.split(','):
            parts = cond.strip().split('/')
            if len(parts) != 2:
                print(f"ERROR: Invalid condition format '{cond.strip()}' "
                      f"(expected 'temp/humidity', e.g. '40/75')", file=sys.stderr)
                sys.exit(1)
            try:
                skip_conditions.add((int(parts[0]), int(parts[1])))
            except ValueError:
                print(f"ERROR: Non-numeric condition '{cond.strip()}' "
                      f"(expected integers, e.g. '40/75')", file=sys.stderr)
                sys.exit(1)
        print(f"Skip conditions: {skip_conditions}")

    # Check required files
    current_plots = os.path.join(working_dir, 'stability_plots.docx')

    if not os.path.exists(current_plots):
        print("ERROR: stability_plots.docx not found in working dir", file=sys.stderr)
        sys.exit(1)

    print("Updating figures in DIR report (title-based matching)")

    with tempfile.TemporaryDirectory(prefix='fig_') as tmp_base:
        current_work = os.path.join(tmp_base, 'current')

        subprocess.run([sys.executable, UNPACK_SCRIPT, current_plots, current_work],
                      capture_output=True, text=True, check=True)

        if args.xml_dir:
            dir_work = args.xml_dir
        else:
            # Standalone: find and unpack DRAFT
            pattern = os.path.join(working_dir, 'DIR_Form_*_DRAFT.docx')
            drafts = glob.glob(pattern)
            if not drafts:
                print("ERROR: No DIR_Form_*_DRAFT.docx found", file=sys.stderr)
                sys.exit(1)
            docx_path = drafts[0]
            dir_work = os.path.join(tmp_base, 'dir')
            subprocess.run([sys.executable, UNPACK_SCRIPT, docx_path, dir_work],
                          capture_output=True, text=True, check=True)

        fig_count = update_figures(dir_work, current_work, target_packages,
                                    skip_conditions, cross_package=args.cross_package)
        print(f"  Replaced: {fig_count}")

        # Repack in standalone mode
        if not args.xml_dir:
            result = subprocess.run(
                [sys.executable, PACK_SCRIPT, dir_work, docx_path, '--validate', 'false'],
                capture_output=True, text=True)
            if result.returncode != 0:
                print(f"ERROR repacking: {result.stderr[:200]}", file=sys.stderr)
                sys.exit(1)
            print(f"Updated: {os.path.basename(docx_path)}")


if __name__ == '__main__':
    main()
