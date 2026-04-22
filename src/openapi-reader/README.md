# openapi-reader

A Claude Code plugin for token-efficient, on-demand access to OpenAPI specifications.

Instead of loading a full spec (often 30K+ tokens) into context, this plugin lets Claude query exactly what it needs: endpoint details, schema definitions, tag-filtered lists, or full-text search.

## Token efficiency

Structured output is emitted as [TOON](https://github.com/toon-format/spec) (Token-Oriented Object Notation) — a compact, LLM-friendly encoding of the JSON data model. Uniform object arrays collapse to tabular form (fields declared once), nested objects use YAML-style indentation, and strings are quoted only when required. On the shipped test fixture (141 KB, 89 endpoints, 160 schemas), the full endpoint + schema population emits in **282 KB of compact TOON vs 672 KB of raw JSON — a 58% reduction** (38% from TOON format, layered over 32% from the junk-token trimmer that removes Pydantic auto-titles, `anyOf[T, null]`, empty descriptions, and FastAPI 422 boilerplate).

Errors are single-line JSON; `summary` is plain text. See `docs/EVAL.md` in the repo for the full measurement report.

## Installation

### From GitHub (recommended)

Inside Claude Code:

```
/plugin marketplace add paul-basanets/claude_openapi_skill
/plugin install openapi-reader@basanets-plugins
/reload-plugins
```

Claude Code clones the repo into its plugin cache automatically — no manual `git clone` needed. To pin a version, append `@<tag>` to the marketplace source (e.g. `paul-basanets/claude_openapi_skill@v0.4.0`).

Your spec must be named `openapi.json` in the project root, or pass `--spec PATH` explicitly. The plugin activates on API-related prompts; use `/openapi` directly for explicit queries.

### Local-directory marketplace (contributors / offline)

```bash
git clone https://github.com/paul-basanets/claude_openapi_skill.git
```

Then inside Claude Code:

```
/plugin marketplace add /absolute/path/to/claude_openapi_skill
/plugin install openapi-reader@basanets-plugins
/reload-plugins
```

Use this mode when hacking on the plugin itself — `/plugin marketplace update basanets-plugins` refreshes against your local working tree.

### Manual copy (legacy fallback)

For Claude Code versions predating `/plugin`, download `dist/openapi-reader.zip` and unpack into your project:

```bash
unzip openapi-reader.zip
cp -r openapi-reader/{.claude-plugin,skills,commands,scripts} .
rm -rf openapi-reader/
```

## Usage

### Slash command

```
/openapi summary
/openapi list --tag "PII Detection"
/openapi endpoint POST /api/guardrails/add
/openapi schema GuardrailResponse
/openapi search "embedding"
/openapi operation add_guardrail_api_guardrails_add_post
```

### Direct CLI

```bash
uv run scripts/openapi_tool.py summary
uv run scripts/openapi_tool.py summary --compact                 # paths-only overview
uv run scripts/openapi_tool.py list --tag TAG --method GET
uv run scripts/openapi_tool.py endpoint METHOD PATH
uv run scripts/openapi_tool.py schema NAME
uv run scripts/openapi_tool.py search QUERY
uv run scripts/openapi_tool.py operation OPERATION_ID
uv run scripts/openapi_tool.py --spec path/to/spec.json summary
uv run scripts/openapi_tool.py --depth 1 endpoint METHOD PATH    # shallow $ref resolution
uv run scripts/openapi_tool.py --raw endpoint METHOD PATH        # disable junk trimming
```

Global flags (`--spec`, `--depth`, `--raw`) must precede the subcommand.

### Skill

The skill activates automatically when you ask about API endpoints or schemas. Claude uses the CLI tool internally to fetch only the relevant data. `SKILL.md` includes a TOON syntax primer so the format is self-describing in-context.

## Output format cheat sheet

```
# Uniform arrays — tabular (fields declared once)
users[2]{id,name}:
  1,Alice
  2,Bob

# Nested objects — indentation
endpoint:
  path: /api/users
  method: GET

# Primitive arrays — inline
tags[3]: admin,user,guest

# Non-uniform or nested-value arrays — expanded
items[2]:
  - id: 1
    meta: {k: v}
  - id: 2
    tags[1]: alpha
```

## Requirements

- Python 3.14+ (no external dependencies)
- `uv` on PATH
