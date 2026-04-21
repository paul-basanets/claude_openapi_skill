---
name: openapi
description: Query the OpenAPI spec. Usage: /openapi [--raw] [--depth N] summary [--compact] | list [--tag TAG] [--method METHOD] | endpoint METHOD PATH | schema NAME | search QUERY | operation OPERATION_ID
allowed-tools:
  - Bash
---

Parse the subcommand and arguments from the `/openapi` invocation, then run:

```
uv run scripts/openapi_tool.py [--spec PATH] [--raw] [--depth N] <subcommand> [args]
```

Global flags go **before** the subcommand:

- `--spec PATH` — spec file other than `./openapi.json`
- `--raw` — disable the default junk-token trimming (keep Pydantic boilerplate intact)
- `--depth N` — cap `$ref` resolution depth (default 3; try `--depth 1` for a shallow peek)

Present the result clearly. For `summary`, display as-is. For JSON output (`list`, `endpoint`, `schema`, `search`, `operation`), format it for readability — highlight key fields rather than dumping raw JSON.

If a schema / operationId miss returns `did_you_mean`, suggest the top match to the user rather than re-issuing the failing call.

If `openapi.json` is not found, suggest running with `--spec PATH` before the subcommand, e.g. `uv run scripts/openapi_tool.py --spec path/to/spec.json summary`.
