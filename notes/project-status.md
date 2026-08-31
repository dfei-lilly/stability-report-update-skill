# Stability Report Update Skill — Project Status

## Current Task
None — ready for next task

## Completed
- Rewrote figures.py from multi-tier pixel/hash matching to title-based semantic field matching
- Created `parse_dir_caption()`, `parse_vendor_heading()`, and `fields_match()` for field-by-field comparison
- Fixed duplicate image extraction (skip `<w:del>` blocks)
- Fixed package normalization (HDPE/Bottles → 'bottle')
- Fixed property name prefix differences (strip "Dissolution" prefix)
- Fixed cross-package humidity mismatch (skip humidity in cross-package mode)
- Verified all 108 unit tests pass
- Tested pairs 1-6: 100% match rate on all stability plots
- Tested pairs 7-9: all correct (48/48, 36/73 correct scope, 16/16, 16/17)
- Ran compare-reports against references for pairs 7-9: all diffs are expected (manual content, narrative text)
- Added pairs 7-9 to `examples/README.md` with full documentation
- Created 8 standalone mini-skills under `~/.claude/skills/stability-*`:
  - stability-figures, stability-tables, stability-author, stability-hash
  - stability-golf-paths, stability-filenames, stability-timepoint, stability-delete-sections

## In Progress
- Nothing actively in progress

## Next Steps
1. Expand property name coverage in `parse_dir_caption()` (user mentioned this as a desired improvement)
2. Consider removing legacy `heading_similarity()` function (lines 346-441 in figures.py) — no longer used by the title-based pipeline
3. Update the parent SKILL.md to reference the new mini-skills and update figures task description (title-based matching, not pixel-based)
4. Sync the profile copy: `cp ~/skills/stability-report-update/scripts/figures.py ~/.claude/skills/stability-report-update/scripts/figures.py`
5. Commit all changes to the dev repo

## Known Issues
- Pair-7 is inherently a 2-run scenario (multi-prior) — no single-invocation support yet
- Pair-8/9 references have substantial manual additions (134-179 paragraphs) that can't be automated
- `heading_similarity()` is dead code in figures.py (kept for potential future fallback use)
