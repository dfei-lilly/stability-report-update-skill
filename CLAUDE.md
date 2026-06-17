# Claude Code Workflow Instructions

## MANDATORY: Check Skills First

Before starting ANY task, check if a relevant skill exists in /mnt/skills/:
- /mnt/skills/public/
- /mnt/skills/user/
- /mnt/skills/examples/
- /mnt/skills/organization/

## Common Skill Triggers:
- Creating/building a skill -> Use skill-creator
- Word documents -> Use docx skill
- Excel files -> Use xlsx skill
- PowerPoint -> Use pptx skill
- Data analysis -> Use data-analysis skill

## Process:
1. User gives task
2. Check if matching skill exists
3. If yes -> use the skill
4. If no -> build from scratch

---

# Research — LLM Wiki Schema

This wiki follows the Karpathy LLM Wiki pattern, installed via the `llm-wiki` Claude Code plugin. The `wiki-compiler` skill (bundled) reads this file on every operation.

## 1. Architecture (three layers)

1. `raw/` — immutable source files you curate. LLM reads, never writes. The plugin's PreToolUse hook blocks writes here.
2. `wiki/` — LLM-owned compiled markdown.
3. `CLAUDE.md` (this file) — conventions, workflows.

## 2. Page types

| Type | Folder | Description | TTL |
|------|--------|-------------|-----|
| entity | entities/ | Company, product, person, or tool mentioned in sources | 180d |
| concept | concepts/ | Pattern, framework, or idea | 365d |
| theme | themes/ | Narrative arc, editorial angle, or research cluster | 90d |
| comparison | comparisons/ | A vs B analysis or filed query output | 90d |
| synthesis | synthesis/ | Cross-cutting analysis spanning multiple sources | 90d |

## 3. Frontmatter (required on every wiki page)

```yaml
---
title: <Exact page title>
type: entity | concept | theme | comparison | synthesis
tags: [domain-tags]
sources: [raw/<filename>.md, ...]
source-type: raw | personal          # default: raw; personal pages may omit sources
external-sources:                     # optional
  - url: "https://..."
    title: "Source Title"
    author: "Author"                  # optional
    accessed: YYYY-MM-DD             # optional
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
ttl: 90d | 180d | 365d | null
confidence: high | medium | low
---
```

- `confidence`: high = multiple sources agree; medium = single source; low = inference or weak signal.
- `source-type: personal` — page is based on personal knowledge; `sources:` may be empty. Use `> [!personal]` callouts in the body.
- `external-sources:` — cite authoritative external URLs. Reference inline with `ext:<key>` (e.g., `ext:aws-docs`).

## 4. Page body conventions

- `[[wikilinks]]` for every reference to another wiki page. Bare slug only.
- Cite sources with inline `^[raw/filename.md]` or `## Sources` section.
- **Core callouts:**
  - `> [!contradiction]` where sources disagree.
  - `> [!gap]` for known missing coverage.
  - `> [!low-confidence]` for inline speculative claims.
  - `> [!source-removed]` when a cited source file was deleted.
- **Sensitivity callouts:**
  - `> [!confidential]` for sensitive material (excluded from export).
  - `> [!confidential <tier>]` for classification-tiered sensitivity (define tiers below).
- **Provenance callouts:**
  - `> [!personal]` for content from personal knowledge, not a raw source.
  - `> [!external]` for content from external authoritative references.
  - `> [!domain-specific]` for content specific to your organization/context.
- Every page ends with `## Backlinks`. The LLM maintains it.

## 5. index.md structure

Organized by type. One line per page with a terse summary:

```
## Entities
- [[entity-name]] — one-line description
```

## 6. log.md structure

Append-only, parseable:

```
## [YYYY-MM-DD] ingest | <source title>
- Ingested raw/<file>.md
- Pages touched: [[a]], [[b]]
- New pages: [[c]]
- Notes: ...
```

## 7. Workflows

Use the plugin's slash commands:

- `/llm-wiki-lilly:ingest <file>` or `/llm-wiki-lilly:ingest --new` — compile raw sources into wiki pages
- `/llm-wiki-lilly:ingest --all --auto` — batch ingest without discussion checkpoints
- `/llm-wiki-lilly:query "..." [--file-back]` — answer a question grounded in the wiki
- `/llm-wiki-lilly:lint` — health check (orphans, broken links, stale pages, discovery suggestions)
- `/llm-wiki-lilly:curate sweep` — scan for promotion, retirement, and merge candidates
- `/llm-wiki-lilly:curate promote|retire|merge` — act on individual pages
- `/llm-wiki-lilly:export` — render as a static HTML site

The `wiki-compiler` skill also auto-invokes when you say things like "ingest this into my wiki" or "compile these sources".

## 8. Obsidian compatibility

This wiki works as an Obsidian vault with no configuration. Open the wiki root directory in Obsidian and you get:

- **Graph view** of the knowledge graph via `[[wikilinks]]`
- **Dataview queries** on frontmatter fields (`type`, `confidence`, `tags`, `ttl`, etc.)
- **Native callout rendering** for all `> [!type]` blocks
- **Web Clipper integration** — drop clippings into `raw/Clippings/`, then ingest

Add `.obsidian/` to `.gitignore` — it's user-specific vault configuration.

## 9. What NOT to do

- Do not write to `raw/`. The plugin hook will block you.
- Do not delete wiki pages silently — log the deletion in `log.md`.
- Do not create pages without source citations (synthesis pages excepted).
- Do not duplicate content — always `[[link]]`.
- Do not overstate `confidence`.
- Do not fabricate data.
