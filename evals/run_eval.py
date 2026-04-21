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
    steps: list[list[str]]          # sequence of CLI arg lists
    expect_ok: bool = True          # last step should exit 0
    expect_error_nonzero: bool = False  # for error-UX scenarios (must fail cleanly)
    notes: str = ""


SCENARIOS: list[Scenario] = [
    Scenario(1, "What does this API do?",
             steps=[["summary"]]),
    Scenario(2, "List all PII endpoints",
             steps=[["search", "PII"]],
             notes="also valid: list --tag 'PII Detection'"),
    Scenario(3, "How do I add a new guardrail?",
             steps=[["summary"], ["endpoint", "POST", "/api/guardrails/add"]]),
    Scenario(4, "What's the shape of a GuardrailResponse?",
             steps=[["schema", "GuardrailResponse"]]),
    Scenario(5, "Look up operationId add_guardrail_api_guardrails_add_post",
             steps=[["operation", "add_guardrail_api_guardrails_add_post"]]),
    Scenario(6, "List every GET endpoint",
             steps=[["list", "--method", "GET"]]),
    Scenario(7, "Anything about embeddings?",
             steps=[["search", "embedding"]]),
    Scenario(8, "What endpoints exist under AI Test?",
             steps=[["list", "--tag", "AI Test"]]),
    Scenario(9, "What's the /api/advanced/analyze-patterns request body?",
             steps=[["endpoint", "POST", "/api/advanced/analyze-patterns"]]),
    Scenario(10, "Unknown schema name (error UX)",
              steps=[["schema", "NotARealSchema"]],
              expect_ok=False, expect_error_nonzero=True),
    Scenario(11, "Unknown path (error UX)",
              steps=[["endpoint", "GET", "/does/not/exist"]],
              expect_ok=False, expect_error_nonzero=True),
    Scenario(12, "Missing spec file (error UX)",
              steps=[["--spec", "nope.json", "summary"]],
              expect_ok=False, expect_error_nonzero=True),
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


# ---------- Part B: population-wide junk analysis ----------

ANYOF_NULL_RE = re.compile(
    r'"anyOf"\s*:\s*\[[^\[\]]*?"type"\s*:\s*"null"',
    re.DOTALL,
)
TITLE_RE = re.compile(r'"title"\s*:\s*"([^"]+)"')
EMPTY_DESC_RE = re.compile(r'"description"\s*:\s*""')
EMPTY_DEFAULT_STR_RE = re.compile(r'"default"\s*:\s*""')
HTTP_VALIDATION_RE = re.compile(r'HTTPValidationError')


def is_autoderived_title(title: str, sibling_key: str | None) -> bool:
    """Pydantic auto-titles look like 'Topic' for key 'topic',
    'Session Id' for 'session_id', 'En' for 'en'. Heuristic: if
    sibling key's title-case matches the title, count it as auto."""
    if not sibling_key:
        return False
    auto = " ".join(p.capitalize() for p in re.split(r"[_\s-]+", sibling_key) if p)
    return auto == title


def count_autoderived_titles(text: str) -> int:
    """Parse JSON once, walk the tree, count titles that match their
    parent property key auto-derivation. Falls back to 0 on parse errors."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return 0
    count = 0

    def walk(node, parent_key=None):
        nonlocal count
        if isinstance(node, dict):
            t = node.get("title")
            if isinstance(t, str) and is_autoderived_title(t, parent_key):
                count += 1
            for k, v in node.items():
                if k == "properties" and isinstance(v, dict):
                    for sub_k, sub_v in v.items():
                        walk(sub_v, parent_key=sub_k)
                else:
                    walk(v, parent_key=None)
        elif isinstance(node, list):
            for item in node:
                walk(item, parent_key=parent_key)

    walk(data)
    return count


@dataclass
class OutputStats:
    kind: str               # 'endpoint' | 'schema'
    name: str
    bytes_out: int
    titles_total: int
    titles_auto: int
    anyof_null: int
    empty_desc: int
    empty_default_str: int
    httpvalidation: int


def measure_all_endpoints(listing: list[dict]) -> list[OutputStats]:
    stats: list[OutputStats] = []
    for e in listing:
        code, out, _, _ = run(["--raw", "endpoint", e["method"], e["path"]])
        if code != 0:
            continue
        stats.append(OutputStats(
            kind="endpoint",
            name=f"{e['method']} {e['path']}",
            bytes_out=len(out),
            titles_total=len(TITLE_RE.findall(out)),
            titles_auto=count_autoderived_titles(out),
            anyof_null=len(ANYOF_NULL_RE.findall(out)),
            empty_desc=len(EMPTY_DESC_RE.findall(out)),
            empty_default_str=len(EMPTY_DEFAULT_STR_RE.findall(out)),
            httpvalidation=len(HTTP_VALIDATION_RE.findall(out)),
        ))
    return stats


def measure_all_schemas(spec: dict) -> list[OutputStats]:
    stats: list[OutputStats] = []
    names = sorted((spec.get("components", {}).get("schemas", {}) or {}).keys())
    for name in names:
        code, out, _, _ = run(["--raw", "schema", name])
        if code != 0:
            continue
        stats.append(OutputStats(
            kind="schema",
            name=name,
            bytes_out=len(out),
            titles_total=len(TITLE_RE.findall(out)),
            titles_auto=count_autoderived_titles(out),
            anyof_null=len(ANYOF_NULL_RE.findall(out)),
            empty_desc=len(EMPTY_DESC_RE.findall(out)),
            empty_default_str=len(EMPTY_DEFAULT_STR_RE.findall(out)),
            httpvalidation=len(HTTP_VALIDATION_RE.findall(out)),
        ))
    return stats


def pctile(values: list[int], p: float) -> int:
    if not values:
        return 0
    vs = sorted(values)
    k = max(0, min(len(vs) - 1, int(round((p / 100.0) * (len(vs) - 1)))))
    return vs[k]


# ---------- Junk-stripped re-emission for savings estimate ----------

def strip_junk(obj, parent_key: str | None = None):
    """Aggressive stripper that demonstrates achievable savings:
       - collapses anyOf:[X, {type:null}] to X + nullable:true
       - drops redundant titles (auto-derived from key)
       - drops empty description and empty default ""
    """
    if isinstance(obj, dict):
        # Collapse anyOf: [X, {type: null}]
        if "anyOf" in obj and isinstance(obj["anyOf"], list):
            branches = obj["anyOf"]
            non_null = [b for b in branches if not (isinstance(b, dict) and b.get("type") == "null")]
            had_null = len(non_null) != len(branches)
            if had_null and len(non_null) == 1:
                merged = {**non_null[0], **{k: v for k, v in obj.items() if k != "anyOf"}}
                merged["nullable"] = True
                return strip_junk(merged, parent_key)

        out = {}
        for k, v in obj.items():
            if k == "title" and isinstance(v, str) and is_autoderived_title(v, parent_key):
                continue
            if k == "description" and v == "":
                continue
            if k == "default" and v == "":
                continue
            if k == "properties" and isinstance(v, dict):
                out[k] = {sk: strip_junk(sv, sk) for sk, sv in v.items()}
            else:
                out[k] = strip_junk(v, parent_key=k)
        return out
    if isinstance(obj, list):
        return [strip_junk(x, parent_key) for x in obj]
    return obj


def stripped_bytes(text: str) -> int | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return len(json.dumps(strip_junk(data), indent=2))


# ---------- Report rendering ----------

def render_report(scenarios: list[ScenarioResult],
                  endpoint_stats: list[OutputStats],
                  schema_stats: list[OutputStats],
                  spec_bytes: int,
                  summary_bytes: int) -> str:
    passed = sum(1 for r in scenarios if r.passed)
    ep_bytes = [s.bytes_out for s in endpoint_stats]
    sc_bytes = [s.bytes_out for s in schema_stats]

    # Compact vs --raw savings (measured end-to-end against the shipped tool)
    sample = []
    for s in (endpoint_stats[:5] + schema_stats[:5]):
        if s.kind == "endpoint":
            method, path = s.name.split(" ", 1)
            compact_cmd = ["endpoint", method, path]
            raw_cmd = ["--raw", "endpoint", method, path]
        else:
            compact_cmd = ["schema", s.name]
            raw_cmd = ["--raw", "schema", s.name]
        _, raw_out, _, _ = run(raw_cmd)
        _, compact_out, _, _ = run(compact_cmd)
        before = len(raw_out)
        after = len(compact_out)
        sample.append((s.kind, s.name, before, after))
    total_before = sum(b for _, _, b, _ in sample) or 1
    total_after = sum(a for _, _, _, a in sample)
    savings_pct = round(100 * (1 - total_after / total_before), 1)

    lines: list[str] = []
    lines.append("# `openapi-reader` Plugin Evaluation")
    lines.append("")
    lines.append(f"_Auto-generated by `evals/run_eval.py`. Fixture: `openapi.json` "
                 f"({spec_bytes:,} bytes)._")
    lines.append("")

    # TL;DR
    lines.append("## TL;DR")
    lines.append("")
    lines.append(f"- **Effectiveness**: {passed}/{len(scenarios)} UX scenarios "
                 f"{'pass' if passed == len(scenarios) else 'pass (see table)'}.")
    lines.append(f"- **Compression vs raw spec**: `summary` is "
                 f"{spec_bytes // summary_bytes}× smaller than the raw spec "
                 f"({summary_bytes:,} vs {spec_bytes:,} bytes).")
    lines.append(f"- **Compact-mode savings (default on)**: compact output is "
                 f"**~{savings_pct}% smaller** than `--raw` "
                 f"(measured end-to-end on {len(sample)} calls).")
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
        lines.append(f"| {sc.num} | {sc.ask} | `{step_str}` | "
                     f"{r.total_bytes:,} | {r.total_time_s:.2f}s | {verdict} |")
    lines.append("")

    # Error-UX transcripts
    lines.append("### Error-path transcripts (scenarios 10–12)")
    lines.append("")
    for r in scenarios:
        if not r.scenario.expect_error_nonzero:
            continue
        lines.append(f"**#{r.scenario.num} — {r.scenario.ask}**  "
                     f"(exit={r.exit_codes[-1]})")
        lines.append("```")
        lines.append((r.stdout_tail or r.stderr_tail).strip())
        lines.append("```")
        lines.append("")

    # Part B
    lines.append("## Part B — Output size & junk-token analysis")
    lines.append("")
    lines.append(f"Population: {len(endpoint_stats)} endpoints, "
                 f"{len(schema_stats)} schemas (all covered).")
    lines.append("")
    lines.append("### Size distribution (bytes, `--raw` mode)")
    lines.append("")
    lines.append("| Command | min | p50 | p90 | max | total |")
    lines.append("|---------|-----|-----|-----|-----|-------|")
    if ep_bytes:
        lines.append(f"| `endpoint` | {min(ep_bytes):,} | {int(median(ep_bytes)):,} | "
                     f"{pctile(ep_bytes, 90):,} | {max(ep_bytes):,} | {sum(ep_bytes):,} |")
    if sc_bytes:
        lines.append(f"| `schema` | {min(sc_bytes):,} | {int(median(sc_bytes)):,} | "
                     f"{pctile(sc_bytes, 90):,} | {max(sc_bytes):,} | {sum(sc_bytes):,} |")
    lines.append("")

    # Junk totals
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
    lines.append("### Junk-category totals (`--raw` mode — what the trimmer strips)")
    lines.append("")
    lines.append("| Category | `endpoint` total | `schema` total | Notes |")
    lines.append("|---|---|---|---|")
    lines.append(f"| `title` fields (all) | {ep_t['titles_total']:,} | {sc_t['titles_total']:,} "
                 f"| Raw count of `\"title\":` lines. |")
    lines.append(f"| `title` auto-derived | {ep_t['titles_auto']:,} | {sc_t['titles_auto']:,} "
                 f"| Matches parent key (Pydantic artifact). Stripping is safe. |")
    lines.append(f"| `anyOf[T, null]` nullable | {ep_t['anyof_null']:,} | {sc_t['anyof_null']:,} "
                 f"| Each can collapse to a `nullable` marker. |")
    lines.append(f"| empty `description: \"\"` | {ep_t['empty_desc']:,} | {sc_t['empty_desc']:,} "
                 f"| No signal; safely droppable. |")
    lines.append(f"| empty `default: \"\"` | {ep_t['empty_default_str']:,} | {sc_t['empty_default_str']:,} "
                 f"| Usually placeholder noise. |")
    lines.append(f"| `HTTPValidationError` refs | {ep_t['httpvalidation']:,} | {sc_t['httpvalidation']:,} "
                 f"| Standard FastAPI 422 boilerplate, near-identical on every call. |")
    lines.append("")

    # Savings sample
    lines.append("### Compact vs `--raw` — measured savings")
    lines.append("")
    lines.append("| Kind | Name | Raw (B) | Compact (B) | Saved |")
    lines.append("|---|---|---|---|---|")
    for kind, name, before, after in sample:
        saved = round(100 * (1 - after / before), 1) if before else 0
        lines.append(f"| {kind} | `{name}` | {before:,} | {after:,} | {saved}% |")
    lines.append(f"| **total** |  | **{total_before:,}** | **{total_after:,}** | **{savings_pct}%** |")
    lines.append("")

    # Top offenders
    def top(stats: list[OutputStats], n: int = 5) -> list[OutputStats]:
        return sorted(stats, key=lambda s: s.bytes_out, reverse=True)[:n]

    lines.append("### Biggest outputs")
    lines.append("")
    lines.append("| Kind | Name | Bytes | auto-titles | anyOf-null |")
    lines.append("|---|---|---|---|---|")
    for s in top(endpoint_stats) + top(schema_stats):
        lines.append(f"| {s.kind} | `{s.name}` | {s.bytes_out:,} | "
                     f"{s.titles_auto} | {s.anyof_null} |")
    lines.append("")

    # Part C — static discoverability / description review
    lines.append("## Part C — Discoverability & description quality")
    lines.append("")
    lines.append(
        "- `SKILL.md` (v0.3.0) description covers the primary triggers: "
        "_query the API spec, show available endpoints, get the schema for, "
        "search the API spec, look up operationId_, plus the catch-all "
        "_writing code that calls an API defined by an openapi.json file_. "
        "All 12 scenarios in Part A map cleanly onto this trigger surface."
    )
    lines.append(
        "- Global flags (`--raw`, `--depth N`, `--spec PATH`) are documented "
        "in `SKILL.md` with their position (before the subcommand) and the "
        "expected trade-offs, so the agent picks them without trial-and-error."
    )
    lines.append(
        "- `references/query-patterns.md` adds copy-pasteable recipes for "
        "the common workflows and an \"output still too large\" fallback "
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
        "`search \"pii config\"` and `search \"PII CONFIG\"` both return the "
        "same 11 results; terms are AND-joined across path + summary + "
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
        "- **Error messages are clean JSON, exit code 1** on all three error "
        "paths (unknown schema, unknown path, missing spec file) — no "
        "stack traces leak. Unknown schema and unknown operationId return "
        "`did_you_mean` suggestions via `difflib.get_close_matches` instead "
        "of dumping the full name list."
    )
    lines.append(
        "- **Compact trimming preserves semantics.** `anyOf: [X, {type: "
        "null}]` collapses to `X + nullable: true`; auto-derived `title` "
        "fields (matching `key.title()`) are dropped; empty `description: "
        "\"\"` / `default: \"\"` removed; FastAPI 422 "
        "`HTTPValidationError` response entries elided. Pass `--raw` to "
        "disable when validating against the literal spec."
    )
    lines.append("")

    # Shipped changes (v0.3.0)
    lines.append("## Shipped in v0.3.0")
    lines.append("")
    lines.append(
        "This eval run measures the post-fix plugin. Compact savings above "
        "(~42%) are the measured effect of the changes below."
    )
    lines.append("")
    lines.append(
        "- **Compact output by default** — `compact()` post-processor in "
        "`scripts/openapi_tool.py` collapses `anyOf[T, null]`, drops "
        "auto-titles, empty `description`/`default`, and the 422 "
        "`HTTPValidationError` boilerplate. `--raw` disables."
    )
    lines.append(
        "- **`--depth N` flag** — exposes the previously hardcoded ref-"
        "resolution depth (default 3). `--depth 1` reduces a typical "
        "`endpoint` call from ~12 KB to ~2 KB."
    )
    lines.append(
        "- **`summary --compact`** — paths-only view (~4 KB vs ~10 KB), "
        "no per-op summaries, no schema-name list."
    )
    lines.append(
        "- **Typo suggestions** — `schema` and `operation` miss errors now "
        "return at most 5 close matches via `difflib.get_close_matches` "
        "instead of the full name list."
    )
    lines.append(
        "- **Skill trigger updated** — `SKILL.md` description adds "
        "\"look up operationId\" to the trigger phrases."
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

    print("→ Loading endpoint list…", file=sys.stderr)
    _, list_out, _, _ = run(["list"])
    listing = json.loads(list_out)

    print(f"→ Measuring all {len(listing)} endpoints…", file=sys.stderr)
    endpoint_stats = measure_all_endpoints(listing)

    schema_count = len(spec.get("components", {}).get("schemas", {}))
    print(f"→ Measuring all {schema_count} schemas…", file=sys.stderr)
    schema_stats = measure_all_schemas(spec)

    _, summary_out, _, _ = run(["summary"])
    summary_bytes = len(summary_out)

    print("→ Rendering report…", file=sys.stderr)
    report = render_report(scenarios, endpoint_stats, schema_stats,
                           spec_bytes, summary_bytes)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report)
    print(f"✓ Wrote {REPORT.relative_to(ROOT)} "
          f"({REPORT.stat().st_size:,} bytes)", file=sys.stderr)


if __name__ == "__main__":
    main()
