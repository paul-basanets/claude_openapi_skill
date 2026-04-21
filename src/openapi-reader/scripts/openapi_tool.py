#!/usr/bin/env python3
"""OpenAPI spec query tool — stdlib only, no dependencies."""

import argparse
import json
import sys
from pathlib import Path


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


def resolve_refs(obj, spec: dict, seen: frozenset = frozenset(), depth: int = 0):
    if depth >= 3:
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
            return resolve_refs(merged, spec, seen | {ref}, depth + 1)
        return {k: resolve_refs(v, spec, seen, depth) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_refs(item, spec, seen, depth) for item in obj]
    return obj


def _iter_operations(spec: dict):
    """Yield (path, method, operation_dict) for every operation in the spec."""
    methods = ("get", "post", "put", "delete", "patch", "head", "options")
    for path, path_item in spec.get("paths", {}).items():
        for method in methods:
            op = path_item.get(method)
            if op is not None:
                yield path, method, op


def cmd_summary(spec: dict) -> None:
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


def cmd_endpoint(spec: dict, method: str, path: str) -> None:
    path_item = spec.get("paths", {}).get(path)
    if path_item is None:
        print(json.dumps({"error": f"Path not found: {path}"}))
        sys.exit(1)
    op = path_item.get(method.lower())
    if op is None:
        print(json.dumps({"error": f"Method {method.upper()} not found at {path}"}))
        sys.exit(1)

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
        "parameters": resolve_refs(final_params, spec),
        "security": op.get("security"),
    }
    if "requestBody" in op:
        result["requestBody"] = resolve_refs(op["requestBody"], spec)
    result["responses"] = resolve_refs(op.get("responses", {}), spec)

    print(json.dumps({k: v for k, v in result.items() if v is not None}, indent=2))


def cmd_schema(spec: dict, name: str) -> None:
    schemas = spec.get("components", {}).get("schemas", {})
    schema = schemas.get(name)
    if schema is None:
        available = sorted(schemas)
        print(json.dumps({"error": f"Schema not found: {name}", "available_count": len(available), "available": available}))
        sys.exit(1)
    print(json.dumps(resolve_refs(schema, spec), indent=2))


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


def cmd_operation(spec: dict, operation_id: str) -> None:
    for path, method, op in _iter_operations(spec):
        if op.get("operationId") == operation_id:
            cmd_endpoint(spec, method, path)
            return

    available = sorted(
        op.get("operationId", "")
        for _, _, op in _iter_operations(spec)
        if op.get("operationId")
    )
    print(json.dumps({
        "error": f"operationId not found: {operation_id}",
        "available_count": len(available),
        "available": available,
    }))
    sys.exit(1)


def main() -> None:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--spec", default="openapi.json", help="Path to OpenAPI JSON spec (default: openapi.json)")
    pre_args, remaining = pre.parse_known_args()

    parser = argparse.ArgumentParser(description="Query an OpenAPI spec efficiently")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("summary", help="Compact API overview: endpoints by tag, schema names")

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
    spec = load_spec(args.spec)

    match args.command:
        case "summary":
            cmd_summary(spec)
        case "list":
            cmd_list(spec, tag=args.tag, method=args.method)
        case "endpoint":
            cmd_endpoint(spec, args.method, args.path)
        case "schema":
            cmd_schema(spec, args.name)
        case "search":
            cmd_search(spec, " ".join(args.query))
        case "operation":
            cmd_operation(spec, args.operation_id)


if __name__ == "__main__":
    main()
