# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

This project is building a Claude skill for efficiently reading and querying OpenAPI specifications.

## Project Setup

```bash
# Python 3.11+ required
python -m venv .venv
source .venv/bin/activate
```

No dependencies are currently declared. The `pyproject.toml` is minimal:

```toml
[project]
name = "openapi-skill"
version = "0.5.3"
requires-python = ">=3.11"
dependencies = []
```

The repo root also acts as a Claude Code plugin marketplace named `basanets-plugins` via `.claude-plugin/marketplace.json`, which points `openapi-reader` at `./src/openapi-reader`. Do not rename or relocate that file — `/plugin marketplace add` and auto-update rely on it.

