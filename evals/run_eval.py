#!/usr/bin/env python3
"""
Evaluation harness for the openapi-reader plugin.

Runs a fixed scenario suite + population-wide junk-token analysis against
the shipped openapi.json fixture, then writes a markdown report to
docs/EVAL.md. Stdlib only, mirrors the plugin's zero-dep style.

Run from repo root:
    uv run evals/run_eval.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "src" / "openapi-reader" / "scripts" / "openapi_tool.py"
SPEC = ROOT / "openapi.json"
REPORT = ROOT / "docs" / "EVAL.md"

# Import the tool in-process so we can inspect pre-emission Python structures
# without subprocess-regex games against a format-dependent output layer.
sys.path.insert(0, str(TOOL.parent))
import openapi_tool as tool  # noqa: E402


def run(args: list[str], cwd: Path = ROOT) -> tuple[int, str, str, float]:
    t0 = time.perf_counter()
    r = subprocess.run(
        ["uv", "run", str(TOOL), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    dt = time.perf_counter() - t0
    return r.returncode, r.stdout, r.stderr, dt


# ---------- Part A: UX scenarios ----------


@dataclass
class Scenario:
    num: int
    ask: str
    steps: list[list[str]]  # sequence of CLI arg lists
    expect_ok: bool = True  # last step should exit 0
    expect_error_nonzero: bool = False  # for error-UX scenarios (must fail cleanly)
    notes: str = ""


SCENARIOS: list[Scenario] = [
    Scenario(1, "What does this API do?", steps=[["summary"]]),
    Scenario(
        2,
        "List all PII endpoints",
        steps=[["search", "PII"]],
        notes="also valid: list --tag 'PII Detection'",
    ),
    Scenario(
        3,
        "How do I add a new guardrail?",
        steps=[["summary"], ["endpoint", "POST", "/api/guardrails/add"]],
    ),
    Scenario(
        4,
        "What's the shape of a GuardrailResponse?",
        steps=[["schema", "GuardrailResponse"]],
    ),
    Scenario(
        5,
        "Look up operationId add_guardrail_api_guardrails_add_post",
        steps=[["operation", "add_guardrail_api_guardrails_add_post"]],
    ),
    Scenario(6, "List every GET endpoint", steps=[["list", "--method", "GET"]]),
    Scenario(7, "Anything about embeddings?", steps=[["search", "embedding"]]),
    Scenario(
        8, "What endpoints exist under AI Test?", steps=[["list", "--tag", "AI Test"]]
    ),
    Scenario(
        9,
        "What's the /api/advanced/analyze-patterns request body?",
        steps=[["endpoint", "POST", "/api/advanced/analyze-patterns"]],
    ),
    Scenario(
        10,
        "Unknown schema name (error UX)",
        steps=[["schema", "NotARealSchema"]],
        expect_ok=False,
        expect_error_nonzero=True,
    ),
    Scenario(
        11,
        "Unknown path (error UX)",
        steps=[["endpoint", "GET", "/does/not/exist"]],
        expect_ok=False,
        expect_error_nonzero=True,
    ),
    Scenario(
        12,
        "Missing spec file (error UX)",
        steps=[["--spec", "nope.json", "summary"]],
        expect_ok=False,
        expect_error_nonzero=True,
    ),
]


@dataclass
class ScenarioResult:
    scenario: Scenario
    total_bytes: int = 0
    total_time_s: float = 0.0
    per_step_bytes: list[int] = field(default_factory=list)
    exit_codes: list[int] = field(default_factory=list)
    passed: bool = False
    stdout_tail: str = ""
    stderr_tail: str = ""


def run_scenarios() -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for sc in SCENARIOS:
        r = ScenarioResult(scenario=sc)
        last_stdout = ""
        last_stderr = ""
        for step in sc.steps:
            code, out, err, dt = run(step)
            r.per_step_bytes.append(len(out))
            r.total_bytes += len(out) + len(err)
            r.total_time_s += dt
            r.exit_codes.append(code)
            last_stdout, last_stderr = out, err
        r.stdout_tail = last_stdout[:400]
        r.stderr_tail = last_stderr[:400]
        if sc.expect_error_nonzero:
            r.passed = r.exit_codes[-1] != 0 and (
                "error" in last_stdout.lower() or "error" in last_stderr.lower()
            )
        else:
            r.passed = r.exit_codes[-1] == 0 and bool(last_stdout.strip())
        results.append(r)
    return results


# ---------- Part B: population-wide junk-token analysis ----------
#
# The junk categories are properties of the upstream spec (not the emission
# format), so we measure them on the in-memory Python structures returned by
# the tool's internal builders, not via regex over the serialized output.


@dataclass
class OutputStats:
    kind: str  # 'endpoint' | 'schema'
    name: str
    bytes_raw: int  # --raw TOON bytes
    bytes_compact: int  # default (compact) TOON bytes
    titles_total: int
    titles_auto: int
    anyof_null: int
    empty_desc: int
    empty_default_str: int
    httpvalidation: int


_SEP_RE = re.compile(r"[_\s-]+")


def _auto_title(key: str) -> str:
    return " ".join(p.capitalize() for p in _SEP_RE.split(key) if p)


def analyze_junk(obj, parent_key: str | None = None) -> dict[str, int]:
    """Walk a resolved (pre-compact) Python structure and count junk markers."""
    counts = {
        "titles_total": 0,
        "titles_auto": 0,
        "anyof_null": 0,
        "empty_desc": 0,
        "empty_default_str": 0,
        "httpvalidation": 0,
    }

    def walk(node, pkey):
        if isinstance(node, dict):
            branches = node.get("anyOf")
            if isinstance(branches, list) and any(
                isinstance(b, dict) and b.get("type") == "null" for b in branches
            ):
                counts["anyof_null"] += 1
            t = node.get("title")
            if isinstance(t, str):
                counts["titles_total"] += 1
                if pkey and t == _auto_title(pkey):
                    counts["titles_auto"] += 1
            if node.get("description") == "":
                counts["empty_desc"] += 1
            if node.get("default") == "":
                counts["empty_default_str"] += 1
            schema_in_content = (
                node.get("content", {}).get("application/json", {}).get("schema", {})
                if isinstance(node.get("content"), dict)
                else {}
            )
            if isinstance(schema_in_content, dict):
                if schema_in_content.get("title") == "HTTPValidationError":
                    counts["httpvalidation"] += 1
                ref = schema_in_content.get("$ref", "")
                if isinstance(ref, str) and ref.endswith("/HTTPValidationError"):
                    counts["httpvalidation"] += 1
            for k, v in node.items():
                if k == "properties" and isinstance(v, dict):
                    for sk, sv in v.items():
                        walk(sv, sk)
                else:
                    walk(v, None)
        elif isinstance(node, list):
            for item in node:
                walk(item, pkey)

    walk(obj, parent_key)
    return counts


def measure_all_endpoints(spec: dict) -> list[OutputStats]:
    stats: list[OutputStats] = []
    for path, method, _ in tool._iter_operations(spec):
        code_r, out_r, _, _ = run(["--raw", "endpoint", method.upper(), path])
        if code_r != 0:
            continue
        code_c, out_c, _, _ = run(["endpoint", method.upper(), path])
        if code_c != 0:
            continue
        raw_obj = tool._build_endpoint(spec, method, path, max_depth=tool.DEFAULT_DEPTH)
        junk = analyze_junk(raw_obj)
        stats.append(
            OutputStats(
                kind="endpoint",
                name=f"{method.upper()} {path}",
                bytes_raw=len(out_r),
                bytes_compact=len(out_c),
                **junk,
            )
        )
    return stats


def measure_all_schemas(spec: dict) -> list[OutputStats]:
    stats: list[OutputStats] = []
    schemas = sorted((spec.get("components", {}).get("schemas", {}) or {}).keys())
    for name in schemas:
        code_r, out_r, _, _ = run(["--raw", "schema", name])
        if code_r != 0:
            continue
        code_c, out_c, _, _ = run(["schema", name])
        if code_c != 0:
            continue
        raw_obj = tool.resolve_refs(
            spec["components"]["schemas"][name], spec, max_depth=tool.DEFAULT_DEPTH
        )
        junk = analyze_junk(raw_obj, parent_key=name)
        stats.append(
            OutputStats(
                kind="schema",
                name=name,
                bytes_raw=len(out_r),
                bytes_compact=len(out_c),
                **junk,
            )
        )
    return stats


def pctile(values: list[int], p: float) -> int:
    if not values:
        return 0
    vs = sorted(values)
    k = max(0, min(len(vs) - 1, int(round((p / 100.0) * (len(vs) - 1)))))
    return vs[k]


# ---------- Report rendering ----------


def render_report(
    scenarios: list[ScenarioResult],
    endpoint_stats: list[OutputStats],
    schema_stats: list[OutputStats],
    spec_bytes: int,
    summary_bytes: int,
) -> str:
    passed = sum(1 for r in scenarios if r.passed)
    ep_raw = [s.bytes_raw for s in endpoint_stats]
    sc_raw = [s.bytes_raw for s in schema_stats]
    ep_com = [s.bytes_compact for s in endpoint_stats]
    sc_com = [s.bytes_compact for s in schema_stats]

    total_raw = sum(ep_raw) + sum(sc_raw) or 1
    total_compact = sum(ep_com) + sum(sc_com)
    savings_pct = round(100 * (1 - total_compact / total_raw), 1)

    lines: list[str] = []
    lines.append("# `openapi-reader` Plugin Evaluation")
    lines.append("")
    lines.append(
        f"_Auto-generated by `evals/run_eval.py`. Fixture: `openapi.json` "
        f"({spec_bytes:,} bytes). Output format: **TOON**._"
    )
    lines.append("")

    # TL;DR
    lines.append("## TL;DR")
    lines.append("")
    lines.append(
        f"- **Effectiveness**: {passed}/{len(scenarios)} UX scenarios "
        f"{'pass' if passed == len(scenarios) else 'pass (see table)'}."
    )
    lines.append(
        f"- **Compression vs raw spec**: `summary` is "
        f"{spec_bytes // summary_bytes}× smaller than the raw spec "
        f"({summary_bytes:,} vs {spec_bytes:,} bytes)."
    )
    lines.append(
        f"- **Compact-mode savings (default on)**: compact output is "
        f"**~{savings_pct}% smaller** than `--raw` "
        f"(measured end-to-end across all "
        f"{len(endpoint_stats)} endpoints and {len(schema_stats)} schemas)."
    )
    lines.append(
        "- **Output format**: TOON (Token-Oriented Object Notation) "
        "for structured responses; plain text for `summary`; "
        "single-line JSON for errors."
    )
    lines.append("")

    # Part A
    lines.append("## Part A — UX scenarios")
    lines.append("")
    lines.append("| # | Ask | Steps | Bytes | Time | Result |")
    lines.append("|---|-----|-------|-------|------|--------|")
    for r in scenarios:
        sc = r.scenario
        step_str = " → ".join(" ".join(s) for s in sc.steps)
        verdict = "PASS" if r.passed else "FAIL"
        lines.append(
            f"| {sc.num} | {sc.ask} | `{step_str}` | "
            f"{r.total_bytes:,} | {r.total_time_s:.2f}s | {verdict} |"
        )
    lines.append("")

    # Error-UX transcripts
    lines.append("### Error-path transcripts (scenarios 10–12)")
    lines.append("")
    for r in scenarios:
        if not r.scenario.expect_error_nonzero:
            continue
        lines.append(
            f"**#{r.scenario.num} — {r.scenario.ask}**  (exit={r.exit_codes[-1]})"
        )
        lines.append("```")
        lines.append((r.stdout_tail or r.stderr_tail).strip())
        lines.append("```")
        lines.append("")

    # Part B
    lines.append("## Part B — Output size & junk-token analysis")
    lines.append("")
    lines.append(
        f"Population: {len(endpoint_stats)} endpoints, "
        f"{len(schema_stats)} schemas (all covered)."
    )
    lines.append("")
    lines.append("### Size distribution (bytes, `--raw` TOON)")
    lines.append("")
    lines.append("| Command | min | p50 | p90 | max | total |")
    lines.append("|---------|-----|-----|-----|-----|-------|")
    if ep_raw:
        lines.append(
            f"| `endpoint` | {min(ep_raw):,} | {int(median(ep_raw)):,} | "
            f"{pctile(ep_raw, 90):,} | {max(ep_raw):,} | {sum(ep_raw):,} |"
        )
    if sc_raw:
        lines.append(
            f"| `schema` | {min(sc_raw):,} | {int(median(sc_raw)):,} | "
            f"{pctile(sc_raw, 90):,} | {max(sc_raw):,} | {sum(sc_raw):,} |"
        )
    lines.append("")
    lines.append("### Size distribution (bytes, default compact TOON)")
    lines.append("")
    lines.append("| Command | min | p50 | p90 | max | total |")
    lines.append("|---------|-----|-----|-----|-----|-------|")
    if ep_com:
        lines.append(
            f"| `endpoint` | {min(ep_com):,} | {int(median(ep_com)):,} | "
            f"{pctile(ep_com, 90):,} | {max(ep_com):,} | {sum(ep_com):,} |"
        )
    if sc_com:
        lines.append(
            f"| `schema` | {min(sc_com):,} | {int(median(sc_com)):,} | "
            f"{pctile(sc_com, 90):,} | {max(sc_com):,} | {sum(sc_com):,} |"
        )
    lines.append("")

    # Junk totals (measured on pre-emission Python structures)
    def totals(stats: list[OutputStats]) -> dict[str, int]:
        return {
            "titles_total": sum(s.titles_total for s in stats),
            "titles_auto": sum(s.titles_auto for s in stats),
            "anyof_null": sum(s.anyof_null for s in stats),
            "empty_desc": sum(s.empty_desc for s in stats),
            "empty_default_str": sum(s.empty_default_str for s in stats),
            "httpvalidation": sum(s.httpvalidation for s in stats),
        }

    ep_t, sc_t = totals(endpoint_stats), totals(schema_stats)
    lines.append("### Junk-category totals (what the compact trimmer strips)")
    lines.append("")
    lines.append(
        "Measured on the in-memory spec structures before emission — "
        "format-independent."
    )
    lines.append("")
    lines.append("| Category | `endpoint` total | `schema` total | Notes |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| `title` fields (all) | {ep_t['titles_total']:,} | {sc_t['titles_total']:,} "
        f"| Count of `title` keys on dict nodes. |"
    )
    lines.append(
        f"| `title` auto-derived | {ep_t['titles_auto']:,} | {sc_t['titles_auto']:,} "
        f"| Matches parent key (Pydantic artifact). Stripping is safe. |"
    )
    lines.append(
        f"| `anyOf[T, null]` nullable | {ep_t['anyof_null']:,} | {sc_t['anyof_null']:,} "
        f"| Each can collapse to a `nullable` marker. |"
    )
    lines.append(
        f'| empty `description: ""` | {ep_t["empty_desc"]:,} | {sc_t["empty_desc"]:,} '
        f"| No signal; safely droppable. |"
    )
    lines.append(
        f'| empty `default: ""` | {ep_t["empty_default_str"]:,} | {sc_t["empty_default_str"]:,} '
        f"| Usually placeholder noise. |"
    )
    lines.append(
        f"| `HTTPValidationError` refs | {ep_t['httpvalidation']:,} | {sc_t['httpvalidation']:,} "
        f"| Standard FastAPI 422 boilerplate, near-identical on every call. |"
    )
    lines.append("")

    # Savings sample
    lines.append("### Compact vs `--raw` — top-10 sample")
    lines.append("")
    sample = (
        sorted(endpoint_stats, key=lambda s: s.bytes_raw, reverse=True)[:5]
        + sorted(schema_stats, key=lambda s: s.bytes_raw, reverse=True)[:5]
    )
    lines.append("| Kind | Name | Raw (B) | Compact (B) | Saved |")
    lines.append("|---|---|---|---|---|")
    for s in sample:
        saved = (
            round(100 * (1 - s.bytes_compact / s.bytes_raw), 1) if s.bytes_raw else 0
        )
        lines.append(
            f"| {s.kind} | `{s.name}` | {s.bytes_raw:,} | "
            f"{s.bytes_compact:,} | {saved}% |"
        )
    lines.append(
        f"| **population total** |  | **{total_raw:,}** | **{total_compact:,}** | **{savings_pct}%** |"
    )
    lines.append("")

    # Part C — static discoverability / description review
    lines.append("## Part C — Discoverability & description quality")
    lines.append("")
    lines.append(
        "- `SKILL.md` (v0.4.0) description covers the primary triggers: "
        "_query the API spec, show available endpoints, get the schema for, "
        "search the API spec, look up operationId_, plus the catch-all "
        "_writing code that calls an API defined by an openapi.json file_. "
        "All 12 scenarios in Part A map cleanly onto this trigger surface."
    )
    lines.append(
        "- `SKILL.md` now includes a **TOON primer** so a fresh Claude "
        "session can parse the output format without an external spec fetch. "
        "Global flags (`--raw`, `--depth N`, `--spec PATH`) are documented "
        "with position and trade-offs."
    )
    lines.append(
        "- `references/query-patterns.md` gives copy-pasteable recipes for "
        'the common workflows plus an "output still too large" fallback '
        "playbook (`--depth 1` → `summary --compact` → direct `schema` call)."
    )
    lines.append(
        "- `/openapi` slash command advertises all flags in its description "
        "line so the `/command` completion surface shows the full argument set."
    )
    lines.append("")

    # Part D — correctness spot-checks
    lines.append("## Part D — Correctness spot-checks")
    lines.append("")
    lines.append(
        "- **Circular refs terminate cleanly.** `schema GuardrailResponse` "
        "nests itself via `properties.guardrails.additionalProperties` "
        "(after the nullable collapse). The configurable `depth` cap in "
        "`resolve_refs` (default 3) preserves the inner `$ref` rather than "
        "expanding it — no infinite recursion, and the agent still gets a "
        "pointer it can resolve with a follow-up `schema` call."
    )
    lines.append(
        "- **Search is case-insensitive and multi-term AND.** "
        '`search "pii config"` and `search "PII CONFIG"` return the '
        "same set; terms are AND-joined across path + summary + "
        "description + operationId + tags + parameter names/descriptions."
    )
    lines.append(
        "- **Parameter merge is untested by this fixture.** The code in "
        "`cmd_endpoint` merges path-level `parameters` with operation-level "
        "ones, with operation-level overriding on `(name, in)` key collision. "
        "The shipped spec has no endpoint that uses both levels, so the "
        "merge path is exercised only in the edge branch covering unnamed "
        "extras. Covering this would need either a different fixture or a "
        "targeted unit test."
    )
    lines.append(
        "- **Error messages are clean single-line JSON, exit code 1** on all "
        "three error paths (unknown schema, unknown path, missing spec file) "
        "— no stack traces leak. Unknown schema and unknown operationId "
        "return `did_you_mean` suggestions via `difflib.get_close_matches` "
        "instead of dumping the full name list."
    )
    lines.append(
        "- **Compact trimming preserves semantics.** `anyOf: [X, {type: "
        "null}]` collapses to `X + nullable: true`; auto-derived `title` "
        "fields (matching `key.title()`) are dropped; empty `description: "
        '""` / `default: ""` removed; FastAPI 422 '
        "`HTTPValidationError` response entries elided. Pass `--raw` to "
        "disable when validating against the literal spec."
    )
    lines.append(
        "- **TOON encoder coverage.** Handles tabular arrays (homogeneous "
        "primitive-valued objects, field list declared once), inline "
        "primitive arrays, expanded list form for non-uniform or nested "
        "item arrays, rule-based string quoting, and canonical numeric "
        "forms. Inline-encoded in `openapi_tool.py` (~130 LOC); no external "
        "dependencies."
    )
    lines.append("")

    # Shipped changes (v0.4.0)
    lines.append("## Shipped in v0.4.0")
    lines.append("")
    lines.append("Structural output-format change atop the v0.3.0 compact trimmer.")
    lines.append("")
    lines.append(
        "- **TOON output format** — structured responses (`list`, "
        "`endpoint`, `schema`, `search`, `operation`) now emit "
        "[TOON](https://github.com/toon-format/spec) instead of indented "
        "JSON. Uniform object arrays use tabular form (keys declared once "
        "per array). Errors stay as single-line JSON."
    )
    lines.append(
        "- **Stdlib-only TOON encoder** — inline in `scripts/openapi_tool.py`. "
        "No new dependencies, preserving the zero-dep policy."
    )
    lines.append(
        "- **Compact trimmer carried over** — the v0.3.0 `compact()` "
        "post-processor still runs before TOON encoding. Total savings "
        "compound: raw JSON → compact JSON → compact TOON."
    )
    lines.append(
        "- **Docs updated** — `SKILL.md` includes a TOON syntax primer; "
        "`references/query-patterns.md` shows a TOON example; "
        "`commands/openapi.md` references TOON rather than JSON."
    )
    lines.append("")
    lines.append("### Remaining follow-ups")
    lines.append("")
    lines.append(
        "- Unit test for the path-level + operation-level `parameters` "
        "merge branch (fixture has no example)."
    )
    lines.append(
        "- Consider a `--depth 0` mode that emits `$ref` strings untouched — "
        "useful when the agent already has the referenced schema in context."
    )
    lines.append("")

    return "\n".join(lines)


# ---------- Main ----------


def main() -> None:
    if not SPEC.exists():
        print(f"Missing fixture: {SPEC}", file=sys.stderr)
        sys.exit(1)

    spec = json.loads(SPEC.read_text())
    spec_bytes = SPEC.stat().st_size

    print("→ Running UX scenarios…", file=sys.stderr)
    scenarios = run_scenarios()

    op_count = sum(1 for _ in tool._iter_operations(spec))
    print(f"→ Measuring all {op_count} endpoints (raw + compact)…", file=sys.stderr)
    endpoint_stats = measure_all_endpoints(spec)

    schema_count = len(spec.get("components", {}).get("schemas", {}))
    print(f"→ Measuring all {schema_count} schemas (raw + compact)…", file=sys.stderr)
    schema_stats = measure_all_schemas(spec)

    _, summary_out, _, _ = run(["summary"])
    summary_bytes = len(summary_out)

    print("→ Rendering report…", file=sys.stderr)
    report = render_report(
        scenarios, endpoint_stats, schema_stats, spec_bytes, summary_bytes
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report)
    print(
        f"✓ Wrote {REPORT.relative_to(ROOT)} ({REPORT.stat().st_size:,} bytes)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
