---
name: stability-report-update
description: "Full stability DIR report update orchestrator. Runs 8 sequential tasks: personnel, data hashes, golf paths, filenames, timepoint text, figures, tables, and section deletion. Produces a tracked-changes DRAFT docx. Supports package-scope filtering — auto-detects from folder name, then asks the user to confirm or choose any combination of packages via popup. Also supports same-timepoint data refresh — when prior and current folders share the same timepoint, automatically skips timepoint-text and processes all conditions including accelerated. Use this skill whenever someone mentions updating a DIR, stability report update, next timepoint, data refresh, re-running figures, replacing package scope, moving from 12M to 18M (or same timepoint), full DIR update, orchestrating a DIR update, or running the stability update pipeline. This is the go-to skill for any stability DIR report modification — even if the user only mentions one aspect (like updating figures or changing the timepoint), use this skill because it handles everything in the correct order."
license: Proprietary - Eli Lilly internal use only.
---

# Stability Report Update

Updates a stability DIR report from one timepoint to the next, or refreshes data within the same timepoint. Produces a tracked-changes `_DRAFT.docx` that the user reviews in Word.

The orchestrator runs 8 tasks sequentially, each building on the previous. All edits appear as Word tracked changes so the reviewer can accept/reject each modification.

**Same-timepoint support:** When `old_timepoint == new_timepoint` (auto-detected from folder names), the skill runs as a "data refresh" — all tasks execute except timepoint-text (no text change needed), and accelerated conditions (40°C/75% RH) are never skipped for tables (vendor may have corrected that data).

---

## Workflow: Auto-Discover → Collect Inputs → Run

1. Auto-discover folders and timepoints from the working directory
2. Read current personnel from the DRAFT docx
3. Collect confirmations via ONE `AskUserQuestion` call (up to 5 questions — personnel keep/change + folders + timepoint + packages + reference)
4. If personnel change requested, ask for new names in plain text
5. Run `orchestrate.py` immediately — no further confirmations
6. Optionally run `compare-reports` if user requested reference comparison
7. Move all output files to `./output/`
8. Display the summary

After collecting inputs, proceed directly to execution. The user has already confirmed everything they need to confirm.

---

## Step 0: Auto-Discover

Scan the working directory silently before showing any prompts:

```bash
ls ./prior/       # Single subdirectory = prior vendor folder
ls ./current/     # Single subdirectory = current vendor folder
ls ./reference/*.docx 2>/dev/null   # Optional reference file
```

Extract from folder names:
- **old_timepoint**: regex `(\d+)M` from prior folder name
- **new_timepoint**: regex `(\d+)M` from current folder name
- **detected_packages**: check current folder name for package keywords (Bottles, HDPE, CFAF, PCTFE, Bulk, Blister)

If `./prior/` or `./current/` are missing, inform the user and stop.

---

## Step 1a: Read Current Personnel

After auto-discovery, read current personnel from the DRAFT docx:

```bash
python ~/skills/stability-report-update/scripts/author_reviewer.py <working_dir> --read-current
```

Parse the JSON block between `__CURRENT_PERSONNEL__` and `__END_CURRENT_PERSONNEL__` markers. Extract the `author`, `di_reviewer`, and `tech_reviewer` objects (each has `name`, `title`, `org`).

If the command fails (no DRAFT docx found), set `personnel_found = false` — Step 1b will skip the personnel question and Step 1c will ask for names in plain text.

---

## Step 1b: Confirm Settings (ONE popup — up to 5 questions)

Use `AskUserQuestion` with up to 5 questions. If `personnel_found`, include the personnel question first; otherwise skip it (4 questions).

**Question 0 (Personnel) — only if personnel were read successfully:**
- Header: "Personnel"
- Question: "Current DIR personnel — keep or change?"
- Options:
  - `"Keep current (Recommended)"` — description: `"Author: <author_name> | DI Reviewer: <di_name> | Tech Reviewer: <tech_name>"`
  - `"Change personnel"` — description: `"I'll ask for new names after this popup"`

**Question 1 (Folders):**
- Header: "Folders"
- Question: "Confirm prior and current vendor folders?"
- Options:
  - `"Correct (Recommended)"` — description shows both folder names
  - `"Wrong folders"` — user needs to specify different paths

**Question 2 (Timepoint):**
- Header: "Timepoint"
- If `old_timepoint == new_timepoint` (same-timepoint refresh):
  - Question: "Same timepoint detected (`<tp>M`). Running as data refresh — figures, tables, and metadata will be updated; timepoint text will be skipped."
  - Options:
    - `"<tp>M data refresh (Recommended)"` — same timepoint, updated vendor data
    - `"Other"` — specify a different target timepoint (reverts to normal progression)
- If `old_timepoint != new_timepoint` (normal progression):
  - Question: "Confirm timepoint update: `<old>M` → `<new>M`?"
  - Options:
    - `"<old>M → <new>M (Recommended)"` — detected from folder names
    - `"Other"` — specify different timepoint

**Question 3 (Package Scope):**
- Header: "Packages"
- Question: "Which packages should figures/tables be updated for?"
- Options (if package keyword detected in folder name):
  - `"<detected_package(s)> only (Recommended)"` — detected from folder name
  - `"All packages"` — update everything
  - `"Custom combination"` — user types comma-separated packages via Other
- Options (if NO keyword detected):
  - `"All packages (Recommended)"` — no specific package detected
  - `"Custom combination"` — user types which packages via Other

This question is always shown — user must confirm even when auto-detected.

**Same-timepoint + package scope replacement:**
If same-timepoint is detected AND the user selects packages DIFFERENT from those in the prior report, this is a package scope replacement. The orchestrator will update figures/tables for the new package set and delete sections for the old packages. The prior report must already contain content for the target packages — the skill updates existing content but cannot create new sections from scratch.

**Question 4 (Reference):**
- Header: "Reference"
- Question: "Compare output against a reference file after update?"
- Options (if reference file found):
  - `"Yes — compare against <filename>"` — run compare-reports after update
  - `"No comparison needed"` — skip
- Options (if no reference):
  - `"Yes — I'll provide the path"` — run compare-reports
  - `"No comparison needed"` — skip

---

## Step 1c: Resolve Personnel

Based on the personnel answer from Step 1b:

- **"Keep current"**: Use the names read in Step 1a for `--author`, `--di-reviewer`, `--tech-reviewer`.
- **"Change personnel"** (or personnel not found): Ask the user in plain text:
  > "Who is the **Author**, **DI Reviewer**, and **Tech Reviewer** for this update?"
  > (Type names separated by | or comma, e.g.: `Dongling Fei | Sakshi | Chad`)
  Wait for their response. Parse names by splitting on `|`, `,`, or `and`. If fewer than 3 names provided, ask which role each fills.

---

## Step 2: Run Orchestrator

Parse personnel from Step 1c, then run immediately:

```bash
python ~/skills/stability-report-update/scripts/orchestrate.py \
  --prior-folder "<prior_folder>" \
  --current-folder "<current_folder>" \
  --timepoint "<new_timepoint>" \
  --author "<author>" \
  --di-reviewer "<di_reviewer>" \
  --tech-reviewer "<tech_reviewer>" \
  --working-dir "." \
  --old-timepoint "<old_timepoint>" \
  --packages "<packages>"
```

Omit `--packages` entirely if user chose "All packages".

---

## Step 3: Compare Reports (if requested)

Only if user chose "Yes" in question 4:

```bash
python ~/.claude/skills/compare-reports/scripts/compare_reports.py \
  "<draft_path>" "<reference_path>" --mode full
```

---

## Step 3b: Move Output to `./output/`

After the orchestrator (and optional comparison) completes, move all generated files to `./output/`:

```bash
mkdir -p ./output
mv ./*_DRAFT.docx ./output/
mv ./*_ACCEPTED.docx ./output/ 2>/dev/null
mv ./comparison_report_*.md ./output/ 2>/dev/null
```

This keeps the working directory clean and puts all outputs in a predictable location.

---

## Step 4: Report Results

Parse `__ORCHESTRATOR_RESULT__` JSON from stdout. Display:

```
STABILITY REPORT UPDATE COMPLETE
Output: ./output/<filename>
Tasks: N/N passed (Xs)
Package filter: <packages or "All">
```

If compare-reports ran:
```
COMPARISON: <PASS/FAIL> — see ./output/comparison_report_*.md
```

---

## What the 8 Tasks Do

| # | Task | What it updates |
|---|------|----------------|
| 1 | author-reviewer | Cover page author, 3 review tables (name, title, org) |
| 2 | data-hash | MD5 hash values from DIR_Pkg and stab_package zips |
| 3 | golf-paths | `golf:\golf.grp\CMC_STATS\<folder>` path references |
| 4 | update-filenames | All filename references (fuzzy-matched between prior/current) |
| 5 | timepoint-text | Written-out and numeric timepoint text (e.g., "Twelve Month" → "Eighteen Month") |
| 6 | update-figures | Stability plot images (matched DIR→Prior→Current via binary hash + heading similarity) |
| 7 | update-tables | Summary statistics table values (per-table logic inference from prior vendor data) |
| 8 | delete-sections | Non-target package Heading1 sections (wrapped in tracked-change deletions) |

Tasks 6-8 only apply package filtering when `--packages` is specified. Without it, all packages are updated and no sections are deleted.

---

## Testing Against Example Pairs

Test examples live in `~/stability-report-update-skill-dev/examples/`. After making changes to any script, run the relevant pairs to verify correctness.

### Pair 1 — Ground Truth (MUST PASS for any change)

**Always run pair-1 first.** It exercises all 8 tasks in the standard workflow (12M→18M, multi-package, no section deletions). Any regression to core functionality will show here.

```bash
cd ~/stability-report-update-skill-dev/examples/pair-1
python ~/skills/stability-report-update/scripts/orchestrate.py \
  --prior-folder "prior/CNW_2025_OFG_Tablets_12M_CFAF_Bulk_Primary_Stability" \
  --current-folder "current/DF_2026_OFG_Tablets_18M_CFAF_Bulk_Primary_Stability" \
  --timepoint "18M" --old-timepoint "12M" \
  --author "Dongling" --di-reviewer "Chad" --tech-reviewer "Chad" \
  --working-dir "." --packages "CFAF, Bulk"
```

Compare: `python ~/.claude/skills/compare-reports/scripts/compare_reports.py "<draft>.docx" "reference/DIR_Form_OFG_Tablet_CFF_Bulk_18M_Primary_Stability_12May2026.docx" --mode full`

### Which Pairs to Run by Feature

| If you changed... | Run pair(s) | Why |
|-------------------|-------------|-----|
| Any script (baseline sanity) | **1** | Ground truth — all 8 tasks, standard workflow |
| `delete_sections.py` or package normalization | **2** (deletes 3 sections), **3** (deletes 1) | Heavy vs light deletion; tests normalization |
| `figures.py` (heading similarity, matching) | **1**, **6** | 1 = normal match; 6 = Tier 3 fallback + cross-package |
| `tables.py` (inference, filtering) | **1**, **6** | 1 = normal; 6 = cross-package data override |
| `timepoint_text.py` | **1**, **5** | Standard progression with timepoint text changes |
| Accelerated condition logic | **1** (>6M, skips accel), **6** (same-tp, never skips) |  |
| Same-timepoint / data refresh logic | **6** | Only same-timepoint pair (18M→18M) |
| Cross-package detection | **6** | Only cross-package pair (Bottles→CFAF) |
| `orchestrate.py` (task ordering, CLI) | **1**, **6** | Cover both normal and special modes |
| `author_reviewer.py` | **1** | Personnel updates are product-agnostic |
| `data_hash.py`, `golf_paths.py`, `filenames.py` | **1** | These are straightforward — ground truth suffices |

### Quick Reference

| Pair | Mode | Packages | Sections Deleted | Reference |
|------|------|----------|-----------------|-----------|
| 1 | 12M→18M normal | CFAF, Bulk | 0 | ✅ |
| 2 | 12M→18M normal | Bottles | 3 | ✅ |
| 3 | 12M→18M normal | Blisters, Bulk | 1 | ✅ |
| 4 | 12M→18M→24M (2-step) | Blisters | Multiple | ✅ |
| 5 | 12M→18M normal | Bottles, PCTFE | 0 | ❌ |
| 6 | 18M→18M same-tp + cross-pkg | CFAF (from Bottles) | 3 | ✅ |

### Unit Tests

Always run after script changes:
```bash
cd ~/skills/stability-report-update
python -m unittest discover tests/ -v
```
