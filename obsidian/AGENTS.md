# AGENTS.md

You are maintaining an Obsidian LLM Wiki for the LightRAG project.

## Rules

- `10_Raw/` is read-only after source capture. Never rewrite source notes during wiki maintenance.
- `20_Wiki/` is the compiled knowledge layer.
- `30_Projects/` contains project-specific working notes and goals.
- Every durable claim in `20_Wiki/` needs a source link and a provenance marker:
  `^[extracted]`, `^[inferred]`, or `^[ambiguous]`.
- Use Obsidian wikilinks for concepts, goals, files, and project notes.
- Prefer small updates: one ingest or one lint pass at a time.
- Log wiki maintenance under `40_Logs/`.
