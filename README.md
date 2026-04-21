# openapi-skill

Development project for the **openapi-reader** Claude Code plugin — token-efficient access to OpenAPI specifications.

## Structure

```
src/openapi-reader/     plugin source (see its README for usage)
├── .claude-plugin/     plugin manifest
├── commands/           /openapi slash command
├── scripts/            openapi_tool.py — zero-dep Python CLI
└── skills/openapi/     skill guidance + query-patterns reference

openapi.json            test fixture (Guardrail Management API v2.15.3)
bundle.py               builds dist/openapi-reader.zip
dist/                   build output
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate

# Test the CLI against the fixture
uv run src/openapi-reader/scripts/openapi_tool.py summary
uv run src/openapi-reader/scripts/openapi_tool.py endpoint POST /api/guardrails/add
uv run src/openapi-reader/scripts/openapi_tool.py schema GuardrailResponse
```

## Build

```bash
uv run bundle.py
# → dist/openapi-reader.zip
```
