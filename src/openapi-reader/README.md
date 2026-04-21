# openapi-reader

A Claude Code plugin for token-efficient, on-demand access to OpenAPI specifications.

Instead of loading a full spec (often 30K+ tokens) into context, this plugin lets Claude query exactly what it needs: endpoint details, schema definitions, tag-filtered lists, or full-text search.

## Installation

Copy the plugin files into your project root:

```bash
unzip openapi-reader.zip
cp -r openapi-reader/{.claude-plugin,skills,commands,scripts} .
rm -rf openapi-reader/
```

Your spec must be named `openapi.json` in the project root, or pass `--spec PATH` explicitly.

## Usage

### Slash command

```
/openapi summary
/openapi list --tag "PII Detection"
/openapi endpoint POST /api/guardrails/add
/openapi schema GuardrailResponse
/openapi search "embedding"
```

### Direct CLI

```bash
uv run scripts/openapi_tool.py summary
uv run scripts/openapi_tool.py list --tag TAG --method GET
uv run scripts/openapi_tool.py endpoint METHOD PATH
uv run scripts/openapi_tool.py schema NAME
uv run scripts/openapi_tool.py search QUERY
uv run scripts/openapi_tool.py --spec path/to/spec.json summary
```

### Skill

The skill activates automatically when you ask about API endpoints or schemas. Claude uses the CLI tool internally to fetch only the relevant data.

## Requirements

- Python 3.14+ (no external dependencies)
- `uv` on PATH
