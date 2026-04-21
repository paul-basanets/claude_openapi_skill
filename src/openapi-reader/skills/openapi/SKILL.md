---
name: openapi
description: This skill should be used when the user asks to "query the API spec",
  "show available endpoints", "what endpoints are available", "read the openapi",
  "get the schema for", "search the API spec", "look up operationId", or when writing
  code that calls an API defined by an openapi.json file in the project.
version: 0.3.0
---

# OpenAPI Skill

Query OpenAPI specs without loading the full file into context. Use `uv run scripts/openapi_tool.py` via the Bash tool.

## Subcommands

| Command | Args | Output |
|---------|------|--------|
| `summary` | `[--compact]` | Human-readable: title, ops by tag, schema names. `--compact` drops summaries + schema names (~55% smaller). |
| `list` | `[--tag TAG] [--method METHOD]` | JSON array of matching endpoints |
| `endpoint METHOD PATH` | — | Full operation: params, request body, responses (`$refs` resolved) |
| `schema NAME` | — | Schema definition (`$refs` resolved) |
| `search QUERY` | — | Matching endpoints and schemas |
| `operation OPERATION_ID` | — | Full operation detail (same output as `endpoint`) looked up by operationId |

## Global flags

Placed **before** the subcommand: `--spec PATH`, `--raw`, `--depth N`.

- `--spec PATH` — use a spec file other than `./openapi.json`.
- `--raw` — disable compact trimming. By default the tool strips Pydantic boilerplate (auto-titles, `anyOf[T, null]` → `nullable: true`, empty `description`/`default`, generic 422 responses) for ~45% smaller output with no semantic loss. Pass `--raw` when you need the literal spec text.
- `--depth N` (default 3) — cap `$ref` resolution depth. `--depth 1` gives a shallow peek (very small); higher values fully inline deeply-nested schemas.

## Strategy

1. **Start with `summary`** (or `summary --compact` if you only need the endpoint surface) to orient — ~2–3K tokens, full endpoint index + schema names.
2. **Drill in** with `endpoint`, `schema`, or `operation`. Unknown names return `did_you_mean` suggestions — retry with one of those.
3. **Never read `openapi.json` raw** into context.

Default spec path is `openapi.json` in the current working directory.

## Additional Resources

- **`references/query-patterns.md`** — common multi-step query workflows
