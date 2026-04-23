---
name: openapi
description: This skill should be used when the user asks to "query the API spec",
  "show available endpoints", "what endpoints are available", "read the openapi",
  "get the schema for", "search the API spec", "look up operationId", or when writing
  code that calls an API defined by an openapi.json file in the project.
version: 0.5.5
---

# OpenAPI Skill

Query OpenAPI specs without loading the full file into context. Use the Bash tool with this snippet (handles missing `$CLAUDE_PLUGIN_ROOT`):

```bash
_script="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/scripts/openapi_tool.py}"
_script="${_script:-$(ls ~/.claude/plugins/cache/basanets-plugins/openapi-reader/*/scripts/openapi_tool.py 2>/dev/null | sort -V | tail -1)}"
python "$_script" [global flags] <subcommand> [args]
```

## Subcommands

| Command | Args | Output |
|---------|------|--------|
| `summary` | `[--compact]` | Human-readable text: title, ops by tag, schema names. `--compact` drops summaries + schema names (~55% smaller). |
| `list` | `[--tag TAG] [--method METHOD]` | TOON array of matching endpoints |
| `endpoint METHOD PATH` | — | TOON object with full operation: params, request body, responses (`$refs` resolved) |
| `schema NAME` | — | TOON object with schema definition (`$refs` resolved) |
| `search QUERY` | — | TOON array of matching endpoints and schemas |
| `operation OPERATION_ID` | — | Full operation detail (same output as `endpoint`) looked up by operationId |

Errors are single-line JSON (`{"error": "...", ...}`); all other structured output is TOON.

## Output format: TOON

TOON ([Token-Oriented Object Notation](https://github.com/toon-format/spec/blob/main/SPEC.md)) is a compact, JSON-equivalent encoding that saves ~20–35% tokens vs indented JSON. Key syntax Claude needs to know:

- **Objects** use YAML-style indentation (2 spaces per level). `key: value` for scalars, `key:` followed by indented children for nested objects.
- **Primitive arrays** are inline: `tags[3]: a,b,c` — length in brackets, comma-separated values.
- **Uniform object arrays** are tabular: `users[2]{id,name}:` declares field list once, then each object is one CSV row at the next indent level (`  1,Alice`).
- **Non-uniform or nested object arrays** use expanded form: `items[N]:` followed by `  - key: value` entries.
- **Strings** are unquoted unless they contain `:`, `,`, `"`, `\`, `[`, `]`, `{`, `}`, whitespace boundaries, match `true`/`false`/`null`/a number, or start with `-`. Escapes inside quoted strings: `\\ \" \n \r \t`.
- **Scalars**: `true`, `false`, `null`, numbers in canonical form.

A full endpoint looks like:

```
path: /api/resource/add
method: POST
requestBody:
  required: true
  content:
    application/json:
      schema:
        type: object
        required[2]: topic,keywords
        properties:
          topic:
            type: string
            description: Internal name
```

## Global flags

Placed **before** the subcommand: `--spec PATH_OR_URL`, `--refresh`, `--raw`, `--depth N`.

- `--spec PATH_OR_URL` — use a spec file or HTTP(S) URL instead of `./openapi.json`. URLs (starting with `http://` or `https://`) are fetched and cached for 1 hour in the system temp dir.
- `--refresh` — force re-fetch of a URL spec, ignoring the cache.
- `--raw` — disable compact trimming. By default the tool strips Pydantic boilerplate (auto-titles, `anyOf[T, null]` → `nullable: true`, empty `description`/`default`, generic 422 responses) with no semantic loss. Pass `--raw` when you need the literal spec text.
- `--depth N` (default 3) — cap `$ref` resolution depth. `--depth 1` gives a shallow peek (very small); higher values fully inline deeply-nested schemas.

## Strategy

1. **Start with `summary`** (or `summary --compact` if you only need the endpoint surface) to orient — ~2–3K tokens, full endpoint index + schema names.
2. **Drill in** with `endpoint`, `schema`, or `operation`. Unknown names return `did_you_mean` suggestions — retry with one of those.
3. **Never read `openapi.json` raw** into context.

Default spec path is `openapi.json` in the current working directory. Pass `--spec https://…/openapi.json` to query a remote spec directly (cached 1h; use `--refresh` to re-fetch).

## Additional Resources

- **`references/query-patterns.md`** — common multi-step query workflows
