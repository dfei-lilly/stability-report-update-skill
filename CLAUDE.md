# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Development and testing workspace for the `stability-report-update` Claude Code skill. This repo contains:
- Example input pairs for testing the skill against real data
- Output artifacts from test runs
- An LLM wiki documenting the skill's architecture, known issues, and fixes
- Session notes tracking development progress

The actual skill lives in two locations (keep both in sync):
- **Profile (triggers skill):** `~/.claude/skills/stability-report-update/`
- **Runtime (orchestrator reads scripts from here):** `~/skills/stability-report-update/`

After editing any script, copy it to both locations:
```bash
cp ~/skills/stability-report-update/scripts/<file>.py ~/.claude/skills/stability-report-update/scripts/<file>.py
```

## Running the Skill Against Examples

Each example pair has `prior/`, `current/`, and optionally `reference/` subdirectories. Run from inside the pair directory:

```bash
cd examples/pair-N
python ~/skills/stability-report-update/scripts/orchestrate.py \
  --prior-folder "prior/<vendor_folder>" \
  --current-folder "current/<vendor_folder>" \
  --timepoint "<new>M" \
  --author "<name>" \
  --di-reviewer "<name>" \
  --tech-reviewer "<name>" \
  --working-dir "." \
  --old-timepoint "<old>M" \
  --packages "<package_list>"
```

Omit `--packages` for "All packages". After running, compare against reference:

```bash
python ~/.claude/skills/compare-reports/scripts/compare_reports.py \
  "<draft>.docx" "reference/<ref>.docx" --mode full
```

Move outputs to `output/pair-N/` after runs.

## Running Tests

```bash
cd ~/skills/stability-report-update
python -m unittest discover tests/ -v
```

Run a single test file:
```bash
python -m unittest tests.test_orchestrate -v
```

Tests cover figures (heading similarity, skip conditions), orchestrator logic (same-timepoint, accelerated conditions, suffix handling), and shared utilities.

## Example Pairs

| Pair | Product | Timepoint | Packages | Notes |
|------|---------|-----------|----------|-------|
| pair-1 | OFG Tablets | 12M→18M | CFAF, Bulk | No sections deleted (all are target) |
| pair-2 | OFG Capsules | 12M→18M | Bottles | Deletes 3 non-target sections |
| pair-3 | OFG Capsules | 12M→18M | Blisters, Bulk | Deletes HDPE section only |
| pair-4 | OFG Capsules | 6M→12M | Bottles | All packages; has extra manual edits in reference |
| pair-5 | OFG Tablets | 12M→18M | Bottles, PCTFE | No sections deleted (only target pkgs present) |
| pair-6 | OFG Tablets | 18M→18M | CFAF (cross-package from Bottles) | Same-timepoint + cross-package: Bottles→CFAF |

## Skill Architecture (8 Sequential Tasks)

| # | Script | What it updates |
|---|--------|----------------|
| 1 | `author_reviewer.py` | Cover page author, 3 review tables (name, title, org) |
| 2 | `data_hash.py` | MD5 hash values from vendor zips |
| 3 | `golf_paths.py` | golf:\\ path references |
| 4 | `filenames.py` | Filename references (fuzzy-matched between prior/current) |
| 5 | `timepoint_text.py` | Written-out and numeric timepoint text |
| 6 | `figures.py` | Stability plot images (always updates all conditions) |
| 7 | `tables.py` | Summary statistics table values (skips accelerated after 6M) |
| 8 | `delete_sections.py` | Non-target package Heading1 sections |

All scripts live in `~/skills/stability-report-update/scripts/`. The orchestrator unpacks the docx to XML via `unpack.py` (which pretty-prints and merges adjacent runs), runs all tasks on the shared XML directory, then repacks.

## Key Architectural Details

### XML Processing Pipeline

The orchestrator uses `~/.claude/skills/docx/scripts/office/unpack.py` which:
1. Extracts the .docx ZIP
2. Pretty-prints all XML files (adds indentation/newlines)
3. **Merges adjacent `<w:r>` runs** with identical formatting (e.g., `"Dongling Fei"` + `" "` → `"Dongling Fei "`)

Scripts must account for merged runs when doing regex-based text matching. The `replace_text_tracked()` function in `author_reviewer.py` has three strategies: exact single-run match, partial match with whitespace padding (Strategy 1b), and paragraph-level match.

### Accelerated Conditions

Accelerated stability conditions (40°C/75% RH) stop collecting new data after 6 months. For timepoints > 6M:
- **Figures:** Always replaced (vendor may restyle plots even without new data points)
- **Tables:** Skipped via `--skip-conditions 40/75` (numerical values won't change)

**Exception:** On same-timepoint data refresh (`old_timepoint == new_timepoint`), accelerated conditions are NEVER skipped for tables — the vendor may have corrected that data.

### Same-Timepoint Mode

When `--old-timepoint` equals `--timepoint` (auto-detected from folder names), the orchestrator:
1. Skips `timepoint_text.py` (no text change needed)
2. Never passes `--skip-conditions` to tables (vendor may have corrected accelerated data)
3. Prints a "data refresh" mode banner
4. Renames prior report to `_DRAFT` (stripping `_FINAL` or existing `_DRAFT` suffix)

All other tasks (author, hash, paths, filenames, figures, tables, delete-sections) run normally.

### Cross-Package Mode

Auto-detected when the prior folder's package keyword (e.g., "Bottles") differs from the current folder's (e.g., "CFF"/"CFAF"). The orchestrator passes `--cross-package` to figures.py and tables.py:

- **Figures:** `heading_similarity()` ignores the Package field (`ignore_package=True`) so Bottle plots match CFAF plots by Property/Condition. Caption-based package filter is bypassed.
- **Tables:** Table-level caption filter is bypassed (would otherwise skip "Bottles" tables when target is CFAF). `target_packages` is used directly for vendor data lookup instead of caption-extracted package name.
- **Delete-sections:** Still runs normally — deletes non-target (Bottle/PCTFE) sections via tracked changes.

Detection uses `detect_package_keyword()` in orchestrate.py with hardcoded keyword map:
- `bottle/bottles/hdpe` → HDPE (125cc)
- `cfaf/cff` → CFAF Blister
- `pctfe` → PCTFE Blister
- `bulk` → Bulk Simulator

### Figures Matching Pipeline (4 Tiers)

Figures use a 3-stage chain: DIR → Prior → Current.

**DIR↔Prior matching** (which DIR image came from which prior plot):
1. **Tier 1:** Binary SHA-256 hash (exact byte match)
2. **Tier 2:** File-size similarity (>90% threshold)
3. **Tier 3:** Heading similarity (>50% threshold, token overlap with field-label stripping) — handles cases where Word recompressed images on insert

**Prior→Current matching** (which current vendor plot replaces each prior one):
- Heading similarity >70% threshold (field-aware structured comparison)
- In cross-package mode, Package field is ignored (`ignore_package=True`)

### Tables Logic Inference

`tables.py` infers aggregation rules (min/max/mean/first) and rounding methods per table by testing all combinations against prior vendor data. The Data Statistics sheet uses a combined `Stability_Condition` column (e.g., `"30°C/75% RH"`), not separate Temperature/Humidity columns — the `_condition_matches()` helper handles both formats.

### Tracked Changes

All modifications are written as Word tracked changes (`<w:del>`/`<w:ins>`) so the reviewer can accept/reject each in Word. The `shared_utils.find_max_id()` ensures new change IDs don't collide with existing ones.

## Package Name Normalization

User-facing names must be normalized to internal canonical names for delete-sections matching:

| User Input | Internal Name |
|------------|--------------|
| Bottles, HDPE | HDPE (125cc) |
| CFAF | CFAF Blister |
| PCTFE | PCTFE Blister |
| Bulk | Bulk Simulator |
| Blisters | PCTFE Blister + CFAF Blister |

This is handled by `normalize_target_packages()` in `delete_sections.py`.

## Known Acceptable Differences vs Reference

- **Off-by-1 table** in pair-1 (manually-added 4th reviewer) and pair-2 (manually-added archival table) — not automatable
- **Substitution diffs** — narrative text, DUCT project naming, data source filenames that differ between template and final reference
- **Pair-4 specifics:** unfuzzable filename (`2026_02_18 PS campaign...xlsx`), reference has 2 tech reviewers (skill supports 1), reference has 1 manually-deleted image

## LLM Wiki

This project includes an LLM wiki (`wiki/`) documenting skill internals. Key pages:
- `wiki/entities/stability-report-update-skill.md` — main skill overview
- `wiki/concepts/delete-sections-normalization-fix.md` — the package matching bug fix
- `wiki/concepts/stability-report-package-filtering.md` — how package filtering works
- `wiki/concepts/accelerated-condition-skip.md` — accelerated conditions behavior

Wiki conventions:
- `raw/` is immutable (hook-blocked). Source references go here.
- `wiki/` is LLM-owned compiled markdown with YAML frontmatter.
- Use `[[wikilinks]]` between pages. Every page ends with `## Backlinks`.
- Log changes to `wiki/log.md`. Update `wiki/index.md` when adding pages.

## Skill-First Workflow

Before starting any task, check if a relevant skill exists in `/mnt/skills/` or `~/.claude/skills/`. Common triggers:
- Word documents → `docx` skill
- Excel files → `xlsx` skill
- Creating/building a skill → `skill-creator`
- Stability report update → `stability-report-update` (this skill)
