---
name: stability-author
description: "Standalone skill to update author and reviewer names/titles in a DIR stability report. Replaces personnel in the cover page author field and 3 review tables (DI reviewer, Tech reviewer, Author rows — updating name, title, and organization). Use when someone says: 'update author only', 'change reviewer names', 'update personnel', 'fix author name', 'change who reviewed', 'just the author task', 'update names in DIR', 'keep current author', 'keep reviewers', 'check who reviewed', or 'show current personnel'. For a full 8-task pipeline update, use the stability-report-update skill instead."
---

# Stability Author/Reviewer — Standalone Update

Updates author and reviewer names, titles, and organization in the DIR report cover page and review tables.

## When to Use

- Checking or confirming current personnel in a DIR
- Keeping current personnel unchanged (most common — just confirm and move on)
- Changing personnel after a full run
- Fixing a name/title typo
- Re-assigning the DIR to a different author or reviewer

## Required Files

| File | Purpose |
|------|---------|
| `DIR_Form_*_DRAFT.docx` | The DIR report to read/update |

## Workflow

### Step 1: Read Current Personnel

Run the read-current command to discover who is currently in the document:

```bash
cd <working_dir>
python ~/skills/stability-report-update/scripts/author_reviewer.py . --read-current
```

Parse the JSON block between `__CURRENT_PERSONNEL__` and `__END_CURRENT_PERSONNEL__` markers in the output. Extract the `author`, `di_reviewer`, and `tech_reviewer` objects (each has `name`, `title`, `org`).

If the command fails (no DRAFT docx found), skip to Step 3 directly — ask the user for all three names.

### Step 2: Ask User — Keep or Change

Use `AskUserQuestion` with 1 question:

- **Header:** `"Personnel"`
- **Question:** `"Current DIR personnel — keep or change?"`
- **Options:**
  - `"Keep current (Recommended)"` — description: `"Author: <author_name> | DI Reviewer: <di_name> | Tech Reviewer: <tech_name>"`
  - `"Change personnel"` — description: `"I'll ask for new names"`

### Step 3: Handle the User's Choice

**If "Keep current":**

Print: "✓ Personnel unchanged — no update needed." and stop. Do NOT run `author_reviewer.py` again.

**If "Change personnel":**

Ask the user in plain text:

> "Which names should change? Provide Author, DI Reviewer, and Tech Reviewer."
> (Type names separated by | or comma, e.g.: `Dongling Fei | Sakshi | Chad`)

Then run:

```bash
cd <working_dir>
python ~/skills/stability-report-update/scripts/author_reviewer.py . \
  --author "<Author Name>" \
  --di-reviewer "<DI Reviewer Name>" \
  --tech-reviewer "<Tech Reviewer Name>"
```

For any role the user wants to keep unchanged, pass the current name from Step 1.

## What Gets Updated (when changing)

- Cover page author name
- DI Review table: reviewer name, title, organization
- Technical Review table: reviewer name, title, organization
- Author table: author name, title, organization

All changes appear as Word tracked changes.
