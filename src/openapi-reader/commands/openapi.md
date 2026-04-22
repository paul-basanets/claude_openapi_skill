---
name: openapi
description: Query the OpenAPI spec. Usage: /openapi [--raw] [--depth N] summary [--compact] | list [--tag TAG] [--method METHOD] | endpoint METHOD PATH | schema NAME | search QUERY | operation OPERATION_ID
allowed-tools:
  - Bash
---

Parse the subcommand and arguments from the `/openapi` invocation, then run:

```
uv run "$CLAUDE_PLUGIN_ROOT/scripts/openapi_tool.py" [--spec PATH_OR_URL] [--refresh] [--raw] [--depth N] <subcommand> [args]
```

Global flags go **before** the subcommand:

- `--spec PATH_OR_URL` — spec file or HTTP(S) URL (default `./openapi.json`). URLs are cached 1h in the system temp dir.
- `--refresh` — force re-fetch of URL spec, ignoring the cache
- `--raw` — disable the default junk-token trimming (keep Pydantic boilerplate intact)
- `--depth N` — cap `$ref` resolution depth (default 3; try `--depth 1` for a shallow peek)

Present the result clearly. For `summary`, display as-is. For TOON output (`list`, `endpoint`, `schema`, `search`, `operation`), format it for readability — highlight key fields rather than dumping the full tree. Errors are single-line JSON.

If a schema / operationId miss returns `did_you_mean`, suggest the top match to the user rather than re-issuing the failing call.

If `openapi.json` is not found, suggest running with `--spec` before the subcommand — either a local path or a URL, e.g. `uv run "$CLAUDE_PLUGIN_ROOT/scripts/openapi_tool.py" --spec path/to/spec.json summary` or `--spec https://api.example.com/openapi.json summary`.
