# OpenAPI Query Patterns

## 1. Discover the API surface
```bash
uv run scripts/openapi_tool.py summary
```
Returns all endpoints grouped by tag and a list of all schema names.

## 2. Find endpoints for a feature
```bash
uv run scripts/openapi_tool.py search "PII"
uv run scripts/openapi_tool.py list --tag "PII Detection"
uv run scripts/openapi_tool.py list --method GET
```

## 3. Understand a specific endpoint
```bash
uv run scripts/openapi_tool.py endpoint POST /api/guardrails/add
uv run scripts/openapi_tool.py endpoint GET /api/pii/config
```
Returns parameters, request body, and all responses with `$ref`s resolved inline.

## 4. Understand a request or response schema
```bash
uv run scripts/openapi_tool.py schema GuardrailResponse
uv run scripts/openapi_tool.py schema AddGuardrailRequest
```
Returns the full schema with `$ref`s resolved. If the name is unknown, the error response lists all 160 available schemas.
