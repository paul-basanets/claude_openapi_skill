#!/usr/bin/env python3
"""OpenAPI spec query tool — stdlib only, no dependencies."""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

DEFAULT_DEPTH = 3


def load_spec(spec_path: str) -> dict:
    path = Path(spec_path)
    if not path.exists():
        print(json.dumps({"error": f"Spec file not found: {spec_path}"}))
        sys.exit(1)
    with open(path) as f:
        try:
            spec = json.load(f)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON in spec file: {spec_path}: {e}"}))
            sys.exit(1)
    version_str = spec.get("openapi", spec.get("swagger", ""))
    if not str(version_str).startswith("3"):
        print(
            json.dumps({"warning": f"Spec version '{version_str}' is not OpenAPI 3.x; output may be incorrect"}),
            file=sys.stderr,
        )
    return spec


def resolve_ref(ref: str, spec: dict) -> dict:
    if not ref.startswith("#/"):
        return {"$ref": ref}
    parts = ref[2:].split("/")
    node = spec
    try:
        for part in parts:
            node = node[part]
    except KeyError:
        return {"error": f"Unresolvable $ref: {ref}"}
    return node


def resolve_refs(obj, spec: dict, seen: frozenset = frozenset(), depth: int = 0, max_depth: int = DEFAULT_DEPTH):
    if depth >= max_depth:
        return obj
    if isinstance(obj, dict):
        if "$ref" in obj:
            ref = obj["$ref"]
            if not ref.startswith("#/"):
                return obj
            if ref in seen:
                return {"$ref": ref}
            resolved = resolve_ref(ref, spec)
            merged = {**resolved, **{k: v for k, v in obj.items() if k != "$ref"}}
            return resolve_refs(merged, spec, seen | {ref}, depth + 1, max_depth)
        return {k: resolve_refs(v, spec, seen, depth, max_depth) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_refs(item, spec, seen, depth, max_depth) for item in obj]
    return obj


def _iter_operations(spec: dict):
    """Yield (path, method, operation_dict) for every operation in the spec."""
    methods = ("get", "post", "put", "delete", "patch", "head", "options")
    for path, path_item in spec.get("paths", {}).items():
        for method in methods:
            op = path_item.get(method)
            if op is not None:
                yield path, method, op


# ---------- compact() — junk-token trimmer ----------

_SEP_RE = re.compile(r"[_\s-]+")


def _auto_title(key: str) -> str:
    return " ".join(p.capitalize() for p in _SEP_RE.split(key) if p)


def _is_http_validation_error(node) -> bool:
    """True if a response entry is the FastAPI 422 boilerplate."""
    if not isinstance(node, dict):
        return False
    content = node.get("content", {})
    schema = content.get("application/json", {}).get("schema", {})
    if schema.get("title") == "HTTPValidationError":
        return True
    ref = schema.get("$ref", "")
    return ref.endswith("/HTTPValidationError")


def compact(obj, parent_key: str | None = None):
    """
    Post-process resolved output to remove low-signal tokens:
      - collapse anyOf: [T, {type: null}]  →  T + nullable: true
      - drop title when it auto-derives from the property key
      - drop empty description: "" and default: ""
      - drop 422 HTTPValidationError response entries (boilerplate)
    """
    if isinstance(obj, dict):
        branches = obj.get("anyOf")
        if isinstance(branches, list):
            non_null = [b for b in branches if not (isinstance(b, dict) and b.get("type") == "null")]
            if len(non_null) != len(branches) and len(non_null) == 1:
                merged = {**non_null[0], **{k: v for k, v in obj.items() if k != "anyOf"}}
                merged["nullable"] = True
                return compact(merged, parent_key)

        out: dict = {}
        for k, v in obj.items():
            if k == "title" and isinstance(v, str) and parent_key and v == _auto_title(parent_key):
                continue
            if k == "description" and v == "":
                continue
            if k == "default" and v == "":
                continue
            if k == "responses" and isinstance(v, dict):
                out[k] = {
                    code: compact(resp, parent_key=None)
                    for code, resp in v.items()
                    if not (code == "422" and _is_http_validation_error(resp))
                }
                continue
            if k == "properties" and isinstance(v, dict):
                out[k] = {sk: compact(sv, parent_key=sk) for sk, sv in v.items()}
                continue
            out[k] = compact(v, parent_key=None)
        return out
    if isinstance(obj, list):
        return [compact(x, parent_key) for x in obj]
    return obj


# ---------- subcommands ----------

def cmd_summary(spec: dict, compact_mode: bool = False) -> None:
    info = spec.get("info", {})
    schemas = spec.get("components", {}).get("schemas", {})

    tag_ops: dict[str, list] = {}
    total_ops = 0
    for path, method, op in _iter_operations(spec):
        total_ops += 1
        for tag in op.get("tags", ["Untagged"]):
            tag_ops.setdefault(tag, []).append((method.upper(), path, op.get("summary", "")))

    lines = [
        f"OpenAPI: {info.get('title', 'Unknown')} v{info.get('version', '?')}",
        f"{total_ops} operations  |  {len(spec.get('paths', {}))} paths  |  {len(schemas)} schemas",
        "",
    ]

    if compact_mode:
        for tag in sorted(tag_ops):
            ops = sorted(tag_ops[tag], key=lambda x: (x[1], x[0]))
            lines.append(f"## {tag} ({len(ops)})")
            paths = sorted({path for _, path, _ in ops})
            for path in paths:
                methods = sorted({m for m, p, _ in ops if p == path})
                lines.append(f"  {'/'.join(methods):<20} {path}")
            lines.append("")
        lines.append(f"## Schemas ({len(schemas)}): run `schema NAME` to fetch one.")
    else:
        for tag in sorted(tag_ops):
            ops = sorted(tag_ops[tag], key=lambda x: (x[1], x[0]))
            lines.append(f"## {tag} ({len(ops)})")
            for method, path, summary in ops:
                lines.append(f"  {method:<7} {path}  —  {summary}")
            lines.append("")
        lines.append("## Schemas")
        lines.append(", ".join(sorted(schemas)))

    print("\n".join(lines))


def cmd_list(spec: dict, tag: str | None = None, method: str | None = None) -> None:
    results = []
    for path, m, op in _iter_operations(spec):
        if method and m.upper() != method.upper():
            continue
        tags = op.get("tags", [])
        if tag and not any(tag.lower() in t.lower() for t in tags):
            continue
        results.append({
            "path": path,
            "method": m.upper(),
            "operationId": op.get("operationId", ""),
            "summary": op.get("summary", ""),
            "tags": tags,
        })
    results.sort(key=lambda x: (x["path"], x["method"]))
    print(json.dumps(results, indent=2))


def _build_endpoint(spec: dict, method: str, path: str, max_depth: int) -> dict | None:
    path_item = spec.get("paths", {}).get(path)
    if path_item is None:
        return None
    op = path_item.get(method.lower())
    if op is None:
        return None

    path_params = path_item.get("parameters", [])
    op_params = op.get("parameters", [])
    merged_params: dict[tuple, dict] = {}
    path_extras: list = []
    for p in path_params:
        key = (p.get("name"), p.get("in"))
        if key == (None, None):
            path_extras.append(p)
        else:
            merged_params[key] = p
    op_extras: list = []
    for p in op_params:
        key = (p.get("name"), p.get("in"))
        if key == (None, None):
            op_extras.append(p)
        else:
            merged_params[key] = p
    final_params = path_extras + list(merged_params.values()) + op_extras

    result: dict = {
        "path": path,
        "method": method.upper(),
        "summary": op.get("summary", ""),
        "description": op.get("description", ""),
        "operationId": op.get("operationId", ""),
        "tags": op.get("tags", []),
        "parameters": resolve_refs(final_params, spec, max_depth=max_depth),
        "security": op.get("security"),
    }
    if "requestBody" in op:
        result["requestBody"] = resolve_refs(op["requestBody"], spec, max_depth=max_depth)
    result["responses"] = resolve_refs(op.get("responses", {}), spec, max_depth=max_depth)
    return {k: v for k, v in result.items() if v is not None}


def cmd_endpoint(spec: dict, method: str, path: str, *, raw: bool, max_depth: int) -> None:
    if path not in spec.get("paths", {}):
        print(json.dumps({"error": f"Path not found: {path}"}))
        sys.exit(1)
    if spec["paths"][path].get(method.lower()) is None:
        print(json.dumps({"error": f"Method {method.upper()} not found at {path}"}))
        sys.exit(1)

    result = _build_endpoint(spec, method, path, max_depth)
    assert result is not None
    if not raw:
        result = compact(result)
    print(json.dumps(result, indent=2))


def cmd_schema(spec: dict, name: str, *, raw: bool, max_depth: int) -> None:
    schemas = spec.get("components", {}).get("schemas", {})
    schema = schemas.get(name)
    if schema is None:
        available = sorted(schemas)
        suggestions = difflib.get_close_matches(name, available, n=5, cutoff=0.6)
        err = {"error": f"Schema not found: {name}", "available_count": len(available)}
        if suggestions:
            err["did_you_mean"] = suggestions
        err["hint"] = "Run `list` then grep, or re-call with an exact name."
        print(json.dumps(err))
        sys.exit(1)
    resolved = resolve_refs(schema, spec, max_depth=max_depth)
    if not raw:
        resolved = compact(resolved, parent_key=name)
    print(json.dumps(resolved, indent=2))


def cmd_search(spec: dict, query: str) -> None:
    q = query.lower()
    terms = q.split()
    results = []

    for path, method, op in _iter_operations(spec):
        param_texts = []
        for p in op.get("parameters", []):
            param_texts.append(p.get("name", ""))
            param_texts.append(p.get("description", ""))
        haystack = " ".join([
            path,
            op.get("summary", ""),
            op.get("description", ""),
            op.get("operationId", ""),
            *op.get("tags", []),
            *param_texts,
        ]).lower()
        if not all(t in haystack for t in terms):
            continue
        results.append({
            "type": "endpoint",
            "method": method.upper(),
            "path": path,
            "summary": op.get("summary", ""),
            "tags": op.get("tags", []),
        })

    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        haystack = " ".join([
            name,
            schema.get("description", ""),
            *schema.get("properties", {}).keys(),
        ]).lower()
        if not all(t in haystack for t in terms):
            continue
        results.append({
            "type": "schema",
            "name": name,
            "description": schema.get("description", ""),
        })

    print(json.dumps(results, indent=2))


def cmd_operation(spec: dict, operation_id: str, *, raw: bool, max_depth: int) -> None:
    for path, method, op in _iter_operations(spec):
        if op.get("operationId") == operation_id:
            cmd_endpoint(spec, method, path, raw=raw, max_depth=max_depth)
            return

    available = sorted(
        op.get("operationId", "")
        for _, _, op in _iter_operations(spec)
        if op.get("operationId")
    )
    suggestions = difflib.get_close_matches(operation_id, available, n=5, cutoff=0.6)
    err = {"error": f"operationId not found: {operation_id}", "available_count": len(available)}
    if suggestions:
        err["did_you_mean"] = suggestions
    err["hint"] = "Run `list` to see operationIds, or use `endpoint METHOD PATH`."
    print(json.dumps(err))
    sys.exit(1)


def main() -> None:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--spec", default="openapi.json", help="Path to OpenAPI JSON spec (default: openapi.json)")
    pre.add_argument("--raw", action="store_true", help="Disable compact trimming; emit raw OpenAPI output")
    pre.add_argument("--depth", type=int, default=DEFAULT_DEPTH,
                     help=f"Max $ref resolution depth (default: {DEFAULT_DEPTH})")
    pre_args, remaining = pre.parse_known_args()

    parser = argparse.ArgumentParser(description="Query an OpenAPI spec efficiently")
    sub = parser.add_subparsers(dest="command", required=True)

    sum_p = sub.add_parser("summary", help="Compact API overview: endpoints by tag, schema names")
    sum_p.add_argument("--compact", action="store_true",
                       help="Ultra-short: paths-only list, no summaries, no schema names")

    list_p = sub.add_parser("list", help="List endpoints as JSON (optional filters)")
    list_p.add_argument("--tag", help="Filter by tag name")
    list_p.add_argument("--method", help="Filter by HTTP method (GET, POST, ...)")

    ep = sub.add_parser("endpoint", help="Full operation detail with resolved schemas")
    ep.add_argument("method", help="HTTP method, e.g. POST")
    ep.add_argument("path", help="API path, e.g. /api/guardrails/add")

    sc = sub.add_parser("schema", help="Schema definition with resolved $refs")
    sc.add_argument("name", help="Schema name, e.g. GuardrailResponse")

    sr = sub.add_parser("search", help="Full-text search across endpoints and schemas")
    sr.add_argument("query", nargs="+", help="Search terms")

    op_p = sub.add_parser("operation", help="Full operation detail looked up by operationId")
    op_p.add_argument("operation_id", help="operationId, e.g. add_guardrail_api_guardrails_add_post")

    args = parser.parse_args(remaining)
    args.spec = pre_args.spec
    args.raw = pre_args.raw
    args.depth = pre_args.depth
    spec = load_spec(args.spec)

    match args.command:
        case "summary":
            cmd_summary(spec, compact_mode=args.compact)
        case "list":
            cmd_list(spec, tag=args.tag, method=args.method)
        case "endpoint":
            cmd_endpoint(spec, args.method, args.path, raw=args.raw, max_depth=args.depth)
        case "schema":
            cmd_schema(spec, args.name, raw=args.raw, max_depth=args.depth)
        case "search":
            cmd_search(spec, " ".join(args.query))
        case "operation":
            cmd_operation(spec, args.operation_id, raw=args.raw, max_depth=args.depth)


if __name__ == "__main__":
    main()
