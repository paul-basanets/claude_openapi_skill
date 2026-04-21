---
name: openapi
description: This skill should be used when the user asks to "query the API spec",
  "show available endpoints", "what endpoints are available", "read the openapi",
  "get the schema for", "search the API spec", or when writing code that calls an
  API defined by an openapi.json file in the project.
version: 0.1.0
---

# OpenAPI Skill

Query OpenAPI specs without loading the full file into context. Use `uv run scripts/openapi_tool.py` via the Bash tool.

## Subcommands

| Command | Args | Output |
|---------|------|--------|
| `summary` | `[--spec PATH]` | Human-readable: title, ops by tag, schema names |
| `list` | `[--tag TAG] [--method METHOD] [--spec PATH]` | JSON array of matching endpoints |
| `endpoint METHOD PATH` | `[--spec PATH]` | Full operation: params, request body, responses ($refs resolved) |
| `schema NAME` | `[--spec PATH]` | Schema definition ($refs resolved) |
| `search QUERY` | `[--spec PATH]` | Matching endpoints and schemas |
| `operation OPERATION_ID` | `[--spec PATH]` | Full operation detail (same output as `endpoint`) looked up by operationId |

## Strategy

Start with `summary` to orient — it shows the full endpoint index and all schema names in ~1K tokens. Then call `endpoint` or `schema` for the specific detail needed. Never read `openapi.json` raw into context.

Default spec path is `openapi.json` in the current working directory. Pass `--spec PATH` if the file is elsewhere.

## Additional Resources

- **`references/query-patterns.md`** — common multi-step query workflows
