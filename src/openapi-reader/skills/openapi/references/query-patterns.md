# OpenAPI Query Patterns

All examples assume `openapi.json` in the current directory. Add `--spec PATH_OR_URL` before the subcommand if the spec lives elsewhere — a local path or an HTTP(S) URL (e.g. `--spec https://petstore3.swagger.io/api/v3/openapi.json`). URL specs are cached 1h in the system temp dir; pass `--refresh` to force re-fetch.

## 1. Discover the API surface

```bash
uv run scripts/openapi_tool.py summary
uv run scripts/openapi_tool.py summary --compact   # paths-only, ~55% smaller
```

Returns all endpoints grouped by tag and a list of schema names. Use `--compact` when you only need to know which endpoints exist.

## 2. Find endpoints for a feature

```bash
uv run scripts/openapi_tool.py search "PII"
uv run scripts/openapi_tool.py list --tag "PII Detection"
uv run scripts/openapi_tool.py list --method GET
```

## 3. Understand a specific endpoint

```bash
uv run scripts/openapi_tool.py endpoint POST /api/guardrails/add
uv run scripts/openapi_tool.py --depth 1 endpoint POST /api/guardrails/add   # shallow peek
uv run scripts/openapi_tool.py --raw endpoint POST /api/guardrails/add       # untrimmed
```

Returns parameters, request body, and responses with `$ref`s resolved inline, encoded as TOON. The default output drops Pydantic auto-titles, collapses `anyOf: [T, {type: null}]` into `nullable: true`, strips empty `description`/`default` fields, and removes the generic 422 `HTTPValidationError` branch. TOON encoding additionally saves ~20–35% tokens vs the equivalent JSON. Output shape:

```
path: /api/guardrails/add
method: POST
parameters[0]:
requestBody:
  required: true
  content:
    application/json:
      schema:
        properties:
          topic:
            type: string
responses:
  "200":
    description: Successful Response
```

## 4. Understand a request or response schema

```bash
uv run scripts/openapi_tool.py schema GuardrailResponse
uv run scripts/openapi_tool.py schema AddGuardrailRequest
```

If the name is wrong, the error includes `did_you_mean` — retry with one of those.

## 5. Look up an endpoint by operationId

When code references an `operationId` and you don't know the path:

```bash
uv run scripts/openapi_tool.py operation add_guardrail_api_guardrails_add_post
uv run scripts/openapi_tool.py operation getGuardrail
```

Returns the same full output as `endpoint`. Misses return `did_you_mean` suggestions.

## 6. When output is still too large

- First try `--depth 1` or `--depth 2` for a shallower view.
- Use `summary --compact` as a cheap first probe.
- Call `schema NAME` for the specific type you actually need instead of drilling into `endpoint`.
