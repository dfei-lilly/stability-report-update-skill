# Stability Report Update Skill

A Claude Code skill that automates updating stability DIR reports (Word `.docx`) from one timepoint to the next. Produces tracked-changes drafts that statisticians review in Word.

## Quick Start

### 1. Install the skill

Copy files to the two required locations:

```bash
# Profile location (triggers the skill in Claude Code)
mkdir -p ~/.claude/skills/stability-report-update/scripts
cp skill/SKILL.md ~/.claude/skills/stability-report-update/SKILL.md
cp scripts/*.py ~/.claude/skills/stability-report-update/scripts/

# Runtime location (orchestrator reads scripts from here)
mkdir -p ~/skills/stability-report-update/scripts
cp scripts/*.py ~/skills/stability-report-update/scripts/

# Standalone author skill (optional)
mkdir -p ~/.claude/skills/stability-author
cp standalone-skills/stability-author/SKILL.md ~/.claude/skills/stability-author/SKILL.md

# Tests
mkdir -p ~/skills/stability-report-update/tests
cp tests/*.py ~/skills/stability-report-update/tests/
```

### 2. Set up example pairs for testing

The example pairs contain large vendor data files (8GB total) that are excluded from this repo. Copy them from the shared filesystem:

```bash
cp -r /home/c210435/stability-report-update-skill-dev/examples/ ./examples/
```

### 3. Run tests

```bash
cd ~/skills/stability-report-update
python -m unittest discover tests/ -v    # 108 unit tests
```

### 4. Run against an example pair

```bash
cd examples/pair-1
python ~/skills/stability-report-update/scripts/orchestrate.py \
  --prior-folder "prior/CNW_2025_OFG_Tablets_12M_CFAF_Bulk_Primary_Stability" \
  --current-folder "current/DF_2026_OFG_Tablets_18M_CFAF_Bulk_Primary_Stability" \
  --timepoint "18M" --old-timepoint "12M" \
  --author "Dongling" --di-reviewer "Chad" --tech-reviewer "Chad" \
  --working-dir "." --packages "CFAF, Bulk"
```

## Documentation

- **[Architecture Overview](docs/skill-architecture-overview.md)** — full walkthrough of the skill structure, pipeline, 8 tasks, key concepts, and testing matrix
- **[Example Pairs README](examples/README.md)** — detailed description of all 9 test pairs with run commands and known diffs
- **[CLAUDE.md](CLAUDE.md)** — development workspace instructions for Claude Code

## Repository Structure

```
├── scripts/                           All Python task scripts (10 files)
│   ├── orchestrate.py                 Main orchestrator — runs all 8 tasks
│   ├── author_reviewer.py             Task 1: personnel names/titles/org
│   ├── data_hash.py                   Task 2: MD5 hashes
│   ├── golf_paths.py                  Task 3: golf:\\ paths
│   ├── filenames.py                   Task 4: filename references
│   ├── timepoint_text.py              Task 5: timepoint text
│   ├── figures.py                     Task 6: stability plot images
│   ├── tables.py                      Task 7: summary statistics
│   ├── delete_sections.py             Task 8: non-target sections
│   └── shared_utils.py                Shared utilities
├── skill/SKILL.md                     Main skill definition (8-task orchestrator)
├── standalone-skills/
│   └── stability-author/SKILL.md      Standalone personnel-only skill
├── tests/                             Unit tests (108 tests)
├── docs/                              Architecture docs
├── examples/                          9 test pairs (data files excluded from git)
├── notes/                             Development session notes
└── CLAUDE.md                          Dev workspace config
```

## Keeping Files in Sync

The skill runs from two locations. After editing any script, sync both:

```bash
cp ~/skills/stability-report-update/scripts/<file>.py \
   ~/.claude/skills/stability-report-update/scripts/<file>.py
```
