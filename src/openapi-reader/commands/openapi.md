---
name: openapi
description: Query the OpenAPI spec in this project. Usage: /openapi summary | list [--tag TAG] [--method METHOD] | endpoint METHOD PATH | schema NAME | search QUERY
allowed-tools:
  - Bash
---

Parse the subcommand and arguments from the `/openapi` invocation, then run:

```
uv run scripts/openapi_tool.py [--spec PATH] <subcommand> [args]
```

Present the result clearly. For `summary`, display as-is. For JSON output (`list`, `endpoint`, `schema`, `search`), format it for readability — highlight key fields rather than dumping raw JSON.

If `openapi.json` is not found, suggest running with `--spec PATH` before the subcommand, e.g. `uv run scripts/openapi_tool.py --spec path/to/spec.json summary`.
