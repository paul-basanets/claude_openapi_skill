# openapi-skill

Development project for the **openapi-reader** Claude Code plugin — token-efficient access to OpenAPI specifications.

Structured output is emitted as [TOON](https://github.com/toon-format/spec) (Token-Oriented Object Notation). Combined with the built-in junk-token trimmer, the plugin delivers **~58% fewer bytes than raw JSON** on the shipped fixture without semantic loss. See `src/openapi-reader/README.md` for format details and `docs/EVAL.md` for the current measurement report.

Accepts **OpenAPI 3.x** JSON specs from either a local file or an HTTP(S) URL (`--spec path.json` or `--spec https://…/openapi.json`). Swagger 2.0 loads with a warning — most subcommands work, but `schema` lookups require 3.x (`components/schemas`).

## Install

Inside Claude Code:

```
/plugin marketplace add paul-basanets/claude_openapi_skill
/plugin install openapi-reader@basanets-plugins
/reload-plugins
```

See [`src/openapi-reader/README.md#installation`](src/openapi-reader/README.md#installation) for local-directory and manual-copy install modes.

## Structure

```
.claude-plugin/         marketplace catalog (basanets-plugins)
src/openapi-reader/     plugin source (see its README for usage)
├── .claude-plugin/     plugin manifest (v0.5.1)
├── commands/           /openapi slash command
├── scripts/            openapi_tool.py — zero-dep Python CLI + TOON encoder
└── skills/openapi/     skill guidance + query-patterns reference

evals/run_eval.py       evaluation harness (12 UX scenarios + population-wide metrics)
docs/EVAL.md            generated evaluation report
bundle.py               builds dist/openapi-reader.zip
dist/                   build output
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate

# Test the CLI against the fixture
uv run src/openapi-reader/scripts/openapi_tool.py summary
uv run src/openapi-reader/scripts/openapi_tool.py endpoint POST /api/resource/add
uv run src/openapi-reader/scripts/openapi_tool.py schema GuardrailResponse
```

## Evaluation

```bash
uv run evals/run_eval.py
# → runs 12 UX scenarios, measures all 89 endpoints + 160 schemas, regenerates docs/EVAL.md
```

## Build

```bash
uv run bundle.py
# → dist/openapi-reader.zip
```
