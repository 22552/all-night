"""Model Context Protocol support for Night.

This module implements the stateless MCP 2026-07-28 HTTP core without adding
runtime dependencies. It deliberately lives beside ``night.py`` so Night's
single-file ASGI core remains dependency-free and portable.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import types
import typing as t
from importlib import metadata as importlib_metadata

from night import JSONResponse, Night, Response

MCP_PROTOCOL_VERSION = "2026-07-28"
_HEADER_MISMATCH = -32020
_SERVER_INFO_META_KEY = "io.modelcontextprotocol/serverInfo"
_PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"


def _package_version() -> str:
    try:
        return importlib_metadata.version("all-night")
    except importlib_metadata.PackageNotFoundError:
        return "0.1.1"


def _annotation_schema(annotation: t.Any) -> dict[str, t.Any]:
    if annotation in (inspect.Signature.empty, t.Any):
        return {}

    origin = t.get_origin(annotation)
    args = t.get_args(annotation)

    if origin is t.Annotated:
        return _annotation_schema(args[0]) if args else {}

    if origin in (t.Union, types.UnionType):
        variants = [_annotation_schema(arg) for arg in args]
        return {"anyOf": variants}

    if origin is t.Literal:
        values = list(args)
        schema: dict[str, t.Any] = {"enum": values}
        if values and all(isinstance(value, str) for value in values):
            schema["type"] = "string"
        elif values and all(type(value) is int for value in values):
            schema["type"] = "integer"
        return schema

    if origin in (list, set, frozenset, tuple):
        item = args[0] if args else t.Any
        return {"type": "array", "items": _annotation_schema(item)}

    if origin in (dict, t.Dict):
        value_type = args[1] if len(args) > 1 else t.Any
        return {"type": "object", "additionalProperties": _annotation_schema(value_type)}

    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is type(None):
        return {"type": "null"}
    if annotation in (bytes, bytearray):
        return {"type": "string", "contentEncoding": "base64"}

    if inspect.isclass(annotation) and dataclasses.is_dataclass(annotation):
        properties: dict[str, t.Any] = {}
        required: list[str] = []
        hints = t.get_type_hints(annotation)
        for field in dataclasses.fields(annotation):
            properties[field.name] = _annotation_schema(hints.get(field.name, field.type))
            if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
                required.append(field.name)
        schema = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    return {}


def _input_schema(fn: t.Callable) -> dict[str, t.Any]:
    signature = inspect.signature(fn)
    try:
        hints = t.get_type_hints(fn)
    except Exception:
        hints = {}

    properties: dict[str, t.Any] = {}
    required: list[str] = []
    additional = False
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            additional = True
            continue
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            properties[parameter.name] = {"type": "array"}
            continue
        schema = _annotation_schema(hints.get(parameter.name, parameter.annotation))
        properties[parameter.name] = schema
        if parameter.default is inspect.Parameter.empty:
            required.append(parameter.name)

    out: dict[str, t.Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional,
    }
    if required:
        out["required"] = required
    return out


def _bind_arguments(fn: t.Callable, arguments: dict[str, t.Any]) -> tuple[tuple[t.Any, ...], dict[str, t.Any]]:
    signature = inspect.signature(fn)
    remaining = dict(arguments)
    positional: list[t.Any] = []
    keywords: dict[str, t.Any] = {}
    has_var_kwargs = False

    for parameter in signature.parameters.values():
        name = parameter.name
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            if name in remaining:
                positional.append(remaining.pop(name))
            elif parameter.default is inspect.Parameter.empty:
                raise TypeError(f"Missing required argument: {name}")
        elif parameter.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
            if name in remaining:
                keywords[name] = remaining.pop(name)
        elif parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            if name in remaining:
                values = remaining.pop(name)
                if not isinstance(values, (list, tuple)):
                    raise TypeError(f"{name} must be an array")
                positional.extend(values)
        elif parameter.kind is inspect.Parameter.VAR_KEYWORD:
            has_var_kwargs = True

    if remaining:
        if has_var_kwargs:
            keywords.update(remaining)
        else:
            unknown = next(iter(remaining))
            raise TypeError(f"Unexpected argument: {unknown}")

    bound = signature.bind(*positional, **keywords)
    bound.apply_defaults()
    return bound.args, bound.kwargs


def _jsonrpc_error(request_id: t.Any, code: int, message: str, *, status: int = 200) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status=status,
    )


def _safe_json(value: t.Any) -> t.Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _tool_result(value: t.Any, *, is_error: bool = False) -> dict[str, t.Any]:
    if isinstance(value, Response):
        text = value.body.decode("utf-8", errors="replace")
        return {
            "resultType": "complete",
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
        }

    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")

    safe = _safe_json(value)
    if isinstance(safe, str):
        text = safe
    else:
        text = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))

    result: dict[str, t.Any] = {
        "resultType": "complete",
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }
    if isinstance(safe, dict):
        result["structuredContent"] = safe
    return result


class MCPServer:
    """Expose Night RPC methods as stateless MCP 2026-07-28 tools."""

    def __init__(
        self,
        app: Night,
        *,
        path: str = "/mcp",
        name: str = "night",
        version: str | None = None,
        description: str = "Night MCP server",
        instructions: str | None = None,
        ttl_ms: int = 30_000,
        cache_scope: str = "private",
    ):
        if not path.startswith("/"):
            raise ValueError("MCP path must start with '/'")
        if cache_scope not in {"private", "public"}:
            raise ValueError("cache_scope must be 'private' or 'public'")
        self.app = app
        self.path = path
        self.name = name
        self.version = version or _package_version()
        self.description = description
        self.instructions = instructions
        self.ttl_ms = max(0, int(ttl_ms))
        self.cache_scope = cache_scope
        self._tool_metadata: dict[str, dict[str, t.Any]] = {}
        self._install_route()

    @property
    def server_info(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version, "description": self.description}

    def tool(
        self,
        name: str | None = None,
        *,
        description: str | None = None,
        title: str | None = None,
    ):
        """Register a callable in Night's existing RPC registry and expose it as an MCP tool."""
        def decorator(fn: t.Callable):
            tool_name = name or fn.__name__
            self.app.rpc_methods[tool_name] = fn
            self._tool_metadata[tool_name] = {
                "description": description,
                "title": title,
            }
            return fn
        return decorator

    def _result_meta(self) -> dict[str, t.Any]:
        return {_SERVER_INFO_META_KEY: self.server_info}

    def _complete(self, payload: dict[str, t.Any]) -> dict[str, t.Any]:
        out = dict(payload)
        out.setdefault("resultType", "complete")
        out.setdefault("_meta", self._result_meta())
        return out

    def _tool_definition(self, name: str, fn: t.Callable) -> dict[str, t.Any]:
        metadata = self._tool_metadata.get(name, {})
        description = metadata.get("description") or inspect.getdoc(fn) or f"Call Night RPC method {name}"
        definition: dict[str, t.Any] = {
            "name": name,
            "description": description,
            "inputSchema": _input_schema(fn),
        }
        title = metadata.get("title")
        if title:
            definition["title"] = title
        return definition

    def _validate_headers(self, req, call: dict[str, t.Any]) -> JSONResponse | None:
        request_id = call.get("id")
        method = call.get("method")
        params = call.get("params") if isinstance(call.get("params"), dict) else {}
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        body_version = meta.get(_PROTOCOL_VERSION_META_KEY)
        header_version = req.header("mcp-protocol-version")
        header_method = req.header("mcp-method")

        if header_version != MCP_PROTOCOL_VERSION:
            return _jsonrpc_error(request_id, _HEADER_MISMATCH, "MCP protocol version header mismatch", status=400)
        if body_version != MCP_PROTOCOL_VERSION:
            return _jsonrpc_error(request_id, _HEADER_MISMATCH, "MCP protocol version metadata mismatch", status=400)
        if header_method != method:
            return _jsonrpc_error(request_id, _HEADER_MISMATCH, "Mcp-Method header mismatch", status=400)

        principal_name = params.get("name") if method == "tools/call" else None
        header_name = req.header("mcp-name")
        if principal_name is not None and header_name != str(principal_name):
            return _jsonrpc_error(request_id, _HEADER_MISMATCH, "Mcp-Name header mismatch", status=400)
        if principal_name is None and header_name not in (None, ""):
            return _jsonrpc_error(request_id, _HEADER_MISMATCH, "Unexpected Mcp-Name header", status=400)
        return None

    async def _dispatch(self, req) -> JSONResponse:
        try:
            call = await req.json()
        except Exception:
            return _jsonrpc_error(None, -32700, "Parse error", status=400)

        if not isinstance(call, dict) or call.get("jsonrpc") != "2.0" or not isinstance(call.get("method"), str):
            return _jsonrpc_error(call.get("id") if isinstance(call, dict) else None, -32600, "Invalid Request", status=400)

        mismatch = self._validate_headers(req, call)
        if mismatch is not None:
            return mismatch

        request_id = call.get("id")
        method = call["method"]
        params = call.get("params") if isinstance(call.get("params"), dict) else {}

        if method == "server/discover":
            result = self._complete(
                {
                    "supportedVersions": [MCP_PROTOCOL_VERSION],
                    "capabilities": {"tools": {"listChanged": False}},
                    "ttlMs": self.ttl_ms,
                    "cacheScope": self.cache_scope,
                }
            )
            if self.instructions:
                result["instructions"] = self.instructions
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})

        if method == "tools/list":
            tools = [self._tool_definition(name, fn) for name, fn in self.app.rpc_methods.items()]
            result = self._complete(
                {
                    "tools": tools,
                    "ttlMs": self.ttl_ms,
                    "cacheScope": self.cache_scope,
                }
            )
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})

        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str):
                return _jsonrpc_error(request_id, -32602, "Tool name is required")
            if not isinstance(arguments, dict):
                return _jsonrpc_error(request_id, -32602, "Tool arguments must be an object")
            fn = self.app.rpc_methods.get(name)
            if fn is None:
                return _jsonrpc_error(request_id, -32601, f"Unknown tool: {name}")
            try:
                args, kwargs = _bind_arguments(fn, arguments)
            except TypeError as exc:
                return _jsonrpc_error(request_id, -32602, str(exc))
            try:
                value = fn(*args, **kwargs)
                if inspect.isawaitable(value):
                    value = await t.cast(t.Awaitable[t.Any], value)
                result = self._complete(_tool_result(value))
            except Exception as exc:
                result = self._complete(_tool_result(str(exc), is_error=True))
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})

        return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")

    def _install_route(self) -> None:
        @self.app.post(self.path, name="mcp")
        async def _mcp(req):
            return await self._dispatch(req)


def enable_mcp(app: Night, **kwargs: t.Any) -> MCPServer:
    """Create and register a stateless MCP server on a Night application."""
    return MCPServer(app, **kwargs)


__all__ = ["MCP_PROTOCOL_VERSION", "MCPServer", "enable_mcp"]
