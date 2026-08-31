#!/usr/bin/env python3
"""Shared utilities for stability-report-update scripts.

Provides XML escaping and ID management used across all task scripts.
"""

import re


def xml_escape(text):
    """Escape XML special characters in text content.

    Must be applied to any user-derived text inserted into XML elements
    (w:t, w:delText, etc.) to prevent malformed XML output.

    Args:
        text: Raw text string that may contain &, <, >, ", '

    Returns:
        Escaped string safe for XML text content.
    """
    if not text:
        return text
    # & must be escaped first (before other escapes that introduce &)
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    text = text.replace("'", '&apos;')
    return text


def find_max_id(xml_content):
    """Find the maximum w:id value in existing tracked changes.

    Scans for w:id="N" attributes in del/ins/format change elements.
    Returns the max value found, or 0 if none exist.

    Use this to set ID counters above existing values when modifying
    a document that may already contain tracked changes.
    """
    ids = re.findall(r'w:id="(\d+)"', xml_content)
    if not ids:
        return 0
    return max(int(i) for i in ids)
