# Stability Report Update Skill — Architecture Overview

## What It Does

Automates updating a stability DIR report (Word `.docx`) from one timepoint to the next (e.g., 12M → 18M), or refreshes data within the same timepoint. Produces a tracked-changes `_DRAFT.docx` that a statistician reviews in Word.

---

## Skill Locations (two copies, kept in sync)

```
~/.claude/skills/stability-report-update/   ← profile (triggers the skill)
~/skills/stability-report-update/            ← runtime (scripts execute from here)
```

After any script edit: `cp ~/skills/.../scripts/<file>.py ~/.claude/skills/.../scripts/<file>.py`

---

## File Structure

```
stability-report-update/
├── SKILL.md                         ← Skill definition (Claude's instructions)
├── scripts/
│   ├── orchestrate.py               ← Main orchestrator — runs all 8 tasks sequentially
│   ├── author_reviewer.py           ← Task 1: personnel names/titles/org
│   ├── data_hash.py                 ← Task 2: MD5 hashes from vendor zips
│   ├── golf_paths.py                ← Task 3: golf:\\ path references
│   ├── filenames.py                 ← Task 4: filename references (fuzzy-matched)
│   ├── timepoint_text.py            ← Task 5: "Twelve Month" → "Eighteen Month"
│   ├── figures.py                   ← Task 6: stability plot images
│   ├── tables.py                    ← Task 7: summary statistics table values
│   ├── delete_sections.py           ← Task 8: remove non-target package sections
│   └── shared_utils.py              ← xml_escape(), find_max_id()
├── tests/
│   ├── test_figures.py
│   ├── test_orchestrate.py
│   └── test_utils.py
└── evals/
    └── trigger_eval.json
```

### Standalone Skills

One per task, for running individual tasks outside the orchestrator:

```
~/.claude/skills/
├── stability-author/SKILL.md        ← Just personnel (with keep-current option)
├── stability-hash/SKILL.md
├── stability-golf-paths/SKILL.md
├── stability-filenames/SKILL.md
├── stability-timepoint/SKILL.md
├── stability-figures/SKILL.md
├── stability-tables/SKILL.md
└── stability-delete-sections/SKILL.md
```

---

## How It Runs (the pipeline)

```
User says "update the DIR"
        │
        ▼
┌─────────────────────────────────────────────┐
│  SKILL.md (Claude's instructions)           │
│                                             │
│  Step 0:  Auto-discover folders/timepoints  │
│  Step 1a: Read current personnel (--read-   │
│           current flag → JSON output)       │
│  Step 1b: ONE popup (up to 5 questions):    │
│           Personnel | Folders | Timepoint   │
│           | Packages | Reference            │
│  Step 1c: Resolve personnel (keep or new)   │
│  Step 2:  Run orchestrate.py                │
│  Step 3:  Compare against reference (opt.)  │
│  Step 4:  Move outputs, report results      │
└───────────────┬─────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────┐
│  orchestrate.py                             │
│                                             │
│  1. Unpack DRAFT.docx → shared XML dir      │
│     (via unpack.py: pretty-print + merge    │
│      adjacent <w:r> runs)                   │
│                                             │
│  2. Run 8 tasks sequentially on shared XML: │
│     ┌──────────────────┬──────────────────┐ │
│     │ 1. author_reviewer│ names/titles/org │ │
│     │ 2. data_hash      │ MD5 hashes      │ │
│     │ 3. golf_paths     │ golf:\\ paths   │ │
│     │ 4. filenames      │ fuzzy file refs  │ │
│     │ 5. timepoint_text │ "12M" → "18M"   │ │
│     │ 6. figures        │ plot images      │ │
│     │ 7. tables         │ stats values     │ │
│     │ 8. delete_sections│ non-target pkgs  │ │
│     └──────────────────┴──────────────────┘ │
│                                             │
│  3. Repack XML → _DRAFT.docx                │
└─────────────────────────────────────────────┘
```

---

## Key Concepts

| Concept | What it means |
|---------|---------------|
| **Tracked changes** | Every edit is a `<w:del>`/`<w:ins>` pair — reviewer accepts/rejects in Word |
| **Package filtering** | `--packages "CFAF, Bulk"` limits figures/tables to those packages; delete-sections removes the rest |
| **Same-timepoint mode** | Auto-detected when old == new timepoint → skips timepoint-text, never skips accelerated conditions for tables |
| **Cross-package mode** | Auto-detected when prior folder package ≠ current → adjusts figure/table matching to ignore package field |
| **Accelerated skip** | For timepoints > 6M, tables skip 40°C/75% RH conditions (no new data after 6 months); figures always update |
| **Keep-current personnel** | `--read-current` flag reads names from the docx → "Keep current" is the default first option in both skills |

---

## The 8 Tasks in Detail

### Task 1: `author_reviewer.py` — Personnel

Updates cover page author name and 3 review tables (Author, DI Reviewer, Tech Reviewer). Each table has name, title, and organization fields. Has a `--read-current` flag that prints current personnel as JSON without making changes — used by the skill to offer "keep current" as the default.

**Key functions:**
- `lookup_personnel(name)` — resolves names via a hardcoded directory (aliases, case-insensitive, first/last-name matching)
- `replace_text_tracked()` — 3-strategy regex replacement engine (single-run, whitespace-padded, paragraph-level)
- `find_cover_author()` / `find_review_tables()` / `extract_table_info()` — XML parsing helpers

### Task 2: `data_hash.py` — Data Hashes

Replaces MD5 hash values in the report with hashes computed from vendor zip files in the current folder.

### Task 3: `golf_paths.py` — Golf Paths

Updates `golf:\golf.grp\CMC_STATS\<folder>` path references to point to the current vendor folder.

### Task 4: `filenames.py` — Filename References

Fuzzy-matches filenames between prior and current vendor folders, then replaces all filename references in the report. Handles cases where vendors rename files between timepoints.

### Task 5: `timepoint_text.py` — Timepoint Text

Replaces written-out timepoint text (e.g., "Twelve Month" → "Eighteen Month") and numeric references (e.g., "12-Month" → "18-Month"). Skipped entirely in same-timepoint mode.

### Task 6: `figures.py` — Stability Plot Images

Replaces stability plot images using a 3-stage matching chain:

1. **DIR ↔ Prior** (which DIR image came from which prior plot):
   - Tier 1: Binary SHA-256 hash (exact byte match)
   - Tier 2: File-size similarity (>90%)
   - Tier 3: Heading similarity (>50%, token overlap)

2. **Prior → Current** (which current plot replaces each prior one):
   - Heading similarity >70% (field-aware structured comparison)

Always updates all conditions (including accelerated) since vendors may restyle plots.

### Task 7: `tables.py` — Summary Statistics

Replaces numerical values in summary statistics tables. Infers aggregation rules (min/max/mean/first) and rounding methods per table by testing all combinations against prior vendor data. For timepoints > 6M, skips accelerated conditions (40°C/75% RH) unless in same-timepoint mode.

### Task 8: `delete_sections.py` — Section Deletion

Removes Heading 1 sections for non-target packages using tracked-change deletions. Package names are normalized from user-facing names (e.g., "Bottles" → "HDPE (125cc)") via `normalize_target_packages()`.

---

## XML Processing Pipeline

The orchestrator uses `unpack.py` which:
1. Extracts the `.docx` ZIP
2. Pretty-prints all XML files (adds indentation/newlines)
3. **Merges adjacent `<w:r>` runs** with identical formatting (e.g., `"Dongling Fei"` + `" "` → `"Dongling Fei "`)

All 8 task scripts operate on the shared unpacked XML directory. The orchestrator repacks once at the end.

Scripts must account for merged runs when doing regex-based text matching. The `replace_text_tracked()` function in `author_reviewer.py` demonstrates the 3-strategy approach: exact single-run match, partial match with whitespace padding (Strategy 1b), and paragraph-level match.

---

## Package Name Normalization

User-facing names must be normalized to internal canonical names:

| User Input | Internal Name |
|------------|--------------|
| Bottles, HDPE | HDPE (125cc) |
| CFAF | CFAF Blister |
| PCTFE | PCTFE Blister |
| Bulk | Bulk Simulator |
| Blisters | PCTFE Blister + CFAF Blister |

---

## Testing

### Example Pairs

```
~/stability-report-update-skill-dev/examples/
├── pair-1/  ← Ground truth (ALWAYS run first for any change)
├── pair-2/  ← Tests section deletion (3 sections)
├── pair-3/  ← Tests section deletion (1 section)
├── pair-4/  ← Tests 6M→12M progression
├── pair-5/  ← Tests multi-package, no deletions
├── pair-6/  ← Tests same-timepoint + cross-package
├── pair-7/  ← Tests 18M→24M, all packages (multi-prior merge)
├── pair-8/  ← Tests 18M→24M, 0.2% SDS dissolution, Bottles
└── pair-9/  ← Tests 18M→24M, 0.2% SDS dissolution, CFF (CFAF)
```

Each pair has `prior/`, `current/`, and `reference/` subdirectories. Run the orchestrator, then compare:

```bash
cd examples/pair-1
python ~/skills/stability-report-update/scripts/orchestrate.py \
  --prior-folder "prior/<vendor_folder>" \
  --current-folder "current/<vendor_folder>" \
  --timepoint "18M" --old-timepoint "12M" \
  --author "Dongling" --di-reviewer "Chad" --tech-reviewer "Chad" \
  --working-dir "." --packages "CFAF, Bulk"

python ~/.claude/skills/compare-reports/scripts/compare_reports.py \
  "<draft>.docx" "reference/<ref>.docx" --mode full
```

### Quick Reference

| Pair | Product | Timepoint | Packages | Sections Deleted | Notes | Reference |
|------|---------|-----------|----------|-----------------|-------|-----------|
| 1 | OFG Tablets | 12M→18M | CFAF, Bulk | 0 | Ground truth for all changes | ✅ |
| 2 | OFG Capsules | 12M→18M | Bottles | 3 | Heavy section deletion | ✅ |
| 3 | OFG Capsules | 12M→18M | Blisters, Bulk | 1 | Light section deletion | ✅ |
| 4 | OFG Capsules | 6M→12M | Bottles | Multiple | Has extra manual edits in reference | ✅ |
| 5 | OFG Tablets | 12M→18M | Bottles, PCTFE | 0 | Only target packages present | ❌ |
| 6 | OFG Tablets | 18M→18M | CFAF (from Bottles) | 3 | Same-timepoint + cross-package | ✅ |
| 7 | OFG Tablets | 18M→24M | Bottles, Bulk, CFAF | — | Multi-prior merge (2 prior folders → 1 current) | ✅ |
| 8 | OFG Tablets | 18M→24M | Bottles (0.2% SDS disso) | — | Dissolution-specific DIR | ✅ |
| 9 | OFG Tablets | 18M→24M | CFF (0.2% SDS disso) | — | Dissolution-specific DIR, different author | ✅ |

### Which Pairs to Run by Feature

| If you changed... | Run pair(s) | Why |
|-------------------|-------------|-----|
| Any script (baseline sanity) | **1** | Ground truth — all 8 tasks, standard workflow |
| `delete_sections.py` or package normalization | **2**, **3** | Heavy vs light deletion |
| `figures.py` (heading similarity, matching) | **1**, **6**, **7** | Normal match, cross-package, multi-prior merge |
| `tables.py` (inference, filtering) | **1**, **6**, **8**, **9** | Normal, cross-package, dissolution-specific |
| `timepoint_text.py` | **1**, **5**, **7** | Standard progression at different timepoint ranges |
| Accelerated condition logic | **1**, **6** | >6M skip vs same-timepoint never-skip |
| Same-timepoint / cross-package | **6** | Only pair with both special modes |
| `author_reviewer.py` | **1** | Personnel updates are product-agnostic |
| 24M timepoint progression | **7**, **8**, **9** | All three exercise the 18M→24M path |
| Dissolution-specific reports | **8**, **9** | 0.2% SDS dissolution DIRs (Bottles and CFF) |
| Multi-prior folder handling | **7** | Two prior vendor folders merged into one current |

### Unit Tests

```bash
cd ~/skills/stability-report-update
python -m unittest discover tests/ -v    # 108 tests
```

---

## Known Acceptable Differences vs Reference

- **Off-by-1 table** in pair-1 (manually-added 4th reviewer) and pair-2 (manually-added archival table) — not automatable
- **Substitution diffs** — narrative text, DUCT project naming, data source filenames that differ between template and final reference
- **Pair-4 specifics:** unfuzzable filename, reference has 2 tech reviewers (skill supports 1), reference has 1 manually-deleted image

---

## Areas to Optimize

| Area | File(s) | Notes |
|------|---------|-------|
| **Figures matching** | `figures.py` | 3-tier heading similarity pipeline is the most complex logic |
| **Tables inference** | `tables.py` | Infers aggregation/rounding rules; could be more robust |
| **Description triggering** | `SKILL.md` | The skill-creator has a description optimization loop that hasn't been run yet |
| **Test coverage** | `author_reviewer.py`, `delete_sections.py` | No dedicated unit tests yet |
| **Personnel directory** | `author_reviewer.py` | `PERSONNEL` dict is hardcoded; could be externalized to a config file |
| **Error recovery** | `orchestrate.py` | Currently stops on first task failure; could be more resilient |
