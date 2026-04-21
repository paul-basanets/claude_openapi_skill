# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

This project is building a Claude skill for efficiently reading and querying OpenAPI specifications. The central artifact is `openapi.json` — a real-world OpenAPI 3.1.0 spec for a Guardrail Management Backend API (v2.15.3) that serves as the primary test fixture.

## Project Setup

```bash
# Python 3.14+ required
python -m venv .venv
source .venv/bin/activate
```

No dependencies are currently declared. The `pyproject.toml` is minimal:

```toml
[project]
name = "openapi-skill"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = []
```

