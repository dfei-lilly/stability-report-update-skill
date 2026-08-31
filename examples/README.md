# Example Pairs — Test Case Reference

Each pair exercises a specific combination of skill features. Use this to select which pairs to run when testing changes.

---

## Summary Matrix

| Pair | Product | Timepoint | Packages | Mode | Sections Deleted | Reference |
|------|---------|-----------|----------|------|-----------------|-----------|
| 1 | OFG Tablets | 12M → 18M | CFAF, Bulk | Normal progression | 0 (all target) | ✅ |
| 2 | OFG Capsules | 12M → 18M | Bottles | Normal progression | 3 (HDPE, PCTFE, Bulk) | ✅ |
| 3 | OFG Capsules | 12M → 18M | Blisters, Bulk | Normal progression | 1 (HDPE only) | ✅ |
| 4 | OFG Capsules | 12M → 18M → 24M | Blisters | Normal (2-step prior) | Multiple | ✅ |
| 5 | OFG Tablets | 12M → 18M | Bottles, PCTFE | Normal progression | 0 (only target present) | ❌ |
| 6 | OFG Tablets | 18M → 18M | CFAF (from Bottles) | Same-timepoint + cross-package | 3 (HDPE sections) | ✅ |
| 7 | OFG Tablets | 18M → 24M | Bottles + CFAF + Bulk | Multi-prior (2 runs) | 1 (PCTFE in Bottles run) | ✅ |
| 8 | OFG Tablets (0.2% SDS) | 18M → 24M | Bottles | Normal progression | 0 | ✅ |
| 9 | OFG Tablets (0.2% SDS) | 18M → 24M | CFAF (from Bottles) | Cross-package | 0 | ✅ |

---

## Feature Coverage

| Feature | Best pair(s) to test |
|---------|---------------------|
| Normal timepoint progression | 1, 2, 3, 5, 8 |
| Accelerated condition skip (tables, >6M) | 1, 2, 3, 5, 8 (all >6M) |
| Accelerated condition NOT skipped (<= 6M) | 4 (6M→12M prior step) |
| Section deletion (delete-sections task) | 2 (deletes 3), 3 (deletes 1), 6 (deletes 3), 7-Bottles (deletes PCTFE) |
| No section deletion (all packages are target) | 1, 5, 8, 9 |
| Same-timepoint data refresh | 6 |
| Cross-package replacement | 6 (Bottles→CFAF), 7-CFAF/Bulk (Bottles→CFAF+Bulk), 9 (Bottles→CFAF) |
| Title-based figure matching | 7, 8, 9 (all use new title-based pipeline) |
| Multiple packages in filter | 1 (CFAF+Bulk), 3 (Blisters+Bulk), 5 (Bottles+PCTFE), 7-CFAF/Bulk (CFAF+Bulk) |
| Single package in filter | 2 (Bottles only), 6 (CFAF only), 7-Bottles, 8, 9 |
| Reference comparison available | 1, 2, 3, 4, 6, 7, 8, 9 |
| 2-step prior chain (prior has 2 folders) | 4 |
| Multi-prior (2 separate runs required) | 7 |

---

## Detailed Pair Descriptions

### Pair 1 — Normal update, multi-package, no deletions

| | |
|---|---|
| **Product** | OFG Tablets |
| **Transition** | 12M → 18M |
| **Packages** | CFAF Blister + Bulk Simulator |
| **Prior folder** | `CNW_2025_OFG_Tablets_12M_CFAF_Bulk_Primary_Stability` |
| **Current folder** | `DF_2026_OFG_Tablets_18M_CFAF_Bulk_Primary_Stability` |
| **What it tests** | Standard timepoint progression with 2 target packages. Since all sections in the report belong to CFAF or Bulk, no sections are deleted. Tests figures, tables, timepoint text, filenames, hashes, golf paths, and author/reviewer. |
| **Known diffs vs reference** | Off-by-1 review table (reference has manually-added 4th reviewer row) |

---

### Pair 2 — Normal update, section deletion (3 sections)

| | |
|---|---|
| **Product** | OFG Capsules |
| **Transition** | 12M → 18M |
| **Packages** | Bottles (HDPE 125cc) |
| **Prior folder** | `CNW_2025_OFG_Capsules_12M_Primary_Stability` |
| **Current folder** | `CNW_2025_OFG_Capsules_18M_Bottles_Primary_Stability` |
| **What it tests** | Single-package filter with heavy section deletion. The prior report has ALL packages (Bottles, PCTFE, CFAF, Bulk); only Bottles sections kept. Tests delete-sections normalization (`Bottles` → `HDPE (125cc)`). |
| **Known diffs vs reference** | Off-by-1 table (manually-added archival table) |

---

### Pair 3 — Normal update, section deletion (1 section)

| | |
|---|---|
| **Product** | OFG Capsules |
| **Transition** | 12M → 18M |
| **Packages** | Blisters (PCTFE + CFAF) + Bulk Simulator |
| **Prior folder** | `CNW_2025_OFG_Capsules_12M_Primary_Stability` (same as pair-2) |
| **Current folder** | `CNW_2026_OFG_Capsules_18M_Blisters_Bulk_Primary_Stability` |
| **What it tests** | Multi-package filter with "Blisters" expanding to PCTFE+CFAF. Only HDPE section deleted. Tests the `Blisters` → `PCTFE Blister + CFAF Blister` normalization. |
| **Known diffs vs reference** | Minor substitution diffs |

---

### Pair 4 — Two-step prior, 6M→12M base

| | |
|---|---|
| **Product** | OFG Capsules |
| **Transition** | 12M → 18M → 24M (prior has both 12M and 18M folders) |
| **Packages** | Blisters (PCTFE + CFAF) |
| **Prior folders** | `CNW_2025_OFG_Capsules_12M_Primary_Stability` + `CNW_2026_OFG_Capsules_18M_Blisters_Bulk_Primary_Stability` |
| **Current folder** | `DF_2026_OFG_Capsules_24M_Blisters_Primary_Stability` |
| **What it tests** | The first step (6M→12M) exercises accelerated conditions NOT being skipped (timepoint ≤ 6M). The second step (18M→24M) has them skipped. Also tests the 2-folder prior structure. |
| **Known diffs vs reference** | Unfuzzable filename (`2026_02_18 PS campaign...xlsx`), reference has 2 tech reviewers (skill supports 1), 1 manually-deleted image in reference |

---

### Pair 5 — Normal update, all target packages present (no deletions)

| | |
|---|---|
| **Product** | OFG Tablets |
| **Transition** | 12M → 18M |
| **Packages** | Bottles (HDPE) + PCTFE Blister |
| **Prior folder** | `CNW_2025_OFG_Tablets12M_Bottles_PCTFE_Primary_Stability` |
| **Current folder** | `DF_2026_OFG_Tablets18M_Bottles_PCTFE_Primary_Stability` |
| **What it tests** | Two-package filter where the report ONLY has those two packages — verifies delete-sections correctly identifies nothing to delete. No reference file available (use for quick smoke testing). |
| **Known diffs** | No reference to compare against |

---

### Pair 6 — Same-timepoint + cross-package (Bottles → CFAF)

| | |
|---|---|
| **Product** | OFG Tablets (0.2% SDS Dissolution) |
| **Transition** | 18M → 18M (same timepoint) |
| **Packages** | CFAF (replacing Bottles template sections) |
| **Prior folder** | `DF_2026_OFG_Tablets18M_0.2_SDS_Disso_Bottles_Primary_Stability` |
| **Current folder** | `DF_2026_OFG_Tablets_18M_0.2_SDS_Dissolution_CFF_Primary_Stability` |
| **What it tests** | Combined same-timepoint + cross-package scenario. Tests: (1) timepoint-text skipped, (2) accelerated conditions NOT skipped, (3) `--cross-package` auto-detected and passed, (4) figures use `ignore_package=True` for heading matching, (5) tables bypass caption filter, (6) Tier 3 heading fallback for DIR↔Prior matching, (7) HDPE sections deleted. |
| **Known diffs** | N/A — new feature, first test case |

---

### Pair 7 — Multi-prior, 3 packages from 2 separate DIR reports

| | |
|---|---|
| **Product** | OFG Tablets |
| **Transition** | 18M → 24M |
| **Packages** | Bottles + CFAF Blister + Bulk Simulator (across 2 priors) |
| **Prior folders** | `DF_2026_OFG_Tablets18M_Bottles_PCTFE_Primary_Stability` (Bottles+PCTFE) + `DF_2026_OFG_Tablets_18M_CFAF_Bulk_Primary_Stability` (CFAF+Bulk) |
| **Current folder** | `DF_2026_OFG_Tablets_24M_PS_Bottles_Bulk_CFAF` |
| **What it tests** | Multi-prior scenario where no single prior contains all target packages. Requires 2 separate skill runs: (1) Bottles-only run from Bottles/PCTFE prior (deletes PCTFE), (2) CFAF+Bulk cross-package run from CFAF/Bulk prior. Tests title-based figure matching across both runs, cross-package mode for the CFAF/Bulk run, and section deletion in the Bottles run. |
| **Run commands** | See below |
| **Known diffs vs reference** | Reference combines all 3 packages in one document; substitution diffs are DUCT project names, zip filenames, data source descriptions (manual edits). |

**Run 1 — Bottles (from Bottles/PCTFE prior):**
```bash
python ~/skills/stability-report-update/scripts/orchestrate.py \
  --prior-folder "prior/DF_2026_OFG_Tablets18M_Bottles_PCTFE_Primary_Stability" \
  --current-folder "current/DF_2026_OFG_Tablets_24M_PS_Bottles_Bulk_CFAF" \
  --prior-report "DIR_Form_OFG_Tablet_18M_Bottles_PCTFE_PS.docx" \
  --timepoint "24M" --old-timepoint "18M" \
  --author "Dongling" --di-reviewer "Chad" --tech-reviewer "Chad" \
  --working-dir "." --packages "Bottles"
```

**Run 2 — CFAF + Bulk (cross-package from CFAF/Bulk prior):**
```bash
python ~/skills/stability-report-update/scripts/orchestrate.py \
  --prior-folder "prior/DF_2026_OFG_Tablets_18M_CFAF_Bulk_Primary_Stability" \
  --current-folder "current/DF_2026_OFG_Tablets_24M_PS_Bottles_Bulk_CFAF" \
  --prior-report "DIR_Form_OFG_Tablet_CFF_Bulk_18M_Primary_Stability_12May2026.docx" \
  --timepoint "24M" --old-timepoint "18M" \
  --author "Dongling" --di-reviewer "Chad" --tech-reviewer "Chad" \
  --working-dir "." --packages "CFAF, Bulk"
```

---

### Pair 8 — Normal progression, 0.2% SDS Dissolution (Bottles)

| | |
|---|---|
| **Product** | OFG Tablets (0.2% SDS Dissolution) |
| **Transition** | 18M → 24M |
| **Packages** | Bottles (HDPE) |
| **Prior folder** | `DF_2026_OFG_Tablets18M_0.2_SDS_Disso_Bottles_Primary_Stability` |
| **Current folder** | `DF_2026_OFG_Tablets_24M_0.2_SDS_Disso_Bottles_Primary_Stability` |
| **What it tests** | Standard timepoint progression with title-based figure matching. Single package, no section deletion needed. Tests the new title-based matching pipeline end-to-end on a straightforward case (16/16 figures matched). |
| **Known diffs vs reference** | 22 substitutions (DUCT project names, zip filenames, grammar edits); 134 manual additions in reference (revision history, additional dose strengths 0.8/2.5/5.5 mg, new data source documentation) |

---

### Pair 9 — Cross-package (Bottles → CFAF), 0.2% SDS Dissolution

| | |
|---|---|
| **Product** | OFG Tablets (0.2% SDS Dissolution) |
| **Transition** | 18M → 24M |
| **Packages** | CFAF (cross-package from Bottles prior) |
| **Prior folder** | `DF_2026_OFG_Tablets_18M_0.2_SDS_Dissolution_CFF_Primary_Stability` |
| **Current folder** | `CNW_2026_OFG_Tablets_24M_0.2_SDS_Dissolution_CFF_Primary_Stability` |
| **Prior report** | `DIR_Form_OFG_Tablet_18M_0.2SDS_CFF_disso_Primary_Stability.docx` |
| **What it tests** | Cross-package with timepoint progression (unlike pair-6 which is same-timepoint). Tests title-based matching with `ignore_package=True` and humidity skip in `fields_match()`. 16/17 figures matched (1 unmatched is a non-figure screenshot). No section deletion needed. |
| **Known diffs vs reference** | 19 substitutions (DUCT project names, "through up to 24 months" phrasing); 179 manual additions in reference (revision history, data source documentation, column assignments) |

**Run command:**
```bash
python ~/skills/stability-report-update/scripts/orchestrate.py \
  --prior-folder "prior/DF_2026_OFG_Tablets_18M_0.2_SDS_Dissolution_CFF_Primary_Stability" \
  --current-folder "current/CNW_2026_OFG_Tablets_24M_0.2_SDS_Dissolution_CFF_Primary_Stability" \
  --prior-report "DIR_Form_OFG_Tablet_18M_0.2SDS_CFF_disso_Primary_Stability.docx" \
  --timepoint "24M" --old-timepoint "18M" \
  --author "Dongling" --di-reviewer "Chad" --tech-reviewer "Chad" \
  --working-dir "." --packages "CFAF"
```

---

## Running a Pair

```bash
cd examples/pair-N
python ~/skills/stability-report-update/scripts/orchestrate.py \
  --prior-folder "prior/<folder>" \
  --current-folder "current/<folder>" \
  --timepoint "<new>M" \
  --old-timepoint "<old>M" \
  --author "Dongling" \
  --di-reviewer "Chad" \
  --tech-reviewer "Chad" \
  --working-dir "." \
  --packages "<packages>"
```

Compare against reference (if available):
```bash
python ~/.claude/skills/compare-reports/scripts/compare_reports.py \
  "<draft>.docx" "reference/<ref>.docx" --mode full
```
