#!/usr/bin/env python3
"""OpenAPI spec query tool — stdlib only, no dependencies.

Output format: TOON (Token-Oriented Object Notation) — see
https://github.com/toon-format/spec for the format rules. Encoder is inline
below to preserve the zero-dep policy. Error payloads stay as single-line
JSON for tiny-object parse simplicity.
"""

import argparse
import difflib
import hashlib
import json
import os
import re
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_DEPTH = 3
CACHE_TTL_SECONDS = 3600
CACHE_DIR_NAME = "openapi-reader-cache"
URL_FETCH_TIMEOUT = 30


def _cache_path_for_url(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / CACHE_DIR_NAME / f"{digest}.json"


def _load_from_url(url: str, refresh: bool) -> dict:
    cache_file = _cache_path_for_url(url)
    if not refresh and cache_file.exists():
        if time.time() - cache_file.stat().st_mtime < CACHE_TTL_SECONDS:
            try:
                with open(cache_file) as f:
                    return json.load(f)
            except OSError, json.JSONDecodeError:
                pass  # fall through to re-fetch
    try:
        with urllib.request.urlopen(url, timeout=URL_FETCH_TIMEOUT) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        print(
            json.dumps(
                {"error": f"HTTP {e.code} fetching spec: {e.reason}", "url": url}
            )
        )
        sys.exit(1)
    except urllib.error.URLError as e:
        print(
            json.dumps(
                {"error": f"Network error fetching spec: {e.reason}", "url": url}
            )
        )
        sys.exit(1)
    except socket.timeout:
        print(
            json.dumps(
                {
                    "error": f"Timeout after {URL_FETCH_TIMEOUT}s fetching spec",
                    "url": url,
                }
            )
        )
        sys.exit(1)
    try:
        spec = json.loads(body)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON from URL: {e}", "url": url}))
        sys.exit(1)
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(cache_file.suffix + ".tmp")
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, cache_file)
    except OSError:
        pass  # cache best-effort; still return the fetched spec
    return spec


def load_spec(spec_path: str, refresh: bool = False) -> dict:
    if spec_path.startswith(("http://", "https://")):
        spec = _load_from_url(spec_path, refresh=refresh)
    else:
        path = Path(spec_path)
        if not path.exists():
            print(json.dumps({"error": f"Spec file not found: {spec_path}"}))
            sys.exit(1)
        with open(path) as f:
            try:
                spec = json.load(f)
            except json.JSONDecodeError as e:
                print(
                    json.dumps(
                        {"error": f"Invalid JSON in spec file: {spec_path}: {e}"}
                    )
                )
                sys.exit(1)
    version_str = spec.get("openapi", spec.get("swagger", ""))
    if not str(version_str).startswith("3"):
        print(
            json.dumps(
                {
                    "warning": f"Spec version '{version_str}' is not OpenAPI 3.x; output may be incorrect"
                }
            ),
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


def resolve_refs(
    obj,
    spec: dict,
    seen: frozenset = frozenset(),
    depth: int = 0,
    max_depth: int = DEFAULT_DEPTH,
):
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
        return {
            k: resolve_refs(v, spec, seen, depth, max_depth) for k, v in obj.items()
        }
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


# ---------- TOON encoder (stdlib, subset of the spec we need) ----------

_TOON_RESERVED_RE = re.compile(r'[:"\\\[\]{},\n\r\t]')
_TOON_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?([eE][+-]?\d+)?$")


def _toon_needs_quote(s: str) -> bool:
    if s == "":
        return True
    if s[0].isspace() or s[-1].isspace():
        return True
    if s in ("true", "false", "null"):
        return True
    if _TOON_NUMERIC_RE.match(s):
        return True
    if len(s) >= 2 and s[0] == "0" and s[1].isdigit():
        return True
    if s[0] == "-":
        return True
    return bool(_TOON_RESERVED_RE.search(s))


def _toon_quote_str(s: str) -> str:
    escaped = (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return '"' + escaped + '"'


def _toon_prim(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return _toon_quote_str(repr(v))
        if v.is_integer():
            return str(int(v))
        return repr(v)
    s = v if isinstance(v, str) else str(v)
    return _toon_quote_str(s) if _toon_needs_quote(s) else s


def _toon_key(k) -> str:
    s = k if isinstance(k, str) else str(k)
    return _toon_quote_str(s) if _toon_needs_quote(s) else s


def _is_primitive(v) -> bool:
    return v is None or isinstance(v, (bool, int, float, str))


def _toon_field(
    key, value, lines: list, prefix: str, nested_depth: int, pad_unit: str
) -> None:
    """Emit `<prefix>key: value`. Nested content goes at `nested_depth`."""
    k = _toon_key(key)
    if _is_primitive(value):
        lines.append(f"{prefix}{k}: {_toon_prim(value)}")
        return
    if isinstance(value, dict):
        lines.append(f"{prefix}{k}:")
        if not value:
            return
        child_pad = pad_unit * nested_depth
        for sk, sv in value.items():
            _toon_field(sk, sv, lines, child_pad, nested_depth + 1, pad_unit)
        return
    if isinstance(value, list):
        _toon_array(k, value, lines, prefix, nested_depth, pad_unit)
        return
    lines.append(f"{prefix}{k}: {_toon_prim(value)}")


def _toon_array(
    key_str: str,
    items: list,
    lines: list,
    prefix: str,
    nested_depth: int,
    pad_unit: str,
) -> None:
    """Emit an array header and body.

    `prefix` is the start of the header line (including any indent + dash).
    `key_str` is the (pre-quoted) key or "" for root/anonymous arrays.
    Nested content goes at `nested_depth`.
    """
    n = len(items)
    head = f"{prefix}{key_str}[{n}]"

    if n == 0:
        lines.append(f"{head}:")
        return

    if all(_is_primitive(it) for it in items):
        vals = ",".join(_toon_prim(it) for it in items)
        lines.append(f"{head}: {vals}")
        return

    if all(isinstance(it, dict) for it in items):
        first_keys = list(items[0].keys())
        first_set = set(first_keys)
        if all(set(it.keys()) == first_set for it in items) and all(
            _is_primitive(it[k]) for it in items for k in first_keys
        ):
            fields = ",".join(_toon_key(k) for k in first_keys)
            lines.append(f"{head}{{{fields}}}:")
            row_pad = pad_unit * nested_depth
            for it in items:
                row = ",".join(_toon_prim(it[k]) for k in first_keys)
                lines.append(f"{row_pad}{row}")
            return

    lines.append(f"{head}:")
    item_pad = pad_unit * nested_depth
    for it in items:
        _toon_list_item(it, lines, item_pad, nested_depth, pad_unit)


def _toon_list_item(item, lines: list, pad: str, depth: int, pad_unit: str) -> None:
    """Emit a single list item prefixed with `- ` at column len(pad)."""
    if _is_primitive(item):
        lines.append(f"{pad}- {_toon_prim(item)}")
        return
    if isinstance(item, dict):
        if not item:
            lines.append(f"{pad}-")
            return
        keys = list(item.keys())
        first_k, first_v = keys[0], item[keys[0]]
        _toon_field(
            first_k,
            first_v,
            lines,
            prefix=f"{pad}- ",
            nested_depth=depth + 1,
            pad_unit=pad_unit,
        )
        cont_pad = pad_unit * (depth + 1)
        for k in keys[1:]:
            _toon_field(k, item[k], lines, cont_pad, depth + 2, pad_unit)
        return
    if isinstance(item, list):
        _toon_array("", item, lines, f"{pad}- ", depth + 1, pad_unit)
        return
    lines.append(f"{pad}- {_toon_prim(item)}")


def _toon_dumps(obj, indent: int = 2) -> str:
    lines: list[str] = []
    pad_unit = " " * indent
    if isinstance(obj, dict):
        if obj:
            for k, v in obj.items():
                _toon_field(k, v, lines, "", 1, pad_unit)
    elif isinstance(obj, list):
        _toon_array("", obj, lines, "", 1, pad_unit)
    else:
        lines.append(_toon_prim(obj))
    return "\n".join(lines)


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
            non_null = [
                b
                for b in branches
                if not (isinstance(b, dict) and b.get("type") == "null")
            ]
            if len(non_null) != len(branches) and len(non_null) == 1:
                merged = {
                    **non_null[0],
                    **{k: v for k, v in obj.items() if k != "anyOf"},
                }
                merged["nullable"] = True
                return compact(merged, parent_key)

        out: dict = {}
        for k, v in obj.items():
            if (
                k == "title"
                and isinstance(v, str)
                and parent_key
                and v == _auto_title(parent_key)
            ):
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
            tag_ops.setdefault(tag, []).append(
                (method.upper(), path, op.get("summary", ""))
            )

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
        results.append(
            {
                "path": path,
                "method": m.upper(),
                "operationId": op.get("operationId", ""),
                "summary": op.get("summary", ""),
                "tags": tags,
            }
        )
    results.sort(key=lambda x: (x["path"], x["method"]))
    print(_toon_dumps(results))


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
        result["requestBody"] = resolve_refs(
            op["requestBody"], spec, max_depth=max_depth
        )
    result["responses"] = resolve_refs(
        op.get("responses", {}), spec, max_depth=max_depth
    )
    return {k: v for k, v in result.items() if v is not None}


def cmd_endpoint(
    spec: dict, method: str, path: str, *, raw: bool, max_depth: int
) -> None:
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
    print(_toon_dumps(result))


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
    print(_toon_dumps(resolved))


def cmd_search(spec: dict, query: str) -> None:
    q = query.lower()
    terms = q.split()
    results = []

    for path, method, op in _iter_operations(spec):
        param_texts = []
        for p in op.get("parameters", []):
            param_texts.append(p.get("name", ""))
            param_texts.append(p.get("description", ""))
        haystack = " ".join(
            [
                path,
                op.get("summary", ""),
                op.get("description", ""),
                op.get("operationId", ""),
                *op.get("tags", []),
                *param_texts,
            ]
        ).lower()
        if not all(t in haystack for t in terms):
            continue
        results.append(
            {
                "type": "endpoint",
                "method": method.upper(),
                "path": path,
                "summary": op.get("summary", ""),
                "tags": op.get("tags", []),
            }
        )

    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        haystack = " ".join(
            [
                name,
                schema.get("description", ""),
                *schema.get("properties", {}).keys(),
            ]
        ).lower()
        if not all(t in haystack for t in terms):
            continue
        results.append(
            {
                "type": "schema",
                "name": name,
                "description": schema.get("description", ""),
            }
        )

    print(_toon_dumps(results))


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
    err = {
        "error": f"operationId not found: {operation_id}",
        "available_count": len(available),
    }
    if suggestions:
        err["did_you_mean"] = suggestions
    err["hint"] = "Run `list` to see operationIds, or use `endpoint METHOD PATH`."
    print(json.dumps(err))
    sys.exit(1)


def main() -> None:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument(
        "--spec",
        default="openapi.json",
        help="Path or URL to OpenAPI JSON spec (default: openapi.json). "
        "URLs (http://, https://) are cached 1h in the system temp dir.",
    )
    pre.add_argument(
        "--refresh",
        action="store_true",
        help="Force re-fetch of URL spec, ignoring the 1h cache",
    )
    pre.add_argument(
        "--raw",
        action="store_true",
        help="Disable compact trimming; emit raw OpenAPI output",
    )
    pre.add_argument(
        "--depth",
        type=int,
        default=DEFAULT_DEPTH,
        help=f"Max $ref resolution depth (default: {DEFAULT_DEPTH})",
    )
    pre_args, remaining = pre.parse_known_args()

    parser = argparse.ArgumentParser(description="Query an OpenAPI spec efficiently")
    sub = parser.add_subparsers(dest="command", required=True)

    sum_p = sub.add_parser(
        "summary", help="Compact API overview: endpoints by tag, schema names"
    )
    sum_p.add_argument(
        "--compact",
        action="store_true",
        help="Ultra-short: paths-only list, no summaries, no schema names",
    )

    list_p = sub.add_parser("list", help="List endpoints as JSON (optional filters)")
    list_p.add_argument("--tag", help="Filter by tag name")
    list_p.add_argument("--method", help="Filter by HTTP method (GET, POST, ...)")

    ep = sub.add_parser("endpoint", help="Full operation detail with resolved schemas")
    ep.add_argument("method", help="HTTP method, e.g. POST")
    ep.add_argument("path", help="API path, e.g. /api/resource/add")

    sc = sub.add_parser("schema", help="Schema definition with resolved $refs")
    sc.add_argument("name", help="Schema name, e.g. ResourceResponse")

    sr = sub.add_parser("search", help="Full-text search across endpoints and schemas")
    sr.add_argument("query", nargs="+", help="Search terms")

    op_p = sub.add_parser(
        "operation", help="Full operation detail looked up by operationId"
    )
    op_p.add_argument(
        "operation_id", help="operationId, e.g. add_resource_api_resource_add_post"
    )

    args = parser.parse_args(remaining)
    args.spec = pre_args.spec
    args.raw = pre_args.raw
    args.depth = pre_args.depth
    args.refresh = pre_args.refresh
    spec = load_spec(args.spec, refresh=args.refresh)

    match args.command:
        case "summary":
            cmd_summary(spec, compact_mode=args.compact)
        case "list":
            cmd_list(spec, tag=args.tag, method=args.method)
        case "endpoint":
            cmd_endpoint(
                spec, args.method, args.path, raw=args.raw, max_depth=args.depth
            )
        case "schema":
            cmd_schema(spec, args.name, raw=args.raw, max_depth=args.depth)
        case "search":
            cmd_search(spec, " ".join(args.query))
        case "operation":
            cmd_operation(spec, args.operation_id, raw=args.raw, max_depth=args.depth)


if __name__ == "__main__":
    main()
