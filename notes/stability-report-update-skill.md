# Stability Report Update Skill — Raw Content

Source: `/home/c210435/.claude/skills/stability-report-update`
Captured: 2026-06-16

Updates a stability DIR report from one timepoint to the next. Produces a tracked-changes `_DRAFT.docx` that the user reviews in Word.

The orchestrator runs 8 tasks sequentially, each building on the previous. All edits appear as Word tracked changes so the reviewer can accept/reject each modification.

---

## Workflow: Auto-Discover → Collect Inputs → Run

1. Auto-discover folders and timepoints from the working directory
2. Ask for personnel names (plain text prompt)
3. Collect confirmations via ONE `AskUserQuestion` call (4 questions)
4. Run `orchestrate.py` immediately — no confirmations, no intermediate text
5. Optionally run `compare-reports` if user requested reference comparison
6. Display the summary

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

## Step 1a: Personnel (plain text prompt)

Ask the user directly in chat:

> "Who is the **Author**, **DI Reviewer**, and **Tech Reviewer** for this update?"
> (Type names separated by | or comma, e.g.: `Dongling Fei | Sakshi | Chad`)

Wait for their response. Parse names by splitting on `|`, `,`, or `and`. If fewer than 3 names provided, ask which role each fills.

---

## Step 1b: Confirm Settings (ONE popup — 4 questions)

Use `AskUserQuestion` with exactly 4 questions:

**Question 1 (Folders):**
- Header: "Folders"
- Question: "Confirm prior and current vendor folders?"
- Options:
  - `"Correct (Recommended)"` — description shows both folder names
  - `"Wrong folders"` — user needs to specify different paths

**Question 2 (Timepoint):**
- Header: "Timepoint"
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

## Step 2: Run Orchestrator

Parse personnel from Step 1a, then run immediately:

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

## Step 4: Report Results

Parse `__ORCHESTRATOR_RESULT__` JSON from stdout. Display:

```
STABILITY REPORT UPDATE COMPLETE
Output: <filename>
Tasks: N/N passed (Xs)
Package filter: <packages or "All">
```

If compare-reports ran:
```
COMPARISON: <PASS/FAIL> — see comparison_report_*.md
```

---

## The 8 Orchestrator Tasks

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

## Key Technical Details

### Tracked Changes
All modifications appear as Word tracked changes (insertions/deletions) so the reviewer can accept/reject each one in Microsoft Word.

### Package Keywords
Recognized package types: Bottles, HDPE, CFAF, PCTFE, Bulk, Blister.

### Timepoint Detection
Regex `(\d+)M` extracts numeric month values from folder names.

### Folder Structure Expected
```
working-directory/
├── prior/
│   └── <vendor_folder_name>/
├── current/
│   └── <vendor_folder_name>/
└── reference/                   # optional
    └── <reference>.docx
```

### Dependencies
- Python orchestrator: `~/skills/stability-report-update/scripts/orchestrate.py`
- Compare reports: `~/.claude/skills/compare-reports/scripts/compare_reports.py`
- Output: `_DRAFT.docx` in working directory
