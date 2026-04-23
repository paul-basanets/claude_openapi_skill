# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

This project is building a Claude skill for efficiently reading and querying OpenAPI specifications.

## Project Setup

Python 3.9+ required. The tool is stdlib-only, so a venv is optional for running it — only useful when doing dev work (linters, eval harness, etc.).

```bash
# macOS / Linux
python -m venv .venv && source .venv/bin/activate

# Windows (Git Bash, which Claude Code uses)
python -m venv .venv && source .venv/Scripts/activate
```

On Linux/macOS setups that only ship `python3`, substitute it for `python`.

No dependencies are currently declared. The `pyproject.toml` is minimal:

```toml
[project]
name = "openapi-skill"
version = "0.5.4"
requires-python = ">=3.9"
dependencies = []
```

The repo root also acts as a Claude Code plugin marketplace named `basanets-plugins` via `.claude-plugin/marketplace.json`, which points `openapi-reader` at `./src/openapi-reader`. Do not rename or relocate that file — `/plugin marketplace add` and auto-update rely on it.

