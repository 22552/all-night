#!/usr/bin/env python3
"""night.py - Night's dependency-free Python web framework core.

Night is centered on a runtime-independent Request -> Response core. Normal
CPython is the primary implementation environment; adapters can expose the same
application through ASGI, WSGI, Cloudflare Python Workers, Browser/Pyodide,
Node/Pyodide, Netlify, and other platform-native request/response interfaces.

Design goals
- Keep the dependency-free core in one importable ``night.py`` file.
- Provide Flask-like routing ergonomics without making ASGI or WSGI the core abstraction.
- Keep routing and request dispatch fast with indexed static/dynamic paths and specialized invokers.
- Include practical core features such as request/response helpers, templates, files, sessions,
  middleware/hooks, RPC/SSE/WebSocket helpers, and extension points.
- Keep platform integration at adapter boundaries so the core stays portable.

Optional features may use optional dependencies; the normal CPython core has no
required third-party runtime dependency.
"""

from __future__ import annotations

import ast
import asyncio
import html as _html
import contextvars
import dataclasses
import datetime as _dt
import email.utils
import gzip
import hashlib
import hmac
import inspect
import importlib.util
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
import traceback
import time
import typing as t
import urllib.parse
from email import policy
from email.parser import BytesParser
import argparse
import runpy
import base64
import secrets
import types
import contextlib
import sqlite3

# ----------------------------
# Utilities
# ----------------------------

_T = t.TypeVar("_T")
MAX_BODY_SIZE = 16 * 1024 * 1024
MAX_SESSION_COOKIE_SIZE = 3800


class LuaUnavailable(RuntimeError):
    """Raised when Lua macros are used without the optional lupa package."""


def _lua_macro_endpoint(source: str) -> t.Callable:
    """Build an endpoint for trusted Lua application code.

    The script must return a string, number, or a table containing ``body``,
    ``status``, and optional ``headers``.  Lua macros are deliberately
    optional: applications that do not use them keep zero dependencies.
    """
    try:
        from lupa import LuaRuntime
    except ImportError as exc:
        raise LuaUnavailable("Lua macros require the optional 'lupa' package") from exc

    def make_runtime():
        # Python bridges are disabled. This is not a security sandbox for
        # untrusted user-supplied Lua; use a separate process/container for that.
        runtime = LuaRuntime(
            unpack_returned_tuples=True,
            register_eval=False,
            register_builtins=False,
            max_memory=8 * 1024 * 1024,
        )
        runtime.execute("os=nil; io=nil; debug=nil; package=nil; require=nil; dofile=nil; loadfile=nil")
        return runtime

    async def endpoint(req: Request, **params):
        lua = make_runtime()
        fn = lua.execute("local f = function(req) " + source + " end; return f")
        data = {
            "method": req.method,
            "path": req.path,
            "query": req.query,
            "headers": req.headers,
            "cookies": req.cookies,
            "params": params,
        }
        result = fn(lua.table_from(data, recursive=True))
        if isinstance(result, str):
            return PlainTextResponse(result)
        if isinstance(result, (int, float)):
            return PlainTextResponse(str(result))
        if result is None:
            return Response(b"", status=204)
        body = result["body"]
        status = int(result["status"] or 200)
        headers = dict(result["headers"] or {})
        return Response(_to_bytes(str(body)), status=status, headers=headers)

    return endpoint


def _to_bytes(x: t.Union[str, bytes, bytearray]) -> bytes:
    if isinstance(x, (bytes, bytearray)):
        return bytes(x)
    return x.encode("utf-8")


def _guess_content_type(path: str, default: str = "application/octet-stream") -> str:
    ctype, _ = mimetypes.guess_type(path)
    return ctype or default


def _http_date(dt: _dt.datetime | None = None) -> str:
    if dt is None:
        dt = _dt.datetime.now(tz=_dt.timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return email.utils.format_datetime(dt, usegmt=True)

_HTTP_DATE_CACHE_SECOND = -1
_HTTP_DATE_CACHE_VALUE = ""

def _cached_http_date() -> str:
    global _HTTP_DATE_CACHE_SECOND, _HTTP_DATE_CACHE_VALUE
    second = int(time.time())
    if second != _HTTP_DATE_CACHE_SECOND:
        _HTTP_DATE_CACHE_SECOND = second
        _HTTP_DATE_CACHE_VALUE = email.utils.formatdate(second, usegmt=True)
    return _HTTP_DATE_CACHE_VALUE


def _parse_http_date(s: str) -> _dt.datetime | None:
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt
    except Exception:
        return None


def _parse_query(qs: bytes) -> dict[str, t.Union[str, list[str]]]:
    # Keep a Flask-ish shape: key -> str or list[str]
    if not qs:
        return {}
    parsed = urllib.parse.parse_qs(qs.decode("latin-1"), keep_blank_values=True)
    out: dict[str, t.Union[str, list[str]]] = {}
    for k, vals in parsed.items():
        if len(vals) == 1:
            out[k] = vals[0]
        else:
            out[k] = vals
    return out


def _parse_cookies(cookie_header: str | None) -> dict[str, str]:
    """Parse Cookie header into a dict.

    This is intentionally small (not a full RFC6265 implementation) but it:
    - strips whitespace
    - ignores empty keys
    - unquotes simple quoted values
    - percent-decodes values (common in practice)

    Note: if a cookie name appears multiple times, the last one wins.
    """

    if not cookie_header:
        return {}

    cookies: dict[str, str] = {}

    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue

        # Unquote "..." values.
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            v = v[1:-1]

        # Percent-decoding is common for cookie values.
        try:
            v = urllib.parse.unquote(v)
        except Exception:
            pass

        cookies[k] = v

    return cookies


def _safe_join(root: str, path: str) -> str:
    # Prevent path traversal; returns a normalized absolute path under root.
    root_abs = os.path.abspath(root)
    target = os.path.abspath(os.path.join(root_abs, path.lstrip("/")))
    if os.path.commonpath([root_abs, target]) != root_abs:
        raise HTTPError(403, "Forbidden")
    return target


# ----------------------------
# Exceptions
# ----------------------------


class HTTPError(Exception):
    def __init__(self, status: int, detail: str = ""):
        self.status = int(status)
        self.detail = detail
        super().__init__(f"HTTP {status}: {detail}")


class NotFound(HTTPError):
    def __init__(self, detail: str = "Not Found"):
        super().__init__(404, detail)


class MethodNotAllowed(HTTPError):
    def __init__(self, allowed: t.Iterable[str] = (), detail: str = "Method Not Allowed"):
        self.allowed = sorted(set(allowed))
        super().__init__(405, detail)


class ORMError(RuntimeError):
    """Raised for invalid Night ORM model definitions or operations."""


class Database:
    """A small synchronous SQLite ORM for simple Night applications.

    Models are registered with ``@db.model`` and use normal type annotations.
    The ORM intentionally supports a compact SQLite subset only.
    """

    _sqlite_types = {int: "INTEGER", float: "REAL", str: "TEXT", bytes: "BLOB", bool: "INTEGER"}

    def __init__(self, path: str = ":memory:"):
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._models: set[type] = set()

    def close(self) -> None:
        self.connection.close()

    @staticmethod
    def _name(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ORMError(f"Invalid SQL identifier: {value!r}")
        return value

    def model(self, cls: type | None = None, *, table: str | None = None):
        def register(model: type) -> type:
            if not dataclasses.is_dataclass(model):
                model = dataclasses.dataclass(model)
            model.__night_table__ = self._name(table or model.__name__.lower() + "s")
            model.__night_db__ = self
            self._models.add(model)

            model.create = classmethod(lambda kind, **values: self.create(kind, **values))
            model.get = classmethod(lambda kind, ident: self.get(kind, ident))
            model.all = classmethod(lambda kind: self.all(kind))
            model.filter = classmethod(lambda kind, **where: self.filter(kind, **where))
            model.save = lambda item: self.save(item)
            model.delete = lambda item: self.delete(item)
            return model
        return register if cls is None else register(cls)

    def _fields(self, model: type) -> list[dataclasses.Field]:
        if model not in self._models:
            raise ORMError(f"{model.__name__} is not registered; use @db.model")
        return list(dataclasses.fields(model))

    def create_all(self, *models: type) -> None:
        for model in models or tuple(self._models):
            fields = self._fields(model)
            hints = t.get_type_hints(model)
            columns = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
            for field in fields:
                if field.name == "id":
                    continue
                typ = hints.get(field.name, field.type)
                origin, args = t.get_origin(typ), t.get_args(typ)
                if origin in (t.Union, types.UnionType) and type(None) in args:
                    typ = next(item for item in args if item is not type(None))
                sql_type = self._sqlite_types.get(typ)
                if sql_type is None:
                    raise ORMError(f"Unsupported SQLite field type: {field.name}: {typ}")
                columns.append(f'"{self._name(field.name)}" {sql_type}')
            self.connection.execute(f'CREATE TABLE IF NOT EXISTS "{model.__night_table__}" ({", ".join(columns)})')
        self.connection.commit()

    def _from_row(self, model: type, row: sqlite3.Row):
        values = {field.name: row[field.name] for field in self._fields(model) if field.name in row.keys()}
        item = model(**{key: value for key, value in values.items() if key != "id"})
        setattr(item, "id", row["id"])
        return item

    def create(self, model: type, **values: t.Any):
        fields = [field for field in self._fields(model) if field.name != "id"]
        unknown = set(values) - {field.name for field in fields}
        if unknown:
            raise ORMError(f"Unknown model fields: {', '.join(sorted(unknown))}")
        item = model(**values)
        self.save(item)
        return item

    def save(self, item: t.Any) -> None:
        model = type(item)
        fields = [field for field in self._fields(model) if field.name != "id"]
        names = [self._name(field.name) for field in fields]
        values = [getattr(item, field.name) for field in fields]
        ident = getattr(item, "id", None)
        if ident is None:
            placeholders = ", ".join("?" for _ in names)
            columns = ", ".join(f'"{name}"' for name in names)
            cursor = self.connection.execute(f'INSERT INTO "{model.__night_table__}" ({columns}) VALUES ({placeholders})', values)
            setattr(item, "id", cursor.lastrowid)
        else:
            assignments = ", ".join(f'"{name}" = ?' for name in names)
            self.connection.execute(f'UPDATE "{model.__night_table__}" SET {assignments} WHERE id = ?', [*values, ident])
        self.connection.commit()

    def get(self, model: type, ident: int):
        row = self.connection.execute(f'SELECT * FROM "{model.__night_table__}" WHERE id = ?', (ident,)).fetchone()
        return self._from_row(model, row) if row is not None else None

    def all(self, model: type) -> list[t.Any]:
        rows = self.connection.execute(f'SELECT * FROM "{model.__night_table__}" ORDER BY id').fetchall()
        return [self._from_row(model, row) for row in rows]

    def filter(self, model: type, **where: t.Any) -> list[t.Any]:
        valid = {field.name for field in self._fields(model)} | {"id"}
        if not where:
            return self.all(model)
        if set(where) - valid:
            raise ORMError("Unknown filter field")
        clause = " AND ".join(f'"{self._name(name)}" = ?' for name in where)
        rows = self.connection.execute(f'SELECT * FROM "{model.__night_table__}" WHERE {clause} ORDER BY id', tuple(where.values())).fetchall()
        return [self._from_row(model, row) for row in rows]

    def delete(self, item: t.Any) -> None:
        ident = getattr(item, "id", None)
        if ident is None:
            return
        self.connection.execute(f'DELETE FROM "{type(item).__night_table__}" WHERE id = ?', (ident,))
        self.connection.commit()

    @contextlib.contextmanager
    def transaction(self):
        try:
            yield self
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()


class ValidationError(HTTPError):
    def __init__(self, errors: list[dict[str, str]], detail: str = "Invalid request body"):
        self.errors = errors
        super().__init__(422, detail)


def _validate_value(value: t.Any, typ: t.Any, field: str, errors: list[dict[str, str]]) -> t.Any:
    origin, args = t.get_origin(typ), t.get_args(typ)
    if origin in (t.Union, types.UnionType) and type(None) in args:
        if value is None:
            return None
        typ = next((item for item in args if item is not type(None)), t.Any)
        origin, args = t.get_origin(typ), t.get_args(typ)
    if origin is list:
        if not isinstance(value, list):
            errors.append({"field": field, "message": "Expected a list"})
            return value
        item_type = args[0] if args else t.Any
        return [_validate_value(item, item_type, f"{field}[{index}]", errors) for index, item in enumerate(value)]
    if dataclasses.is_dataclass(typ):
        return _validate_dataclass(typ, value, errors, field)
    try:
        if typ is bool and not isinstance(value, bool):
            raise ValueError
        if typ is int and isinstance(value, bool):
            raise ValueError
        if typ in (int, float, str, bool) and not isinstance(value, typ):
            value = typ(value)
    except (TypeError, ValueError):
        errors.append({"field": field, "message": f"Expected {getattr(typ, '__name__', str(typ))}"})
    return value


def _validate_dataclass(model: type, value: t.Any, errors: list[dict[str, str]] | None = None, prefix: str = "") -> t.Any:
    errors = errors if errors is not None else []
    error_count = len(errors)
    if not dataclasses.is_dataclass(model) or not isinstance(value, dict):
        errors.append({"field": prefix or "body", "message": "Expected an object"})
        if prefix:
            return value
        raise ValidationError(errors)
    hints = t.get_type_hints(model)
    result: dict[str, t.Any] = {}
    for field in dataclasses.fields(model):
        name = f"{prefix}.{field.name}" if prefix else field.name
        if field.name not in value:
            if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING:
                continue
            errors.append({"field": name, "message": "Field is required"})
            continue
        result[field.name] = _validate_value(value[field.name], hints.get(field.name, field.type), name, errors)
    if not prefix and errors:
        raise ValidationError(errors)
    if prefix and len(errors) > error_count:
        return value
    return model(**result)


def _dataclass_schema(model: type) -> dict[str, t.Any]:
    primitive = {str: "string", int: "integer", float: "number", bool: "boolean"}
    if not dataclasses.is_dataclass(model):
        return {"type": "object"}
    properties, required = {}, []
    for field in dataclasses.fields(model):
        typ = t.get_type_hints(model).get(field.name, field.type)
        origin, args = t.get_origin(typ), t.get_args(typ)
        nullable = origin in (t.Union, types.UnionType) and type(None) in args
        if nullable: typ = next(item for item in args if item is not type(None))
        if t.get_origin(typ) is list:
            schema = {"type": "array", "items": _dataclass_schema(t.get_args(typ)[0])}
        elif dataclasses.is_dataclass(typ):
            schema = _dataclass_schema(typ)
        else:
            schema = {"type": primitive.get(typ, "object")}
        if nullable: schema["type"] = [schema.get("type", "object"), "null"]
        properties[field.name] = schema
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
            required.append(field.name)
    out = {"type": "object", "properties": properties}
    if required: out["required"] = required
    return out


def csrf_token() -> str:
    value = session().get("_csrf_token")
    if not isinstance(value, str) or not value:
        value = secrets.token_urlsafe(32)
        session()["_csrf_token"] = value
    return value


async def csrf_protect(req: Request | None = None) -> None:
    req = req or request()
    if req.method not in {"POST", "PUT", "PATCH", "DELETE", "QUERY"}:
        return
    supplied = req.header("x-csrf-token")
    if not supplied and (req.header("content-type") or "").split(";", 1)[0].lower() in {
        "application/x-www-form-urlencoded", "multipart/form-data"
    }:
        supplied = (await req.form()).get("csrf_token")
    expected = session().get("_csrf_token")
    if not isinstance(supplied, str) or not isinstance(expected, str) or not hmac.compare_digest(supplied, expected):
        raise HTTPError(403, "CSRF validation failed")


def csrf_middleware() -> Middleware:
    async def middleware(req: Request, call_next: t.Callable[[], t.Awaitable[Response]]) -> Response:
        await csrf_protect(req)
        return await call_next()
    return middleware


# ----------------------------
# Request / Response
# ----------------------------


@dataclasses.dataclass(slots=True)
class Request:
    scope: dict
    receive: t.Callable
    send: t.Callable
    app: t.Any = None

    _body: bytes | None = None
    _json: t.Any = dataclasses.field(default=None, init=False)
    _json_loaded: bool = dataclasses.field(default=False, init=False)
    _query: dict[str, t.Union[str, list[str]]] | None = dataclasses.field(default=None, init=False)
    _cookies: dict[str, str] | None = dataclasses.field(default=None, init=False)
    path_params: dict[str, t.Any] = dataclasses.field(default_factory=dict)
    max_body_size: int = MAX_BODY_SIZE
    _headers: dict[str, str] | None = dataclasses.field(default=None, init=False)
    _header_cache: dict[str, str | None] = dataclasses.field(default_factory=dict, init=False)

    @property
    def method(self) -> str:
        return (self.scope.get("method") or "GET").upper()

    @property
    def path(self) -> str:
        return self.scope.get("path") or "/"

    @property
    def query_string(self) -> bytes:
        return self.scope.get("query_string") or b""

    @property
    def query(self) -> dict[str, t.Union[str, list[str]]]:
        if self._query is None:
            self._query = _parse_query(self.query_string)
        return self._query

    @property
    def headers(self) -> dict[str, str]:
        if self._headers is not None:
            return self._headers
        # ASGI provides list[(bytes, bytes)]
        hs = {}
        for k, v in self.scope.get("headers") or []:
            hs[k.decode("latin-1").lower()] = v.decode("latin-1")
        self._headers = hs
        return hs

    def header(self, name: str, default: str | None = None) -> str | None:
        key = name.lower()
        if self._headers is not None:
            return self._headers.get(key, default)
        if key in self._header_cache:
            value = self._header_cache[key]
            return default if value is None else value

        target = key.encode("latin-1")
        value = None
        headers = self.scope.get("headers") or ()
        # Search from the end to preserve the previous "last value wins"
        # behavior without decoding unrelated headers. ASGI headers are a list.
        for raw_name, raw_value in reversed(headers):
            if raw_name == target or raw_name.lower() == target:
                value = raw_value.decode("latin-1")
                break
        self._header_cache[key] = value
        return default if value is None else value

    @property
    def trace_id(self) -> str:
        value = (self.header("traceparent") or "").split("-")
        return value[1] if len(value) == 4 and len(value[1]) == 32 else self.scope.setdefault("trace_id", os.urandom(16).hex())

    @property
    def span_id(self) -> str:
        value = (self.header("traceparent") or "").split("-")
        return value[2] if len(value) == 4 and len(value[2]) == 16 else self.scope.setdefault("span_id", os.urandom(8).hex())

    def trace_headers(self) -> dict[str, str]:
        return {"traceparent": f"00-{self.trace_id}-{self.span_id}-01"}

    @property
    def cookies(self) -> dict[str, str]:
        if self._cookies is None:
            self._cookies = _parse_cookies(self.header("cookie"))
        return self._cookies

    @property
    def client(self) -> tuple[str, int] | None:
        c = self.scope.get("client")
        if not c:
            return None
        try:
            host, port = c
            return str(host), int(port)
        except Exception:
            return None

    @property
    def info(self):
        from night_request_info import from_scope
        return from_scope(self.scope)

    @property
    def client_ip(self) -> str | None:
        return self.info.client_ip

    @property
    def user_agent(self) -> str | None:
        return self.info.user_agent

    @property
    def country(self) -> str | None:
        return self.info.country

    @property
    def request_id(self) -> str | None:
        return self.info.request_id

    @property
    def platform(self) -> str | None:
        return self.info.platform

    @property
    def scheme(self) -> str:
        return self.scope.get("scheme") or "http"

    @property
    def host(self) -> str | None:
        # Prefer Host header
        h = self.header("host")
        if h:
            return h
        c = self.client
        if c:
            return c[0]
        return None

    @property
    def url(self) -> str:
        host = self.host or ""
        qs = self.query_string.decode("latin-1") if self.query_string else ""
        base = f"{self.scheme}://{host}{self.path}" if host else self.path
        return base + ("?" + qs if qs else "")

    @property
    def state(self) -> dict:
        self.scope.setdefault("state", {})
        st = self.scope["state"]
        if not isinstance(st, dict):
            # Keep it simple: enforce dict.
            self.scope["state"] = {}
        return self.scope["state"]

    async def body(self) -> bytes:
        if self._body is not None:
            return self._body
        body = bytearray()
        content_length = self.header("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_body_size:
            raise HTTPError(413, "Request body too large")
        more = True
        while more:
            event = await self.receive()
            if event["type"] != "http.request":
                continue
            body += event.get("body", b"")
            if len(body) > self.max_body_size:
                raise HTTPError(413, "Request body too large")
            more = event.get("more_body", False)
        self._body = bytes(body)
        return self._body

    async def text(self, encoding: str = "utf-8") -> str:
        return (await self.body()).decode(encoding, errors="replace")

    async def json(self) -> t.Any:
        if self._json_loaded:
            return self._json
        b = await self.body()
        if not b:
            self._json = None
        else:
            self._json = json.loads(b.decode("utf-8"))
        self._json_loaded = True
        return self._json

    async def form(self) -> "QueryDict":
        if "_form" in self.scope:
            return self.scope["_form"]
        body = await self.body()
        ctype = (self.header("content-type") or "").split(";", 1)[0].strip().lower()
        if ctype == "application/x-www-form-urlencoded":
            result = QueryDict(urllib.parse.parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True))
            self.scope["_form"] = result
            return result
        if ctype == "multipart/form-data":
            form, files = self._parse_multipart(body)
            self.scope["_files"] = files
            self.scope["_form"] = form
            return form
        self.scope["_form"] = QueryDict()
        return self.scope["_form"]

    async def files(self) -> dict[str, UploadFile]:
        await self.form()
        return self.scope.get("_files", {})

    def _parse_multipart(self, body: bytes) -> tuple[QueryDict, dict[str, UploadFile]]:
        content_type = self.header("content-type") or ""
        message = BytesParser(policy=policy.default).parsebytes(
            (f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n").encode() + body
        )
        fields: dict[str, list[str]] = {}
        files: dict[str, UploadFile] = {}
        for part in message.iter_parts():
            disposition = part.get_content_disposition()
            name = part.get_param("name", header="content-disposition")
            if disposition != "form-data" or not name:
                continue
            data = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if filename:
                if len(data) > self.max_body_size:
                    raise HTTPError(413, "Uploaded file too large")
                files[name] = UploadFile(filename, part.get_content_type(), data)
            else:
                fields.setdefault(name, []).append(data.decode(part.get_content_charset() or "utf-8", errors="replace"))
        return QueryDict(fields), files


def session() -> dict[str, t.Any]:
    req = request()
    secret = req.scope.get("session_secret")
    if not secret:
        raise RuntimeError("Session requires secret_key")
    if "_session" not in req.scope:
        raw = req.cookies.get("night_session")
        data = {}
        if raw and secret and "." in raw:
            encoded, signature = raw.rsplit(".", 1)
            expected = hmac.new(secret, encoded.encode(), hashlib.sha256).hexdigest()
            if hmac.compare_digest(signature, expected):
                try:
                    data = json.loads(base64.urlsafe_b64decode(encoded + "=="))
                except Exception:
                    data = {}
        req.scope["_session"] = data if isinstance(data, dict) else {}
        req.scope["_session_original"] = json.dumps(req.scope["_session"], sort_keys=True)
    return req.scope["_session"]


def flash(message: str, category: str = "message"):
    session().setdefault("_flashes", []).append([category, message])


def get_flashed_messages(*, with_categories: bool = False) -> list[t.Any]:
    values = session().pop("_flashes", [])
    return values if with_categories else [message for _, message in values]


def session_clear():
    req = request()
    req.scope["_session"] = {}
    req.scope["_session_regenerated"] = True


def session_regenerate():
    data = dict(session())
    data.pop("_nonce", None)
    data["_nonce"] = os.urandom(16).hex()
    request().scope["_session"] = data
    request().scope["_session_regenerated"] = True


class QueryDict(dict[str, list[str]]):
    """Django-like multi-value query/form mapping."""

    def __init__(self, values: t.Mapping[str, t.Any] | None = None):
        super().__init__({k: list(v) if isinstance(v, list) else [str(v)] for k, v in (values or {}).items()})

    def get(self, key: str, default: t.Any = None):
        values = super().get(key)
        return values[-1] if values else default

    def getlist(self, key: str) -> list[str]:
        return list(super().get(key, []))


@dataclasses.dataclass
class UploadFile:
    filename: str
    content_type: str | None
    data: t.Any

    def __post_init__(self):
        if isinstance(self.data, bytes):
            spool = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
            spool.write(self.data)
            spool.seek(0)
            self.data = spool

    async def read(self) -> bytes:
        self.data.seek(0)
        return self.data.read()

    def save(self, path: str):
        self.data.seek(0)
        with open(path, "wb") as f:
            f.write(self.data.read())


class CSSRegistry:
    def __init__(self):
        self.rules: list[dict[str, t.Any]] = []
        self.variables: dict[str, t.Any] = {}
        self.keyframes: dict[str, dict[str, dict[str, t.Any]]] = {}

    def add(self, rules: dict[str, t.Any]):
        self.rules.append(rules)

    def add_variables(self, variables: dict[str, t.Any]):
        self.variables.update(variables)

    def add_keyframes(self, name: str, frames: dict[str, dict[str, t.Any]]):
        self.keyframes[name] = frames

    def _decl(self, key: str, value: t.Any, minify: bool) -> str:
        prop = re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), key)
        return f"{prop}:{value}" if minify else f"  {prop}: {value};"

    def _render_rules(self, selector: str, values: dict[str, t.Any], parent: str | None, minify: bool) -> list[str]:
        current = selector if not parent else ", ".join(
            s.replace("&", p) if "&" in s else f"{p} {s}" for p in parent.split(", ") for s in selector.split(", ")
        )
        declarations, nested = [], []
        for key, value in values.items():
            if isinstance(value, dict): nested.append((key, value))
            else: declarations.append(self._decl(key, value, minify))
        out = []
        if declarations:
            if minify: out.append(current + "{" + ";".join(x.removesuffix(";") for x in declarations) + "}")
            else: out.append(current + " {\n" + "\n".join(declarations) + "\n}")
        for child, child_values in nested:
            if child.startswith("@"):
                inner = []
                for nested_selector, nested_values in child_values.items():
                    inner.extend(self._render_rules(nested_selector, nested_values, None, minify))
                out.append(child + ("{" if minify else " {\n") + ("".join(inner) if minify else "\n".join(inner)) + ("}" if minify else "\n}"))
            else:
                out.extend(self._render_rules(child, child_values, current, minify))
        return out

    def render(self, *, minify: bool = False) -> str:
        chunks = []
        if self.variables:
            values = {f"--{k.lstrip('-')}": v for k, v in self.variables.items()}
            chunks.extend(self._render_rules(":root", values, None, minify))
        for rules in self.rules:
            for selector, values in rules.items():
                if selector.startswith("@media"):
                    inner = []
                    for child, child_values in values.items(): inner.extend(self._render_rules(child, child_values, None, minify))
                    chunks.append(selector + ("{" if minify else " {\n") + ("".join(inner) if minify else "\n".join(inner)) + ("}" if minify else "\n}"))
                else: chunks.extend(self._render_rules(selector, values, None, minify))
        for name, frames in self.keyframes.items():
            body = []
            for step, values in frames.items(): body.extend(self._render_rules(step, values, None, minify))
            chunks.append("@keyframes " + name + ("{" if minify else " {\n") + ("".join(body) if minify else "\n".join(body)) + ("}" if minify else "\n}"))
        return ("" if minify else "\n\n").join(chunks) + ("" if minify else "\n")


class WebSocket:
    def __init__(self, scope: dict, receive, send):
        self.scope = scope
        self.receive = receive
        self.send = send
        self._connect_received = False
        self._accepted = False

    @property
    def path(self) -> str:
        return self.scope.get("path") or "/"

    async def accept(self, subprotocol: str | None = None):
        if not self._connect_received:
            event = await self.receive()
            event_type = event.get("type")
            if event_type == "websocket.disconnect":
                raise ConnectionError("WebSocket disconnected before accept")
            if event_type != "websocket.connect":
                raise RuntimeError(f"Expected websocket.connect before accept, got {event_type!r}")
            self._connect_received = True

        event = {"type": "websocket.accept"}
        if subprotocol:
            event["subprotocol"] = subprotocol
        await self.send(event)
        self._accepted = True

    async def receive_text(self) -> str:
        event = await self.receive()
        if event["type"] == "websocket.disconnect":
            raise ConnectionError("WebSocket disconnected")
        if event.get("text") is not None:
            return event["text"]
        return (event.get("bytes") or b"").decode("utf-8", errors="replace")

    async def send_text(self, data: str):
        await self.send({"type": "websocket.send", "text": str(data)})

    async def send_bytes(self, data: bytes):
        await self.send({"type": "websocket.send", "bytes": bytes(data)})

    async def receive_json(self) -> t.Any:
        return json.loads(await self.receive_text())

    async def send_json(self, data: t.Any):
        await self.send_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))

    async def close(self, code: int = 1000, reason: str = ""):
        event = {"type": "websocket.close", "code": int(code)}
        if reason:
            event["reason"] = reason
        await self.send(event)


class Response:
    def __init__(
        self,
        body: t.Union[str, bytes, bytearray] = b"",
        status: int = 200,
        headers: t.Mapping[str, str] | None = None,
        content_type: str | None = None,
        raw_headers: t.Iterable[tuple[str, str]] | None = None,
    ):
        self.status = int(status)
        self.body = _to_bytes(body)
        self.headers = {k.lower(): v for k, v in headers.items()} if headers else {}
        self.raw_headers = list(raw_headers) if raw_headers else []
        if content_type is not None:
            self.headers["content-type"] = content_type
        if "date" not in self.headers:
            self.headers["date"] = _cached_http_date()
        if "content-length" not in self.headers:
            self.headers["content-length"] = str(len(self.body))

    def asgi_headers(self) -> list[tuple[bytes, bytes]]:
        encoded = [
            (k.encode("latin-1"), v.encode("latin-1"))
            for k, v in self.headers.items()
            if k != "set-cookie"
        ]
        if self.raw_headers:
            encoded.extend(
                (k.encode("latin-1"), v.encode("latin-1"))
                for k, v in self.raw_headers
            )
        return encoded

    def add_header(self, name: str, value: str):
        self.raw_headers.append((name.lower(), value))

    def set_cookie(self, key: str, value: str = "", *, max_age: int | None = None,
                   expires: str | None = None, path: str = "/", domain: str | None = None,
                   secure: bool = False, httponly: bool = False,
                   samesite: str | None = None):
        parts = [f"{key}={urllib.parse.quote(str(value), safe='')}"]
        if max_age is not None: parts.append(f"Max-Age={int(max_age)}")
        if expires is not None: parts.append(f"Expires={expires}")
        if path: parts.append(f"Path={path}")
        if domain: parts.append(f"Domain={domain}")
        if secure: parts.append("Secure")
        if httponly: parts.append("HttpOnly")
        if samesite: parts.append(f"SameSite={samesite}")
        self.add_header("set-cookie", "; ".join(parts))

    def delete_cookie(self, key: str, *, path: str = "/", domain: str | None = None):
        self.set_cookie(key, "", max_age=0, expires="Thu, 01 Jan 1970 00:00:00 GMT", path=path, domain=domain)

    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": self.status, "headers": self.asgi_headers()})
        await send({"type": "http.response.body", "body": self.body, "more_body": False})


class TestResponse:
    def __init__(self, status_code: int, headers: dict[str, str], body: bytes):
        self.status_code, self.headers, self.data = status_code, headers, body

    def get_json(self):
        return json.loads(self.data.decode("utf-8"))

    @property
    def text(self):
        return self.data.decode("utf-8", errors="replace")


class TestClient:
    def __init__(self, app: "Night"):
        self.app, self.cookies = app, {}
        self._runner: asyncio.Runner | None = None

    def _run(self, coro):
        if self._runner is None:
            self._runner = asyncio.Runner()
        return self._runner.run(coro)

    def close(self):
        runner, self._runner = self._runner, None
        if runner is not None:
            runner.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def request(self, method: str, path: str, *, data: bytes | str | None = None, headers: dict[str, str] | None = None):
        async def run():
            sent = []
            body = data.encode() if isinstance(data, str) else (data or b"")
            parsed = urllib.parse.urlsplit(path)
            hs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
            if self.cookies:
                hs.append((b"cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()).encode()))
            if body and not any(k == b"content-length" for k, _ in hs): hs.append((b"content-length", str(len(body)).encode()))
            events = [{"type": "http.request", "body": body, "more_body": False}]
            async def receive(): return events.pop(0) if events else {"type": "http.disconnect"}
            async def send(event): sent.append(event)
            scope = {"type": "http", "method": method.upper(), "path": parsed.path or "/", "query_string": parsed.query.encode(), "headers": hs}
            await self.app(scope, receive, send)
            start = next(e for e in sent if e["type"] == "http.response.start")
            for key, value in start["headers"]:
                if key.lower() == b"set-cookie":
                    pair = value.decode().split(";", 1)[0]
                    name, _, cookie_value = pair.partition("=")
                    if name: self.cookies[name] = cookie_value
            chunks = [e.get("body", b"") for e in sent if e["type"] == "http.response.body"]
            return TestResponse(start["status"], {k.decode(): v.decode() for k, v in start["headers"]}, b"".join(chunks))
        return self._run(run())

    def get(self, path, **kwargs): return self.request("GET", path, **kwargs)
    def post(self, path, **kwargs): return self.request("POST", path, **kwargs)
    def query(self, path, **kwargs): return self.request("QUERY", path, **kwargs)


class StreamingResponse(Response):
    """Send an async iterator/generator as chunked body.

    Note: Many servers will handle this fine. We do not set Content-Length.
    """

    def __init__(
        self,
        body_iter: t.AsyncIterable[t.Union[str, bytes, bytearray]] | t.Iterable[t.Union[str, bytes, bytearray]],
        status: int = 200,
        headers: t.Mapping[str, str] | None = None,
        content_type: str | None = "application/octet-stream",
    ):
        self.status = int(status)
        self._body_iter = body_iter
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        if content_type is not None:
            self.headers.setdefault("content-type", content_type)
        if "date" not in self.headers:
            self.headers["date"] = _cached_http_date()
        # Intentionally omit content-length
        self.body = b""  # compatibility

    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": self.status, "headers": self.asgi_headers()})

        it = self._body_iter
        if hasattr(it, "__aiter__"):
            async for chunk in t.cast(t.AsyncIterable, it):
                await send({"type": "http.response.body", "body": _to_bytes(chunk), "more_body": True})
        else:
            for chunk in t.cast(t.Iterable, it):
                await send({"type": "http.response.body", "body": _to_bytes(chunk), "more_body": True})

        await send({"type": "http.response.body", "body": b"", "more_body": False})


def sse(
    body_iter: t.AsyncIterable[t.Any] | t.Iterable[t.Any],
    *,
    status: int = 200,
    headers: t.Mapping[str, str] | None = None,
) -> StreamingResponse:
    """Create a Server-Sent Events response.

    Items may be strings or dictionaries with ``data``, ``event``, ``id``,
    and ``retry`` keys.  A blank line terminates each event.
    """
    async def encode_async():
        async for item in t.cast(t.AsyncIterable, body_iter):
            yield _format_sse(item)

    def encode_sync():
        for item in t.cast(t.Iterable, body_iter):
            yield _format_sse(item)

    source = encode_async() if hasattr(body_iter, "__aiter__") else encode_sync()
    h = dict(headers or {})
    h.setdefault("cache-control", "no-cache")
    h.setdefault("connection", "keep-alive")
    return StreamingResponse(source, status=status, headers=h, content_type="text/event-stream")


def _format_sse(item: t.Any) -> str:
    if not isinstance(item, dict):
        item = {"data": item}
    lines: list[str] = []
    for key in ("id", "event", "retry"):
        if item.get(key) is not None:
            lines.append(f"{key}: {item[key]}")
    data = str(item.get("data", ""))
    lines.extend(f"data: {line}" for line in data.splitlines() or [""])
    return "\n".join(lines) + "\n\n"


class JSONResponse(Response):
    def __init__(
        self,
        data: t.Any,
        status: int = 200,
        headers: t.Mapping[str, str] | None = None,
        *,
        dumps: t.Callable[..., str] = json.dumps,
    ):
        """JSON response helper.

        `dumps` can be overridden to plug in a faster JSON library (e.g. orjson)
        while keeping night single-file.
        """

        if dumps is json.dumps:
            encoded = dumps(data, ensure_ascii=False, separators=(",", ":"))
        else:
            # Fast serializers such as orjson return bytes and generally do
            # not accept json.dumps keyword arguments.
            encoded = dumps(data)
        body = encoded if isinstance(encoded, bytes) else str(encoded).encode("utf-8")
        if headers:
            h = dict(headers)
            h.setdefault("content-type", "application/json; charset=utf-8")
            super().__init__(body=body, status=status, headers=h)
        else:
            super().__init__(
                body=body,
                status=status,
                content_type="application/json; charset=utf-8",
            )


class PlainTextResponse(Response):
    def __init__(self, text: str, status: int = 200, headers: t.Mapping[str, str] | None = None):
        if headers:
            h = dict(headers)
            h.setdefault("content-type", "text/plain; charset=utf-8")
            super().__init__(body=text, status=status, headers=h)
        else:
            super().__init__(body=text, status=status, content_type="text/plain; charset=utf-8")


class HTMLResponse(Response):
    def __init__(self, html: str, status: int = 200, headers: t.Mapping[str, str] | None = None):
        if headers:
            h = dict(headers)
            h.setdefault("content-type", "text/html; charset=utf-8")
            super().__init__(body=html, status=status, headers=h)
        else:
            super().__init__(body=html, status=status, content_type="text/html; charset=utf-8")


class TemplateError(ValueError):
    """Raised for invalid Night template syntax or expressions."""


class SafeString(str):
    """String explicitly marked as safe for HTML template output."""


class _TemplateExpression(ast.NodeVisitor):
    def __init__(self, context: t.Mapping[str, t.Any]):
        self.context = context

    def evaluate(self, source: str) -> t.Any:
        try:
            node = ast.parse(source, mode="eval").body
        except SyntaxError as exc:
            raise TemplateError(f"Invalid template expression: {source!r}") from exc
        return self.visit(node)

    def generic_visit(self, node):
        raise TemplateError(f"Unsupported template expression: {type(node).__name__}")

    def visit_Constant(self, node: ast.Constant):
        return node.value

    def visit_Name(self, node: ast.Name):
        if node.id.startswith("_"):
            raise TemplateError("Private names are not available in templates")
        if node.id not in self.context:
            raise TemplateError(f"Unknown template variable: {node.id}")
        return self.context[node.id]

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr.startswith("_"):
            raise TemplateError("Private attributes are not available in templates")
        value = self.visit(node.value)
        if isinstance(value, t.Mapping):
            try:
                return value[node.attr]
            except KeyError as exc:
                raise TemplateError(f"Unknown template attribute: {node.attr}") from exc
        try:
            return getattr(value, node.attr)
        except AttributeError as exc:
            raise TemplateError(f"Unknown template attribute: {node.attr}") from exc

    def visit_Subscript(self, node: ast.Subscript):
        value = self.visit(node.value)
        key = self.visit(node.slice)
        try:
            return value[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise TemplateError(f"Invalid template subscript: {key!r}") from exc

    def visit_List(self, node: ast.List):
        return [self.visit(item) for item in node.elts]

    def visit_Tuple(self, node: ast.Tuple):
        return tuple(self.visit(item) for item in node.elts)

    def visit_Dict(self, node: ast.Dict):
        return {self.visit(k): self.visit(v) for k, v in zip(node.keys, node.values)}

    def visit_UnaryOp(self, node: ast.UnaryOp):
        value = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not value
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return +value
        raise TemplateError("Unsupported unary operator")

    def visit_BoolOp(self, node: ast.BoolOp):
        if isinstance(node.op, ast.And):
            result = True
            for item in node.values:
                result = self.visit(item)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for item in node.values:
                result = self.visit(item)
                if result:
                    return result
            return result
        raise TemplateError("Unsupported boolean operator")

    def visit_BinOp(self, node: ast.BinOp):
        left, right = self.visit(node.left), self.visit(node.right)
        if isinstance(node.op, ast.Add): return left + right
        if isinstance(node.op, ast.Sub): return left - right
        if isinstance(node.op, ast.Mult): return left * right
        if isinstance(node.op, ast.Div): return left / right
        if isinstance(node.op, ast.FloorDiv): return left // right
        if isinstance(node.op, ast.Mod): return left % right
        raise TemplateError("Unsupported binary operator")

    def visit_Compare(self, node: ast.Compare):
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            if isinstance(op, ast.Eq): ok = left == right
            elif isinstance(op, ast.NotEq): ok = left != right
            elif isinstance(op, ast.Lt): ok = left < right
            elif isinstance(op, ast.LtE): ok = left <= right
            elif isinstance(op, ast.Gt): ok = left > right
            elif isinstance(op, ast.GtE): ok = left >= right
            elif isinstance(op, ast.In): ok = left in right
            elif isinstance(op, ast.NotIn): ok = left not in right
            elif isinstance(op, ast.Is): ok = left is right
            elif isinstance(op, ast.IsNot): ok = left is not right
            else: raise TemplateError("Unsupported comparison operator")
            if not ok:
                return False
            left = right
        return True

    def visit_IfExp(self, node: ast.IfExp):
        return self.visit(node.body if self.visit(node.test) else node.orelse)


@dataclasses.dataclass(frozen=True)
class Template:
    """Compiled template produced by :class:`TemplateEngine`."""

    engine: "TemplateEngine"
    source: str
    nodes: tuple[t.Any, ...]
    name: str = "<string>"

    def render(
        self,
        context: t.Mapping[str, t.Any] | None = None,
        *,
        autoescape: bool | None = None,
        render_options: t.Mapping[str, t.Any] | None = None,
        **values: t.Any,
    ) -> str:
        data = self.engine.make_context(context)
        data.update(values)
        escape = self.engine.autoescape if autoescape is None else bool(autoescape)
        options = dict(render_options or {})
        return self.engine._render_nodes(self.nodes, data, escape, options)


class TemplateEngine:
    """Small dependency-free template engine designed for subclassing.

    Syntax::

        ${{ user.name }}
        ${% if user.admin %}admin${% else %}user${% endif %}
        ${% for item in items %}${{ item }}${% endfor %}
        ${% include "partial.html" %}

    Expressions use a restricted Python AST. Function calls, comprehensions,
    lambdas and private names/attributes are intentionally unavailable.
    """

    _token_re = re.compile(r"(\$\{\{.*?\}\}|\$\{%.*?%\}|\$\{#.*?#\})", re.S)

    def __init__(self, template_folder: str = "templates", *, autoescape: bool = False):
        self.template_folder = str(template_folder)
        self.autoescape = bool(autoescape)
        self.filters: dict[str, t.Callable[[t.Any], t.Any]] = {
            "safe": lambda value: SafeString(str(value)),
            "upper": lambda value: str(value).upper(),
            "lower": lambda value: str(value).lower(),
            "length": lambda value: len(value),
            "items": lambda value: value.items(),
            "json": lambda value: SafeString(json.dumps(value, ensure_ascii=False, separators=(",", ":"))),
        }
        self._cache: dict[str, tuple[int, int, Template]] = {}
        self._expression_cache: dict[str, tuple[str, ast.AST, tuple[str, ...]]] = {}
        self._expression_cache: dict[str, tuple[str, ast.AST, tuple[str, ...]]] = {}

    def make_context(self, context: t.Mapping[str, t.Any] | None = None) -> dict[str, t.Any]:
        return dict(context or {})

    def add_filter(self, name: str, fn: t.Callable[[t.Any], t.Any] | None = None):
        def register(func: t.Callable[[t.Any], t.Any]):
            self.filters[str(name)] = func
            return func
        return register if fn is None else register(fn)

    filter = add_filter

    @staticmethod
    def safe(value: t.Any) -> SafeString:
        return SafeString(str(value))

    def _split_filters(self, expression: str) -> list[str]:
        if "|" not in expression:
            expression = expression.strip()
            return [expression] if expression else []
        parts, current = [], []
        depth = 0
        quote = None
        escaped = False
        for char in expression:
            if escaped:
                current.append(char)
                escaped = False
                continue
            if char == "\\" and quote:
                current.append(char)
                escaped = True
                continue
            if quote:
                current.append(char)
                if char == quote:
                    quote = None
                continue
            if char in {"'", '"'}:
                quote = char
                current.append(char)
                continue
            if char in "([{": depth += 1
            elif char in ")]}": depth = max(0, depth - 1)
            if char == "|" and depth == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(char)
        parts.append("".join(current).strip())
        return [part for part in parts if part]

    def _compile_expression(self, expression: str) -> tuple[str, ast.AST, tuple[str, ...]]:
        cached = self._expression_cache.get(expression)
        if cached is not None:
            return cached
        pipeline = self._split_filters(expression)
        if not pipeline:
            compiled = ("", ast.Constant(value=""), ())
            self._expression_cache[expression] = compiled
            return compiled
        base = pipeline[0]
        try:
            node = ast.parse(base, mode="eval").body
        except SyntaxError as exc:
            raise TemplateError(f"Invalid template expression: {base!r}") from exc
        compiled = (base, node, tuple(pipeline[1:]))
        self._expression_cache[expression] = compiled
        return compiled

    def _warm_nodes(self, nodes) -> None:
        for node in nodes:
            kind = node[0]
            if kind == "expr":
                self._compile_expression(node[1])
            elif kind == "if":
                branches, otherwise = node[1], node[2]
                for condition, body in branches:
                    self._compile_expression(condition)
                    self._warm_nodes(body)
                self._warm_nodes(otherwise)
            elif kind == "for":
                _targets, expression, body, otherwise = node[1:]
                self._compile_expression(expression)
                self._warm_nodes(body)
                self._warm_nodes(otherwise)
            elif kind == "include":
                self._compile_expression(node[1])

    def evaluate(self, expression: str, context: t.Mapping[str, t.Any]) -> tuple[str, t.Any]:
        base, node, filters = self._compile_expression(expression)
        if not base:
            return "", ""
        value = _TemplateExpression(context).visit(node)
        for name in filters:
            fn = self.filters.get(name)
            if fn is None:
                raise TemplateError(f"Unknown template filter: {name}")
            value = fn(value)
        return base, value

    def render_value(
        self,
        expression: str,
        value: t.Any,
        context: t.Mapping[str, t.Any],
        *,
        autoescape: bool,
        options: t.Mapping[str, t.Any],
    ) -> str:
        if value is None:
            return ""
        if isinstance(value, SafeString):
            return str(value)
        text = str(value)
        return _html.escape(text, quote=True) if autoescape else text

    def _tokenize(self, source: str) -> list[tuple[str, str]]:
        out = []
        for part in self._token_re.split(str(source)):
            if not part:
                continue
            if part.startswith("${{"):
                out.append(("expr", part[3:-2].strip()))
            elif part.startswith("${%"):
                out.append(("tag", part[3:-2].strip()))
            elif part.startswith("${#"):
                continue
            else:
                out.append(("text", part))
        return out

    def _parse_nodes(self, tokens, index=0, stops=frozenset()):
        nodes = []
        while index < len(tokens):
            kind, value = tokens[index]
            if kind == "text":
                nodes.append(("text", value)); index += 1; continue
            if kind == "expr":
                nodes.append(("expr", value)); index += 1; continue
            head = value.split(None, 1)[0] if value else ""
            if head in stops:
                return nodes, index, value
            if head == "if":
                condition = value[2:].strip()
                if not condition: raise TemplateError("if requires an expression")
                body, index, stop = self._parse_nodes(tokens, index + 1, frozenset({"elif", "else", "endif"}))
                branches = [(condition, tuple(body))]
                while stop and stop.startswith("elif"):
                    condition = stop[4:].strip()
                    if not condition: raise TemplateError("elif requires an expression")
                    body, index, stop = self._parse_nodes(tokens, index + 1, frozenset({"elif", "else", "endif"}))
                    branches.append((condition, tuple(body)))
                otherwise = ()
                if stop and stop.startswith("else"):
                    body, index, stop = self._parse_nodes(tokens, index + 1, frozenset({"endif"}))
                    otherwise = tuple(body)
                if not stop or not stop.startswith("endif"):
                    raise TemplateError("Unclosed if block")
                nodes.append(("if", tuple(branches), otherwise)); index += 1; continue
            if head == "for":
                match = re.fullmatch(r"for\s+(.+?)\s+in\s+(.+)", value, re.S)
                if not match: raise TemplateError("for syntax is: for name in expression")
                targets = tuple(part.strip() for part in match.group(1).split(",") if part.strip())
                if not targets or any(not re.fullmatch(r"[A-Za-z_]\w*", name) or name.startswith("_") for name in targets):
                    raise TemplateError("Invalid for-loop target")
                expression = match.group(2).strip()
                body, index, stop = self._parse_nodes(tokens, index + 1, frozenset({"else", "endfor"}))
                otherwise = ()
                if stop and stop.startswith("else"):
                    other, index, stop = self._parse_nodes(tokens, index + 1, frozenset({"endfor"}))
                    otherwise = tuple(other)
                if not stop or not stop.startswith("endfor"):
                    raise TemplateError("Unclosed for block")
                nodes.append(("for", targets, expression, tuple(body), otherwise)); index += 1; continue
            if head == "include":
                expression = value[len("include"):].strip()
                if not expression: raise TemplateError("include requires a filename expression")
                nodes.append(("include", expression)); index += 1; continue
            raise TemplateError(f"Unknown template tag: {head or value!r}")
        if stops:
            raise TemplateError(f"Unclosed template block; expected one of {sorted(stops)}")
        return nodes, index, None

    def compile(self, source: str, *, name: str = "<string>") -> Template:
        nodes, _, _ = self._parse_nodes(self._tokenize(source))
        frozen_nodes = tuple(nodes)
        self._warm_nodes(frozen_nodes)
        return Template(self, str(source), frozen_nodes, name)

    def _resolve_path(self, filename: str) -> str:
        path = _safe_join(self.template_folder, str(filename))
        if not os.path.isfile(path):
            raise TemplateError(f"Template not found: {filename}")
        return path

    def load(self, filename: str) -> Template:
        path = self._resolve_path(filename)
        stat = os.stat(path)
        cached = self._cache.get(path)
        if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
            return cached[2]
        with open(path, "r", encoding="utf-8") as handle:
            template = self.compile(handle.read(), name=str(filename))
        self._cache[path] = (stat.st_mtime_ns, stat.st_size, template)
        return template

    def _assign_loop_target(self, context: dict[str, t.Any], targets: tuple[str, ...], value: t.Any) -> None:
        if len(targets) == 1:
            context[targets[0]] = value
            return
        try:
            values = tuple(value)
        except TypeError as exc:
            raise TemplateError("Loop value cannot be unpacked") from exc
        if len(values) != len(targets):
            raise TemplateError("Loop target/value length mismatch")
        context.update(zip(targets, values))

    def _render_nodes(self, nodes, context: dict[str, t.Any], autoescape: bool, options: dict[str, t.Any]) -> str:
        out: list[str] = []
        for node in nodes:
            kind = node[0]
            if kind == "text":
                out.append(node[1]); continue
            if kind == "expr":
                expression, value = self.evaluate(node[1], context)
                out.append(self.render_value(expression, value, context, autoescape=autoescape, options=options)); continue
            if kind == "if":
                selected = node[2]
                for condition, body in node[1]:
                    if self.evaluate(condition, context)[1]:
                        selected = body; break
                out.append(self._render_nodes(selected, context, autoescape, options)); continue
            if kind == "for":
                targets, expression, body, otherwise = node[1:]
                iterable = self.evaluate(expression, context)[1]
                values = list(iterable or ())
                if not values:
                    out.append(self._render_nodes(otherwise, context, autoescape, options)); continue
                length = len(values)
                for i, value in enumerate(values):
                    child = dict(context)
                    self._assign_loop_target(child, targets, value)
                    child["loop"] = {
                        "index": i + 1, "index0": i, "first": i == 0,
                        "last": i == length - 1, "length": length,
                    }
                    out.append(self._render_nodes(body, child, autoescape, options))
                continue
            if kind == "include":
                filename = self.evaluate(node[1], context)[1]
                included = self.load(str(filename))
                out.append(included.render(context, autoescape=autoescape, render_options=options)); continue
        return "".join(out)

    def render_text(
        self,
        source: str,
        context: t.Mapping[str, t.Any] | None = None,
        *,
        autoescape: bool | None = None,
        render_options: t.Mapping[str, t.Any] | None = None,
        **values: t.Any,
    ) -> str:
        return self.compile(source).render(context, autoescape=autoescape, render_options=render_options, **values)

    def render_file(
        self,
        filename: str,
        context: t.Mapping[str, t.Any] | None = None,
        *,
        autoescape: bool | None = None,
        render_options: t.Mapping[str, t.Any] | None = None,
        **values: t.Any,
    ) -> str:
        return self.load(filename).render(context, autoescape=autoescape, render_options=render_options, **values)


_default_template_engine = TemplateEngine()


def _template_engine_for_request(engine: TemplateEngine | None = None) -> TemplateEngine:
    if engine is not None:
        return engine
    try:
        req = request()
    except RuntimeError:
        return _default_template_engine
    app = getattr(req, "app", None)
    return getattr(app, "template_engine", _default_template_engine)


def render_template(
    filename: str,
    *,
    engine: TemplateEngine | None = None,
    status: int = 200,
    headers: t.Mapping[str, str] | None = None,
    **context: t.Any,
) -> HTMLResponse:
    selected = _template_engine_for_request(engine)
    return HTMLResponse(selected.render_file(filename, context, autoescape=True), status=status, headers=headers)


def render_template_string(
    source: str,
    *,
    engine: TemplateEngine | None = None,
    status: int = 200,
    headers: t.Mapping[str, str] | None = None,
    **context: t.Any,
) -> HTMLResponse:
    selected = _template_engine_for_request(engine)
    return HTMLResponse(selected.render_text(source, context, autoescape=True), status=status, headers=headers)


def render_text_template(
    source: str,
    *,
    engine: TemplateEngine | None = None,
    **context: t.Any,
) -> str:
    return _template_engine_for_request(engine).render_text(source, context, autoescape=False)


class FileResponse(Response):
    def __init__(
        self,
        path: str,
        req: Request | None = None,
        status: int = 200,
        headers: t.Mapping[str, str] | None = None,
        download_name: str | None = None,
        cache_seconds: int | None = 3600,
    ):
        # Conditional GET support: ETag + If-None-Match, and If-Modified-Since.
        st = os.stat(path)
        mtime = _dt.datetime.fromtimestamp(st.st_mtime, tz=_dt.timezone.utc)

        etag = 'W/"%s"' % hashlib.sha256(
            (str(st.st_size) + ":" + str(int(st.st_mtime))).encode("utf-8")
        ).hexdigest()[:16]

        h = dict(headers or {})
        h.setdefault("content-type", _guess_content_type(path))
        h.setdefault("etag", etag)
        h.setdefault("last-modified", _http_date(mtime))
        if download_name:
            h.setdefault("content-disposition", f'attachment; filename="{download_name}"')
        if cache_seconds is not None:
            h.setdefault("cache-control", f"public, max-age={int(cache_seconds)}")

        if req is not None:
            inm = req.header("if-none-match")
            if inm and inm.strip() == etag:
                super().__init__(body=b"", status=304, headers=h)
                # Remove content-length for 304
                self.headers.pop("content-length", None)
                return

            ims = req.header("if-modified-since")
            if ims:
                dt = _parse_http_date(ims)
                if dt is not None:
                    # RFC: if resource not modified since ims -> 304
                    if mtime.replace(microsecond=0) <= dt.astimezone(_dt.timezone.utc).replace(microsecond=0):
                        super().__init__(body=b"", status=304, headers=h)
                        self.headers.pop("content-length", None)
                        return

        with open(path, "rb") as f:
            data = f.read()
        super().__init__(body=data, status=status, headers=h)


_GZIP_CACHE_DIR = os.path.join(tempfile.gettempdir(), "night-gzip-cache")


def _gzip_cached_file(path: str, level: int = 6) -> tuple[str, str, os.stat_result]:
    """Return a temp-cached gzip representation for a source file."""
    level = int(level)
    if not 0 <= level <= 9:
        raise ValueError("gzip level must be between 0 and 9")

    source_path = os.path.abspath(os.fspath(path))
    st = os.stat(source_path)
    cache_key = hashlib.sha256(
        f"{source_path}\0{st.st_mtime_ns}\0{st.st_size}\0{level}".encode("utf-8")
    ).hexdigest()
    os.makedirs(_GZIP_CACHE_DIR, exist_ok=True)
    cached_path = os.path.join(_GZIP_CACHE_DIR, cache_key + ".gz")
    if os.path.isfile(cached_path):
        return cached_path, cache_key, st

    temp_path = cached_path + f".{os.getpid()}.{time.time_ns()}.tmp"
    try:
        with open(source_path, "rb") as src, open(temp_path, "wb") as raw_dst:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw_dst,
                compresslevel=level,
                mtime=0,
            ) as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
        os.replace(temp_path, cached_path)
        try:
            os.utime(cached_path, ns=(st.st_atime_ns, st.st_mtime_ns))
        except OSError:
            pass
    finally:
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass
    return cached_path, cache_key, st


class FileHandler:
    """Lazy, chainable file response builder returned by send_file()."""

    def __init__(
        self,
        path: str,
        *,
        req: Request | None = None,
        status: int = 200,
        headers: t.Mapping[str, str] | None = None,
        download_name: str | None = None,
        cache_seconds: int | None = 3600,
    ):
        self.path = os.fspath(path)
        self.req = req
        self.status = int(status)
        self.headers = dict(headers or {})
        self.download_name = download_name
        self.cache_seconds = cache_seconds
        self._gzip: bool | None = None
        self._gzip_level: int | None = None

    def gz(self, level: int | None = None):
        """Serve this file as an HTTP gzip-encoded representation."""
        if level is not None:
            level = int(level)
            if not 0 <= level <= 9:
                raise ValueError("gzip level must be between 0 and 9")
        self._gzip = True
        self._gzip_level = level
        return self

    def raw(self):
        """Disable app-level gzip for this file."""
        self._gzip = False
        return self

    def _gzip_settings(self, req: Request | None) -> tuple[bool, int]:
        app = getattr(req, "app", None) if req is not None else None
        app_enabled = bool(getattr(app, "_file_gzip_enabled", False))
        app_level = int(getattr(app, "_file_gzip_level", 6))
        if self._gzip is False:
            return False, app_level
        if self._gzip is True:
            return True, self._gzip_level if self._gzip_level is not None else app_level
        return app_enabled, app_level

    def response(self, req: Request | None = None) -> FileResponse:
        req = req or self.req
        use_gzip, level = self._gzip_settings(req)
        if not use_gzip:
            return FileResponse(
                self.path,
                req=req,
                status=self.status,
                headers=self.headers,
                download_name=self.download_name,
                cache_seconds=self.cache_seconds,
            )

        cached_path, cache_key, st = _gzip_cached_file(self.path, level)
        h = dict(self.headers)
        h.setdefault("content-type", _guess_content_type(self.path))
        h.setdefault("content-encoding", "gzip")
        h.setdefault("vary", "Accept-Encoding")
        h.setdefault("etag", f'W/"gz-{cache_key[:16]}"')
        mtime = _dt.datetime.fromtimestamp(st.st_mtime, tz=_dt.timezone.utc)
        h.setdefault("last-modified", _http_date(mtime))
        return FileResponse(
            cached_path,
            req=req,
            status=self.status,
            headers=h,
            download_name=self.download_name,
            cache_seconds=self.cache_seconds,
        )

    def __call__(self, req: Request | None = None) -> FileResponse:
        return self.response(req)


# ----------------------------
# Routing
# ----------------------------


_converter_patterns = {
    "str": r"[^/]+",
    "int": r"\d+",
    "path": r".+",
}


@dataclasses.dataclass
class Route:
    methods: set[str]
    pattern: re.Pattern
    param_names: list[str]
    endpoint: t.Callable
    raw_path: str
    name: str | None = None
    signature: inspect.Signature | None = dataclasses.field(default=None, init=False)
    body_model: type | None = None

    def __post_init__(self):
        try:
            self.signature = inspect.signature(self.endpoint)
            setattr(self.endpoint, "__night_signature__", self.signature)
        except Exception:
            self.signature = None


def compile_path(path: str) -> tuple[re.Pattern, list[str]]:
    # /users/<int:id>/posts/<slug>
    # converters: str (default), int, path
    param_names: list[str] = []

    def repl(m: re.Match) -> str:
        inner = m.group(1)
        if ":" in inner:
            conv, name = inner.split(":", 1)
        else:
            conv, name = "str", inner
        if conv not in _converter_patterns:
            conv = "str"
        param_names.append(name)
        return f"(?P<{name}>{_converter_patterns[conv]})"

    regex = re.sub(r"<([^>]+)>", repl, path)
    regex = "^" + regex.rstrip("/") + "/?$"
    return re.compile(regex), param_names


def _format_path(path_template: str, params: dict[str, t.Any]) -> str:
    # Replace <name> or <conv:name> segments.
    def repl(m: re.Match) -> str:
        inner = m.group(1)
        name = inner.split(":", 1)[1] if ":" in inner else inner
        if name not in params:
            raise KeyError(name)
        return urllib.parse.quote(str(params[name]), safe="")

    return re.sub(r"<([^>]+)>", repl, path_template)


# ----------------------------
# App / middleware
# ----------------------------


_current_request: contextvars.ContextVar[Request | None] = contextvars.ContextVar("night_request", default=None)


def request() -> Request:
    r = _current_request.get()
    if r is None:
        raise RuntimeError("No active request in context")
    return r


Middleware = t.Callable[[Request, t.Callable[[], t.Awaitable[Response]]], t.Awaitable[Response]]
BeforeHook = t.Callable[[Request], t.Awaitable[t.Optional[Response]] | t.Optional[Response]]
AfterHook = t.Callable[[Request, Response], t.Awaitable[Response] | Response]
ErrorHandler = t.Callable[[Request, Exception], t.Awaitable[Response] | Response]


class Extension:
    """Base class for reusable Night extensions.

    Subclasses typically register routes, middleware, or hooks in
    ``init_app``.  Extensions should keep their own configuration in the
    instance rather than mutating global state.
    """

    def init_app(self, app: "Night", **config: t.Any) -> None:
        raise NotImplementedError


class GraphQLExtension(Extension):
    """Optional GraphQL-over-HTTP endpoint powered by ``graphql-core``."""

    name = "graphql"

    def __init__(self, schema: t.Any, *, path: str = "/graphql"):
        self.schema = schema
        self.path = path

    def init_app(self, app: "Night", **config: t.Any) -> None:
        try:
            from graphql import graphql
        except ImportError as exc:
            raise RuntimeError("GraphQLExtension requires: pip install graphql-core") from exc

        async def endpoint(req: Request):
            payload = await req.json() if req.method in {"POST", "QUERY"} else None
            if payload is None:
                query = req.query.get("query", "")
                variables = req.query.get("variables")
                operation_name = req.query.get("operationName")
                if isinstance(variables, str) and variables:
                    try:
                        variables = json.loads(variables)
                    except json.JSONDecodeError:
                        return JSONResponse({"errors": [{"message": "Invalid variables JSON"}]}, status=400)
            else:
                if not isinstance(payload, dict):
                    return JSONResponse({"errors": [{"message": "Request must be a JSON object"}]}, status=400)
                query = payload.get("query", "")
                variables = payload.get("variables")
                operation_name = payload.get("operationName")

            if not isinstance(query, str) or not query.strip():
                return JSONResponse({"errors": [{"message": "Missing GraphQL query"}]}, status=400)
            result = graphql(
                self.schema,
                query,
                variable_values=variables,
                operation_name=operation_name,
            )
            if inspect.isawaitable(result):
                result = await t.cast(t.Awaitable, result)
            output: dict[str, t.Any] = {}
            if result.data is not None:
                output["data"] = result.data
            if result.errors:
                output["errors"] = [{"message": str(error)} for error in result.errors]
            return JSONResponse(output, status=200 if not result.errors else 400)

        app.route(self.path, methods=("GET", "POST", "QUERY"), name="graphql")(endpoint)


class Router:
    """A blueprint-like container for routes."""

    def __init__(self):
        self.routes: list[Route] = []
        self._json_dumps: t.Callable[..., t.Any] = json.dumps
        self._fast_mode = False
        self._json_dumps: t.Callable[..., t.Any] = json.dumps
        self._fast_mode = False
        self._json_dumps: t.Callable[..., t.Any] = json.dumps
        self._fast_mode = False

    def add_route(
        self,
        method: str | t.Iterable[str],
        path: str,
        handler: t.Callable,
        *,
        name: str | None = None,
        body: type | None = None,
    ):
        methods = (method,) if isinstance(method, str) else method
        methods_set = {m.upper() for m in methods}
        pattern, names = compile_path(path)
        route = Route(
            methods=methods_set,
            pattern=pattern,
            param_names=names,
            endpoint=handler,
            raw_path=path,
            name=name,
            body_model=body,
        )
        if body is not None:
            setattr(handler, "__night_body_model__", body)
        self.routes.append(route)
        hook = getattr(self, "_on_route_added", None)
        if hook is not None:
            hook(route)
        return self

    def route(
        self,
        path: str,
        methods: t.Iterable[str] = ("GET",),
        *,
        name: str | None = None,
        body: type | None = None,
    ):
        def decorator(fn: t.Callable):
            self.add_route(methods, path, fn, name=name, body=body)
            return fn

        return decorator

    def _method(
        self,
        method: str,
        path: str,
        handler: t.Callable | None = None,
        *,
        name: str | None = None,
        body: type | None = None,
    ):
        if handler is None:
            return self.route(path, methods=(method,), name=name, body=body)
        return self.add_route(method, path, handler, name=name, body=body)

    def get(self, path: str, handler: t.Callable | None = None, *, name: str | None = None):
        return self._method("GET", path, handler, name=name)

    def post(
        self,
        path: str,
        handler: t.Callable | None = None,
        *,
        name: str | None = None,
        body: type | None = None,
    ):
        return self._method("POST", path, handler, name=name, body=body)

    def put(self, path: str, handler: t.Callable | None = None, *, name: str | None = None):
        return self._method("PUT", path, handler, name=name)

    def delete(self, path: str, handler: t.Callable | None = None, *, name: str | None = None):
        return self._method("DELETE", path, handler, name=name)

    def query(self, path: str, handler: t.Callable | None = None, *, name: str | None = None):
        return self._method("QUERY", path, handler, name=name)

    def patch(self, path: str, handler: t.Callable | None = None, *, name: str | None = None):
        return self._method("PATCH", path, handler, name=name)

    def purge(self, path: str, handler: t.Callable | None = None, *, name: str | None = None):
        return self._method("PURGE", path, handler, name=name)


class Blueprint(Router):
    """A named, mountable collection of routes and optional setup hook."""

    def __init__(self, name: str, *, url_prefix: str = "", setup: t.Callable | None = None):
        super().__init__()
        self.name = name
        self.url_prefix = ("/" + url_prefix.strip("/")) if url_prefix else ""
        self.setup = setup

    def register(self, app: "Night", *, url_prefix: str | None = None):
        prefix = self.url_prefix if url_prefix is None else url_prefix
        if self.setup is not None:
            self.setup(self)
            self.setup = None
        app.mount(prefix, self)
        return self


CALL_KWARGS = 0
CALL_REQUEST_POSITIONAL = 1
CALL_REQUEST_KEYWORD = 2

ROUTE_CALL_GENERIC = 0
ROUTE_CALL_DIRECT_PARAM = 1
ROUTE_CALL_NOARGS = 2
ROUTE_CALL_REQUEST_KEYWORD = 3
ROUTE_CALL_REQUEST_POSITIONAL = 4


@dataclasses.dataclass(frozen=True, slots=True)
class _EndpointPlan:
    signature: inspect.Signature | None
    type_hints: dict[str, t.Any]
    call_mode: int
    is_coro: bool
    int_params: tuple[str, ...]
    body_model: type | None
    body_candidates: tuple[str, ...]


def _compile_endpoint(fn: t.Callable) -> _EndpointPlan:
    signature = getattr(fn, "__night_signature__", None)
    if signature is None:
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            signature = None

    try:
        type_hints = t.get_type_hints(fn)
    except Exception:
        type_hints = {}

    call_mode = CALL_KWARGS
    int_params: list[str] = []
    body_candidates: list[str] = []

    if signature is not None:
        params = tuple(signature.parameters.values())
        if "req" in signature.parameters:
            call_mode = CALL_REQUEST_KEYWORD
        elif params:
            first = params[0]
            first_type = type_hints.get(first.name, first.annotation)
            if first_type is Request or first.name in {"request", "req"}:
                call_mode = CALL_REQUEST_POSITIONAL

        for param in params:
            annotation = type_hints.get(param.name, param.annotation)
            if annotation is int:
                int_params.append(param.name)
            if param.name not in {"req", "request"}:
                body_candidates.append(param.name)

    return _EndpointPlan(
        signature=signature,
        type_hints=type_hints,
        call_mode=call_mode,
        is_coro=inspect.iscoroutinefunction(fn),
        int_params=tuple(int_params),
        body_model=getattr(fn, "__night_body_model__", None),
        body_candidates=tuple(body_candidates),
    )


class Night(Router):
    def __init__(self, *, debug: bool = False, max_body_size: int = MAX_BODY_SIZE, secret_key: str | bytes | None = None, session_secure: bool | None = None, css: bool = False, css_minify: bool = False, template_folder: str = "templates"):
        super().__init__()
        self.template_engine = TemplateEngine(template_folder=template_folder)
        self.debug = bool(debug)
        self.max_body_size = int(max_body_size)
        self.secret_key = secret_key.encode() if isinstance(secret_key, str) else secret_key
        self.session_secure = session_secure
        self.css_minify = css_minify
        self.styles: CSSRegistry | None = None
        self._css_cache: str | None = None
        self._static_route_index: dict[str, list[Route]] = {}
        self._dynamic_route_index: list[Route] = []
        self._dynamic_method_routes: dict[str, list[Route]] = {}
        self._dynamic_prefix_index: dict[str, dict[str, list[Route]]] = {}
        self._dynamic_terminal_index: dict[str, dict[str, Route]] = {}
        self._static_method_index: dict[str, dict[str, Route]] = {}
        self._static_methods_by_path: dict[str, set[str]] = {}
        self._endpoint_plans: dict[t.Callable, _EndpointPlan] = {}
        self._file_gzip_enabled = False
        self._file_gzip_level = 6
        if css: self.enable_css(minify=css_minify)
        self.middlewares: list[Middleware] = []
        self.before_hooks: list[BeforeHook] = []
        self.after_hooks: list[AfterHook] = []
        self.error_handlers: dict[type[BaseException], ErrorHandler] = {}
        self.state: dict[str, t.Any] = {}
        self.extensions: dict[str, t.Any] = {}
        self.websocket_routes: list[Route] = []
        self.rpc_methods: dict[str, t.Callable] = {}
        self._rpc_route_installed = False
        self.startup_hooks: list[t.Callable] = []
        self.shutdown_hooks: list[t.Callable] = []

    def fast(self) -> "Night":
        """Enable Night's optional CPython fast profile.

        Requires ``all-night[standard]``. Dict/list responses use ``orjson``;
        ``night run`` also selects uvloop/httptools/websockets when available.
        External ASGI servers keep control of their own event loop/backend.
        """
        try:
            import orjson
        except ImportError as exc:
            raise RuntimeError(
                "Night.fast() requires the standard profile: "
                "pip install 'all-night[standard]'"
            ) from exc
        self._json_dumps = orjson.dumps
        self._fast_mode = True
        return self

    def gz(self, level: int = 6):
        """Enable gzip by default for send_file() and static() responses."""
        level = int(level)
        if not 0 <= level <= 9:
            raise ValueError("gzip level must be between 0 and 9")
        self._file_gzip_enabled = True
        self._file_gzip_level = level
        return self

    def test_client(self) -> TestClient:
        return TestClient(self)

    @staticmethod
    def _classify_route_call(route: Route, plan: _EndpointPlan) -> None:
        if plan.body_model is not None:
            route._night_call_kind = ROUTE_CALL_GENERIC
            return
        if route._night_direct_param is not None:
            route._night_call_kind = ROUTE_CALL_DIRECT_PARAM
            return
        if plan.call_mode == CALL_REQUEST_KEYWORD:
            route._night_call_kind = ROUTE_CALL_REQUEST_KEYWORD
            return
        if plan.call_mode == CALL_REQUEST_POSITIONAL:
            route._night_call_kind = ROUTE_CALL_REQUEST_POSITIONAL
            return
        sig = plan.signature
        if plan.call_mode == CALL_KWARGS and sig is not None and not sig.parameters:
            route._night_call_kind = ROUTE_CALL_NOARGS
            return
        route._night_call_kind = ROUTE_CALL_GENERIC

    def _compile_route_invoker(self, route: Route, plan: _EndpointPlan):
        fn = route.endpoint
        coerce = self._coerce_response
        kind = route._night_call_kind
        route._night_invoke_async = plan.is_coro
        route._night_invoke_scalar = None

        if kind == ROUTE_CALL_DIRECT_PARAM:
            name = route._night_direct_param
            if plan.is_coro:
                async def invoke(req, params, _fn=fn, _name=name, _coerce=coerce):
                    return _coerce(await _fn(params[_name]))
                async def invoke_scalar(value, _fn=fn, _coerce=coerce):
                    return _coerce(await _fn(value))
            else:
                def invoke(req, params, _fn=fn, _name=name, _coerce=coerce):
                    return _coerce(_fn(params[_name]))
                def invoke_scalar(value, _fn=fn, _coerce=coerce):
                    return _coerce(_fn(value))
            route._night_invoke_scalar = invoke_scalar
            return invoke

        if kind == ROUTE_CALL_NOARGS:
            if plan.is_coro:
                async def invoke(req, params, _fn=fn, _coerce=coerce):
                    return _coerce(await _fn())
            else:
                def invoke(req, params, _fn=fn, _coerce=coerce):
                    return _coerce(_fn())
            return invoke

        if kind == ROUTE_CALL_REQUEST_KEYWORD:
            if plan.is_coro:
                async def invoke(req, params, _fn=fn, _coerce=coerce):
                    return _coerce(await _fn(req=req, **params))
            else:
                def invoke(req, params, _fn=fn, _coerce=coerce):
                    return _coerce(_fn(req=req, **params))
            return invoke

        if kind == ROUTE_CALL_REQUEST_POSITIONAL:
            if plan.is_coro:
                async def invoke(req, params, _fn=fn, _coerce=coerce):
                    return _coerce(await _fn(req, **params))
            else:
                def invoke(req, params, _fn=fn, _coerce=coerce):
                    return _coerce(_fn(req, **params))
            return invoke

        route._night_invoke_async = True
        async def invoke(req, params, _route=route):
            return await self._call_route_generic(_route, req, params)
        return invoke

    @staticmethod
    def _simple_dynamic_value(route: Route, path: str):
        prefix, suffix, _name, converter = route._night_simple_dynamic
        if not path.startswith(prefix):
            return None
        if suffix:
            if not path.endswith(suffix):
                return None
            value = path[len(prefix):len(path) - len(suffix)]
        else:
            value = path[len(prefix):]
        if not value or '/' in value:
            return None
        if converter == 'int':
            try:
                value = int(value)
            except ValueError:
                return None
        return value

    def _match_direct_for_dispatch(self, path: str, method: str):
        key = path.rstrip('/') or '/'

        method_routes = self._static_method_index.get(method)
        if method_routes is not None:
            route = method_routes.get(key)
            if route is not None and route._night_call_kind == ROUTE_CALL_NOARGS:
                return route, None

        routes = self._dynamic_method_routes.get(method)
        if routes and len(routes) == 1:
            route = routes[0]
            if route._night_call_kind == ROUTE_CALL_DIRECT_PARAM and route._night_simple_dynamic is not None:
                value = self._simple_dynamic_value(route, key)
                if value is not None:
                    return route, value
        elif routes:
            terminal = self._dynamic_terminal_index.get(method)
            if terminal:
                base, sep, value = key.rpartition('/')
                if sep and value:
                    route = terminal.get(base or '/')
                    if route is not None and route._night_call_kind == ROUTE_CALL_DIRECT_PARAM:
                        _prefix, _suffix, _name, converter = route._night_simple_dynamic
                        if converter == 'int':
                            try:
                                value = int(value)
                            except ValueError:
                                return None
                        return route, value
        return None

    def _on_route_added(self, route: Route):
        key = route.raw_path.rstrip("/") or "/"
        plan = _compile_endpoint(route.endpoint)
        self._endpoint_plans[route.endpoint] = plan
        route._night_plan = plan
        route._night_simple_dynamic = None
        route._night_direct_param = None
        route._night_call_kind = ROUTE_CALL_GENERIC

        if "<" in route.raw_path:
            self._dynamic_route_index.append(route)

            # Common one-parameter routes get a regex-free matcher.
            tokens = list(re.finditer(r"<([^>]+)>", key))
            if len(tokens) == 1:
                token = tokens[0]
                inner = token.group(1)
                if ":" in inner:
                    converter, name = inner.split(":", 1)
                else:
                    converter, name = "str", inner
                if converter in {"str", "int"}:
                    prefix = key[:token.start()]
                    suffix = key[token.end():]
                    route._night_simple_dynamic = (prefix, suffix, name, converter)

                    # For the common def handler(id): case, bypass **kwargs and
                    # call the function positionally. This removes a kwargs
                    # expansion from the hottest dynamic path.
                    sig = plan.signature
                    if plan.call_mode == CALL_KWARGS and plan.body_model is None and sig is not None:
                        ps = tuple(sig.parameters.values())
                        if (
                            len(ps) == 1
                            and ps[0].name == name
                            and ps[0].kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                        ):
                            route._night_direct_param = name

            for method in route.methods:
                routes = self._dynamic_method_routes.setdefault(method, [])
                routes.append(route)
                if route._night_simple_dynamic is not None:
                    prefix, suffix, _name, _converter = route._night_simple_dynamic
                    self._dynamic_prefix_index.setdefault(method, {}).setdefault(prefix, []).append(route)
                    if not suffix and prefix.endswith("/"):
                        base = prefix[:-1] or "/"
                        self._dynamic_terminal_index.setdefault(method, {})[base] = route
            self._classify_route_call(route, plan)
            route._night_invoke = self._compile_route_invoker(route, plan)
            return

        self._classify_route_call(route, plan)
        route._night_invoke = self._compile_route_invoker(route, plan)
        self._static_route_index.setdefault(key, []).append(route)
        methods = self._static_methods_by_path.setdefault(key, set())
        for method in route.methods:
            methods.add(method)
            self._static_method_index.setdefault(method, {})[key] = route
    @staticmethod
    def _match_simple_dynamic(route: Route, path: str):
        prefix, suffix, name, converter = route._night_simple_dynamic
        if not path.startswith(prefix):
            return None
        if suffix:
            if not path.endswith(suffix):
                return None
            value = path[len(prefix):len(path) - len(suffix)]
        else:
            value = path[len(prefix):]
        if not value or "/" in value:
            return None
        if converter == "int":
            try:
                value = int(value)
            except ValueError:
                return None
        return {name: value}

    def _match_prefixed_dynamic(self, path: str, method: str):
        index = self._dynamic_prefix_index.get(method)
        if not index:
            return None

        # Probe literal prefixes from longest to shortest. Runtime cost scales
        # with path depth rather than number of routes.
        probe = path
        while True:
            slash = probe.rfind("/")
            if slash <= 0:
                break
            prefix = probe[:slash + 1]
            routes = index.get(prefix)
            if routes:
                for route in routes:
                    params = self._match_simple_dynamic(route, path)
                    if params is not None:
                        return route, params
            probe = probe[:slash]

        routes = index.get("/")
        if routes:
            for route in routes:
                params = self._match_simple_dynamic(route, path)
                if params is not None:
                    return route, params
        return None

    def enable_css(self, *, minify: bool = False):
        self.css_minify = minify
        self.styles = self.styles or CSSRegistry()
        if not any(r.raw_path == "/_night/style.css" for r in self.routes):
            @self.get("/_night/style.css")
            def _style():
                if self._css_cache is None:
                    self._css_cache = self.styles.render(minify=self.css_minify)
                return Response(self._css_cache, content_type="text/css; charset=utf-8", headers={"cache-control": "no-cache"})
        return self

    def enable_csrf_endpoint(self, path: str = "/csrf-token"):
        """Expose a JSON endpoint for SPA CSRF token acquisition."""
        if not path.startswith("/"):
            raise ValueError("CSRF endpoint path must start with '/'")
        if any(route.raw_path == path for route in self.routes):
            raise ValueError(f"Route already exists: {path}")

        @self.get(path, name="csrf_token")
        def _csrf_token_endpoint():
            return {"csrf_token": csrf_token()}
        return self

    def css(self, rules: dict[str, t.Any]):
        if self.styles is None: raise RuntimeError("CSS support is disabled; use Night(css=True) or enable_css()")
        self.styles.add(rules)
        self._css_cache = None
        return self

    def css_variables(self, variables: dict[str, t.Any]):
        if self.styles is None: raise RuntimeError("CSS support is disabled")
        self.styles.add_variables(variables)
        self._css_cache = None
        return self

    def keyframes(self, name: str, frames: dict[str, dict[str, t.Any]]):
        if self.styles is None: raise RuntimeError("CSS support is disabled")
        self.styles.add_keyframes(name, frames)
        self._css_cache = None
        return self

    @property
    def css_url(self) -> str:
        if self.styles is None: raise RuntimeError("CSS support is disabled")
        return "/_night/style.css"

    def css_tag(self) -> str:
        return f'<link rel="stylesheet" href="{self.css_url}">'

    def rpc(self, name: str):
        def decorator(fn: t.Callable):
            self.rpc_methods[name] = fn
            if not self._rpc_route_installed:
                self._install_rpc_route()
            return fn
        return decorator

    def _install_rpc_route(self):
        self._rpc_route_installed = True

        @self.post("/rpc", name="rpc")
        async def _rpc(req: Request):
            call = await req.json()
            if not isinstance(call, dict) or call.get("jsonrpc") != "2.0":
                return jsonify({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid Request"}}, status=400)
            fn = self.rpc_methods.get(call.get("method"))
            if fn is None:
                return jsonify({"jsonrpc": "2.0", "error": {"code": -32601, "message": "Method not found"}, "id": call.get("id")}, status=404)
            try:
                params = call.get("params", [])
                result = fn(**params) if isinstance(params, dict) else fn(*params)
                if inspect.isawaitable(result):
                    result = await t.cast(t.Awaitable, result)
                return jsonify({"jsonrpc": "2.0", "result": result, "id": call.get("id")})
            except Exception as exc:
                return jsonify({"jsonrpc": "2.0", "error": {"code": -32603, "message": str(exc)}, "id": call.get("id")}, status=500)

    async def cloudflare_rpc(
        self,
        method: str,
        args: t.Any = None,
        kwargs: t.Any = None,
    ) -> t.Any:
        """Invoke a registered ``@app.rpc`` method over Workers RPC.

        The Cloudflare runtime SDK owns the Python <-> JavaScript/RPC value
        conversion. Keeping this bridge lazy preserves Night's zero-dependency
        behavior outside Cloudflare Workers.
        """
        try:
            from workers.rpc import python_from_rpc, python_to_rpc
        except ImportError as exc:
            raise RuntimeError(
                "Cloudflare RPC requires workers-runtime-sdk inside a Python Worker"
            ) from exc

        fn = self.rpc_methods.get(str(method))
        if fn is None:
            raise KeyError(f"Unknown Night RPC method: {method}")

        call_args = python_from_rpc(args) if args is not None else []
        call_kwargs = python_from_rpc(kwargs) if kwargs is not None else {}
        if not isinstance(call_args, (list, tuple)):
            raise TypeError("Workers RPC args must be a list or tuple")
        if not isinstance(call_kwargs, dict):
            raise TypeError("Workers RPC kwargs must be a mapping")

        result = fn(*call_args, **call_kwargs)
        if inspect.isawaitable(result):
            result = await t.cast(t.Awaitable, result)
        return python_to_rpc(result)

    async def cloudflare_fetch(self, request: t.Any, *, response_class: t.Any = None) -> t.Any:
        """Serve a Cloudflare Workers Request through Night's ASGI core.

        This embeds the old portable/web adapter path into Night itself. It
        accepts the official ``workers.Request`` wrapper and also keeps a
        fallback for raw JS Request objects used by older compatibility dates.
        """
        try:
            if response_class is None:
                from workers import Response as response_class
        except ImportError as exc:
            raise RuntimeError(
                "Cloudflare fetch integration requires workers-runtime-sdk"
            ) from exc

        parsed = urllib.parse.urlsplit(str(request.url))
        method_value = getattr(request.method, "value", request.method)
        method = str(method_value).upper()

        header_source = getattr(request, "headers", ())
        try:
            header_items = header_source.items()
        except Exception:
            try:
                header_items = dict(header_source).items()
            except Exception:
                header_items = ()
        headers = [
            (str(key).lower().encode("latin-1"), str(value).encode("latin-1"))
            for key, value in header_items
        ]

        body = b""
        if method not in {"GET", "HEAD"}:
            if hasattr(request, "bytes"):
                body = bytes(await request.bytes())
            else:
                raw = await request.arrayBuffer()
                try:
                    body = bytes(raw.to_py())
                except Exception:
                    body = bytes(raw)
            if len(body) > self.max_body_size:
                raise HTTPError(413, "Request body too large")

        encoded_path = parsed.path or "/"
        decoded_path = urllib.parse.unquote(encoded_path)
        scheme = parsed.scheme or "https"
        port = parsed.port or (443 if scheme == "https" else 80)
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": scheme,
            "path": decoded_path,
            "raw_path": encoded_path.encode("utf-8"),
            "query_string": parsed.query.encode("latin-1"),
            "headers": headers,
            "server": (parsed.hostname or "edge", port),
            "client": None,
        }

        received = False
        async def receive():
            nonlocal received
            if received:
                return {"type": "http.request", "body": b"", "more_body": False}
            received = True
            return {"type": "http.request", "body": body, "more_body": False}

        events: list[dict[str, t.Any]] = []
        async def send(event):
            events.append(event)

        await self(scope, receive, send)
        start = next((event for event in events if event.get("type") == "http.response.start"), None)
        if start is None:
            raise RuntimeError("Night produced no HTTP response start event")
        chunks = [
            event.get("body", b"")
            for event in events
            if event.get("type") == "http.response.body"
        ]
        web_headers = [
            (key.decode("latin-1"), value.decode("latin-1"))
            for key, value in start.get("headers", ())
        ]
        return response_class(
            b"".join(chunks),
            status=int(start["status"]),
            headers=web_headers,
        )

    def openapi(self) -> dict[str, t.Any]:
        paths: dict[str, dict[str, t.Any]] = {}
        for route in self.routes:
            path = re.sub(r"<(?:(\w+):)?(\w+)>", lambda m: "{" + m.group(2) + "}", route.raw_path)
            item = paths.setdefault(path, {})
            for method in route.methods:
                if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "QUERY"}:
                    operation: dict[str, t.Any] = {"operationId": route.name or getattr(route.endpoint, "__name__", "endpoint"), "responses": {"200": {"description": "Success"}}}
                    body_model = route.body_model or getattr(route.endpoint, "__night_body_model__", None)
                    if body_model is not None:
                        operation["requestBody"] = {"required": True, "content": {"application/json": {"schema": _dataclass_schema(body_model)}}}
                    item[method.lower()] = operation
        return {"openapi": "3.1.0", "info": {"title": "Night API", "version": "1.0.0"}, "paths": paths}

    def on_startup(self, fn: t.Callable):
        self.startup_hooks.append(fn)
        return fn

    def on_shutdown(self, fn: t.Callable):
        self.shutdown_hooks.append(fn)
        return fn

    def register_extension(
        self,
        extension: t.Any,
        *,
        name: str | None = None,
        **config: t.Any,
    ) -> t.Any:
        """Install an extension and return it.

        An extension may be an object with ``init_app(app, **config)`` or a
        callable accepting the app.  The optional name is used for lookup in
        ``app.extensions`` and defaults to the class name.
        """
        key = name or getattr(extension, "name", None) or extension.__class__.__name__.lower()
        if hasattr(extension, "init_app"):
            extension.init_app(self, **config)
        elif callable(extension):
            result = extension(self, **config)
            if result is not None:
                extension = result
        else:
            raise TypeError("extension must be callable or define init_app(app, **config)")
        self.extensions[key] = extension
        return extension

    def register_blueprint(self, blueprint: Blueprint, *, url_prefix: str | None = None):
        """Mount a Blueprint and return it for fluent setup code."""
        return blueprint.register(self, url_prefix=url_prefix)

    def websocket(self, path: str, *, name: str | None = None):
        def decorator(fn: t.Callable):
            pattern, names = compile_path(path)
            self.websocket_routes.append(Route({"WEBSOCKET"}, pattern, names, fn, path, name))
            return fn
        return decorator

    async def _handle_websocket(self, scope, receive, send):
        path = scope.get("path") or "/"
        for route in self.websocket_routes:
            match = route.pattern.match(path)
            if not match:
                continue
            ws = WebSocket(scope, receive, send)
            try:
                params = match.groupdict()
                sig = inspect.signature(route.endpoint)
                kwargs = dict(params)
                if "ws" in sig.parameters:
                    result = route.endpoint(ws=ws, **kwargs)
                elif sig.parameters:
                    result = route.endpoint(ws, **kwargs)
                else:
                    result = route.endpoint(**kwargs)
                if inspect.isawaitable(result):
                    await t.cast(t.Awaitable, result)
            except ConnectionError:
                return
            except Exception:
                await ws.close(code=1011, reason="Internal server error")
            return
        await send({"type": "websocket.close", "code": 1008})

    def lua_macro(
        self,
        path: str,
        source: str,
        *,
        methods: t.Iterable[str] = ("GET",),
        name: str | None = None,
    ):
        """Register a small optional Lua macro as a normal route.

        Example::

            app.lua_macro("/hello", 'return "hello " .. req.query.name')

        Install ``lupa`` separately when Lua support is wanted.  The macro
        receives only a plain request-data table and cannot access the Python
        process through this API.
        """
        return self.route(path, methods=methods, name=name)(_lua_macro_endpoint(source))

    # ---- middleware API ----
    def use(self, middleware: Middleware):
        self.middlewares.append(middleware)
        return middleware

    # ---- hooks ----
    def before_request(self, fn: BeforeHook):
        self.before_hooks.append(fn)
        return fn

    def after_request(self, fn: AfterHook):
        self.after_hooks.append(fn)
        return fn

    def errorhandler(self, exc_type: type[BaseException]):
        def decorator(fn: ErrorHandler):
            self.error_handlers[exc_type] = fn
            return fn

        return decorator

    # ---- mounting ----
    def mount(self, prefix: str, router: Router):
        prefix = ("/" + prefix.strip("/")) if prefix else ""
        for r in router.routes:
            mounted_path = prefix + ("/" + r.raw_path.lstrip("/"))
            pattern, names = compile_path(mounted_path)
            self.routes.append(
                Route(
                    methods=set(r.methods),
                    pattern=pattern,
                    param_names=names,
                    endpoint=r.endpoint,
                    raw_path=mounted_path,
                    name=r.name,
                )
            )
        self._static_route_index.clear()
        self._dynamic_route_index.clear()
        self._dynamic_method_routes.clear()
        self._dynamic_prefix_index.clear()
        self._dynamic_terminal_index.clear()
        self._static_method_index.clear()
        self._static_methods_by_path.clear()
        self._endpoint_plans.clear()
        for route in self.routes: self._on_route_added(route)
        return router

    # ---- url building ----
    def url_for(self, name: str, /, **params: t.Any) -> str:
        for r in self.routes:
            if r.name == name:
                path = _format_path(r.raw_path, params)
                # remaining params become query params
                used = set(r.param_names)
                q = {k: v for k, v in params.items() if k not in used}
                if q:
                    return path + "?" + urllib.parse.urlencode(q, doseq=True)
                return path
        raise KeyError(f"No route with name={name!r}")

    # ---- dispatch ----
    def _match(self, path: str) -> tuple[Route, dict[str, str]]:
        for r in self.routes:
            m = r.pattern.match(path)
            if m:
                return r, m.groupdict()
        raise NotFound()

    def _match_method(self, path: str, method: str) -> tuple[Route, dict[str, t.Any]]:
        key = path.rstrip("/") or "/"

        method_routes = self._static_method_index.get(method)
        if method_routes is not None:
            route = method_routes.get(key)
            if route is not None:
                return route, {}

        if key in self._static_methods_by_path:
            raise MethodNotAllowed(self._allowed_methods_for_path(path))

        routes = self._dynamic_method_routes.get(method)

        # One dynamic route is common for tiny services. Avoid prefix probing
        # and all combined-router machinery in that case.
        if routes and len(routes) == 1:
            route = routes[0]
            if route._night_simple_dynamic is not None:
                params = self._match_simple_dynamic(route, key)
                if params is not None:
                    return route, params
            else:
                match = route.pattern.match(path)
                if match is not None:
                    values = match.groups()
                    params: dict[str, t.Any] = dict(zip(route.param_names, values))
                    plan = route._night_plan
                    for name in plan.int_params:
                        value = params.get(name)
                        if value is not None and type(value) is not int:
                            try:
                                params[name] = int(value)
                            except (TypeError, ValueError):
                                pass
                    return route, params
        else:
            terminal = self._dynamic_terminal_index.get(method)
            if terminal:
                base, sep, value = key.rpartition("/")
                if sep and value:
                    route = terminal.get(base or '/')
                    if route is not None:
                        _prefix, _suffix, name, converter = route._night_simple_dynamic
                        if converter == "int":
                            try:
                                value = int(value)
                            except ValueError:
                                route = None
                        if route is not None:
                            return route, {name: value}

            prefixed = self._match_prefixed_dynamic(key, method)
            if prefixed is not None:
                return prefixed

            # Generic fallback only for complex/multi-parameter routes.
            if routes:
                for route in routes:
                    if route._night_simple_dynamic is not None:
                        continue
                    match = route.pattern.match(path)
                    if match is None:
                        continue
                    values = match.groups()
                    params = dict(zip(route.param_names, values))
                    plan = route._night_plan
                    for name in plan.int_params:
                        value = params.get(name)
                        if value is not None and type(value) is not int:
                            try:
                                params[name] = int(value)
                            except (TypeError, ValueError):
                                pass
                    return route, params

        allowed = self._allowed_methods_for_path(path)
        if allowed:
            raise MethodNotAllowed(allowed)
        raise NotFound()
    def _coerce_response(self, value: t.Any) -> Response:
        kind = type(value)
        if kind is dict or kind is list:
            return JSONResponse(value, dumps=self._json_dumps)
        if kind is str:
            return PlainTextResponse(value)
        if kind is bytes:
            return Response(value)
        if value is None:
            return Response(b"", status=204)
        if isinstance(value, FileHandler):
            return value.response(request())
        if isinstance(value, Response):
            return value
        if kind is bytearray:
            return Response(value)
        return PlainTextResponse(str(value))

    async def _call_route_generic(self, route: Route, req: Request, params: dict[str, t.Any]) -> Response:
        plan = route._night_plan
        fn = route.endpoint
        kwargs = params

        if plan.body_model is not None:
            payload = await req.json()
            validated = _validate_dataclass(plan.body_model, payload)
            target = next((name for name in plan.body_candidates if name not in kwargs), None)
            if target is not None:
                kwargs[target] = validated
            else:
                kwargs.setdefault("data", validated)

        if plan.call_mode == CALL_REQUEST_KEYWORD:
            result = fn(req=req, **kwargs)
        elif plan.call_mode == CALL_REQUEST_POSITIONAL:
            result = fn(req, **kwargs)
        elif kwargs:
            result = fn(**kwargs)
        else:
            result = fn()

        if plan.is_coro:
            result = await t.cast(t.Awaitable, result)
        return self._coerce_response(result)

    async def _call_route(self, route: Route, req: Request, params: dict[str, t.Any]) -> Response:
        invoke = getattr(route, "_night_invoke", None)
        if invoke is None:
            # Compatibility path for synthetic routes used by _call_endpoint().
            return await self._call_route_generic(route, req, params)
        result = invoke(req, params)
        if getattr(route, "_night_invoke_async", False):
            return await result
        return result
    async def _call_endpoint(self, fn: t.Callable, req: Request, params: dict[str, t.Any]) -> Response:
        plan = self._endpoint_plans.get(fn)
        if plan is None:
            plan = _compile_endpoint(fn)
            self._endpoint_plans[fn] = plan
        route = types.SimpleNamespace(endpoint=fn, _night_plan=plan, _night_direct_param=None, _night_call_kind=ROUTE_CALL_GENERIC)
        self._classify_route_call(route, plan)
        for name in plan.int_params:
            value = params.get(name)
            if value is not None and type(value) is not int:
                try:
                    params[name] = int(value)
                except (TypeError, ValueError):
                    pass
        return await self._call_route(route, req, params)

    async def _run_before_hooks(self, req: Request) -> Response | None:
        for fn in self.before_hooks:
            res = fn(req)
            if inspect.isawaitable(res):
                res = await t.cast(t.Awaitable, res)
            if isinstance(res, Response):
                return res
        return None

    async def _run_after_hooks(self, req: Request, resp: Response) -> Response:
        for fn in self.after_hooks:
            out = fn(req, resp)
            if inspect.isawaitable(out):
                out = await t.cast(t.Awaitable, out)
            if isinstance(out, Response):
                resp = out
        return resp

    def _find_error_handler(self, exc: BaseException) -> ErrorHandler | None:
        # Exact match first, then nearest base class.
        et = type(exc)
        if et in self.error_handlers:
            return self.error_handlers[et]
        for k, v in self.error_handlers.items():
            if isinstance(exc, k):
                return v
        return None

    async def _dispatch(self, req: Request, path: str | None = None, method: str | None = None) -> Response:
        path = req.path if path is None else path
        method = req.method if method is None else method
        if self.before_hooks:
            early = await self._run_before_hooks(req)
            if early is not None:
                return early

        direct = self._match_direct_for_dispatch(path, method)
        if direct is not None:
            route, value = direct
            if route._night_call_kind == ROUTE_CALL_DIRECT_PARAM:
                name = route._night_direct_param
                req.path_params[name] = value
                invoke = route._night_invoke_scalar
                if route._night_invoke_async:
                    resp = await invoke(value)
                else:
                    resp = invoke(value)
            else:
                invoke = route._night_invoke
                if route._night_invoke_async:
                    resp = await invoke(req, req.path_params)
                else:
                    resp = invoke(req, req.path_params)
        else:
            route, params = self._match_method(path, method)
            req.path_params = params
            invoke = route._night_invoke
            if route._night_invoke_async:
                resp = await invoke(req, params)
            else:
                resp = invoke(req, params)

        if self.after_hooks:
            resp = await self._run_after_hooks(req, resp)
        return resp

    def _allowed_methods_for_path(self, path: str) -> set[str]:
        key = path.rstrip("/") or "/"
        static_methods = self._static_methods_by_path.get(key)
        if static_methods is not None:
            methods = set(static_methods)
        else:
            methods: set[str] = set()
            for route in self._dynamic_route_index:
                if route.pattern.match(path):
                    methods |= set(route.methods)
        if "GET" in methods:
            methods.add("HEAD")
        return methods

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "websocket":
            await self._handle_websocket(scope, receive, send)
            return
        if scope.get("type") == "lifespan":
            await self._handle_lifespan(receive, send)
            return
        if scope.get("type") != "http":
            return

        if self.secret_key:
            request_scope = dict(scope)
            request_scope["session_secret"] = self.secret_key
        else:
            request_scope = scope
        req = Request(scope=request_scope, receive=receive, send=send, app=self, max_body_size=self.max_body_size)
        method = (request_scope.get("method") or "GET").upper()
        path = request_scope.get("path") or "/"
        token = _current_request.set(req)
        try:
            # Automatic OPTIONS and HEAD support.
            if method == "OPTIONS":
                allowed = self._allowed_methods_for_path(path)
                if allowed:
                    allowed_with_opts = set(allowed) | {"OPTIONS"}
                    hdrs = {
                        "allow": ",".join(sorted(allowed_with_opts)),
                    }
                    resp = Response(b"", status=204, headers=hdrs)
                else:
                    resp = PlainTextResponse("Not Found", status=404)
                await resp(scope, receive, send)
                return

            is_head = method == "HEAD"
            if is_head:
                # Treat HEAD as GET for routing; body will be stripped later.
                req.scope = dict(req.scope)
                req.scope["method"] = "GET"
                method = "GET"

            try:
                if self.middlewares:
                    async def call_next(i: int = 0) -> Response:
                        if i >= len(self.middlewares):
                            return await self._dispatch(req, path, method)

                        mw = self.middlewares[i]

                        async def nxt() -> Response:
                            return await call_next(i + 1)

                        return await mw(req, nxt)

                    resp = await call_next(0)
                else:
                    resp = await self._dispatch(req, path, method)
            except HTTPError as he:
                handler = self._find_error_handler(he)
                if handler is not None:
                    out = handler(req, he)
                    if inspect.isawaitable(out):
                        out = await t.cast(t.Awaitable, out)
                    resp = self._coerce_response(out)
                else:
                    error_headers = {}
                    if isinstance(he, MethodNotAllowed) and he.allowed:
                        error_headers["allow"] = ",".join(he.allowed)
                    if isinstance(he, ValidationError):
                        resp = JSONResponse({"errors": he.errors}, status=he.status, headers=error_headers)
                    elif self.debug:
                        resp = PlainTextResponse(f"{he.status} {he.detail}", status=he.status, headers=error_headers)
                    else:
                        resp = PlainTextResponse(he.detail or "Error", status=he.status, headers=error_headers)
            except Exception as e:
                handler = self._find_error_handler(e)
                if handler is not None:
                    out = handler(req, e)
                    if inspect.isawaitable(out):
                        out = await t.cast(t.Awaitable, out)
                    resp = self._coerce_response(out)
                else:
                    if self.debug:
                        resp = PlainTextResponse(traceback.format_exc(), status=500)
                    else:
                        resp = PlainTextResponse("Internal Server Error", status=500)

            if is_head:
                # HEAD has no body, but preserves GET's representation metadata.
                content_length = resp.headers.get("content-length")
                resp.body = b""
                if content_length is not None:
                    resp.headers["content-length"] = content_length
                else:
                    resp.headers.pop("content-length", None)

            if self.secret_key and "_session" in req.scope:
                current = json.dumps(req.scope["_session"], sort_keys=True, separators=(",", ":"))
                original = req.scope.get("_session_original", "")
                if current != original or req.scope.get("_session_regenerated"):
                    encoded = base64.urlsafe_b64encode(current.encode()).decode().rstrip("=")
                    signature = hmac.new(self.secret_key, encoded.encode(), hashlib.sha256).hexdigest()
                    if len(encoded) + len(signature) + len("night_session=; Path=/; HttpOnly; SameSite=Lax") > MAX_SESSION_COOKIE_SIZE:
                        resp = PlainTextResponse("Internal Server Error" if not self.debug else "Session data exceeds cookie size limit", status=500)
                    else:
                        secure = self.session_secure if self.session_secure is not None else scope.get("scheme") == "https"
                        resp.set_cookie("night_session", encoded + "." + signature, httponly=True, secure=secure, samesite="Lax")

            await resp(scope, receive, send)
        finally:
            _current_request.reset(token)

    async def _handle_lifespan(self, receive, send):
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                try:
                    for fn in self.startup_hooks:
                        result = fn()
                        if inspect.isawaitable(result):
                            await t.cast(t.Awaitable, result)
                except Exception as exc:
                    await send({"type": "lifespan.startup.failed", "message": str(exc)})
                else:
                    await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                try:
                    for fn in reversed(self.shutdown_hooks):
                        result = fn()
                        if inspect.isawaitable(result):
                            await t.cast(t.Awaitable, result)
                except Exception as exc:
                    await send({"type": "lifespan.shutdown.failed", "message": str(exc)})
                else:
                    await send({"type": "lifespan.shutdown.complete"})
                return


# ----------------------------
# Helpers
# ----------------------------


def jsonify(data: t.Any, status: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(data, status=status, headers=headers)


def text(s: str, status: int = 200, headers: dict[str, str] | None = None) -> PlainTextResponse:
    return PlainTextResponse(s, status=status, headers=headers)


def html(s: str, status: int = 200, headers: dict[str, str] | None = None) -> HTMLResponse:
    return HTMLResponse(s, status=status, headers=headers)


def redirect(location: str, status: int = 302, *, headers: dict[str, str] | None = None) -> Response:
    h = dict(headers or {})
    h["location"] = location
    return Response(b"", status=status, headers=h)


def clear_client_storage(
    *,
    cookies: t.Iterable[str] = (),
    status: int = 204,
    headers: dict[str, str] | None = None,
) -> Response:
    """Ask browsers to clear caches/storage and expire selected cookies.

    Browser JavaScript localStorage cannot be deleted by a server directly;
    ``Clear-Site-Data`` is the HTTP-level mechanism for this request.
    """
    h = dict(headers or {})
    h.setdefault("cache-control", "no-store")
    h.setdefault("clear-site-data", '"cache", "storage"')
    raw = [("set-cookie", f"{name}=; Max-Age=0; Path=/; HttpOnly") for name in cookies]
    return Response(b"", status=status, headers=h, raw_headers=raw)


def query_result(
    data: t.Any,
    *,
    content_location: str | None = None,
    cache_seconds: int | None = None,
) -> JSONResponse:
    """Return a cache-aware result for a QUERY endpoint."""
    headers: dict[str, str] = {}
    if content_location is not None:
        headers["content-location"] = content_location
    if cache_seconds is not None:
        headers["cache-control"] = f"public, max-age={int(cache_seconds)}"
    return JSONResponse(data, headers=headers)


def stream(
    body_iter: t.AsyncIterable[t.Union[str, bytes, bytearray]] | t.Iterable[t.Union[str, bytes, bytearray]],
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    content_type: str | None = "application/octet-stream",
) -> StreamingResponse:
    return StreamingResponse(body_iter, status=status, headers=headers, content_type=content_type)


def send_file(
    path: str,
    *,
    req: Request | None = None,
    status: int = 200,
    headers: dict[str, str] | None = None,
    download_name: str | None = None,
    cache_seconds: int | None = 3600,
) -> FileHandler:
    """Build a lazy file handler that can be returned or registered directly."""
    return FileHandler(
        path,
        req=req,
        status=status,
        headers=headers,
        download_name=download_name,
        cache_seconds=cache_seconds,
    )


def static(
    root: str,
    *,
    url_prefix: str = "/static",
    cache_seconds: int | None = 3600,
) -> Router:
    """Create a router that serves files under root at url_prefix.

    Example:
        app.mount("", static("./public"))
        # GET /static/app.js -> ./public/app.js
    """

    r = Router()

    @r.get(url_prefix + "/<path:path>", name="static")
    def _static(path: str):
        req = request()
        full = _safe_join(root, path)
        if not os.path.exists(full) or not os.path.isfile(full):
            raise NotFound()
        return send_file(full, req=req, cache_seconds=cache_seconds)

    return r


# ----------------------------
# Built-in middleware
# ----------------------------


def logger_middleware(*, print_fn=print) -> Middleware:
    async def _mw(req: Request, call_next):
        loop = asyncio.get_event_loop()
        start = loop.time()
        resp = await call_next()
        dur_ms = (loop.time() - start) * 1000
        print_fn(f"[night] {req.method} {req.path} -> {resp.status} ({dur_ms:.1f}ms)")
        return resp

    return _mw


def cors_middleware(
    *,
    allow_origin: str = "*",
    allow_methods: str = "GET,POST,PUT,DELETE,OPTIONS",
    allow_headers: str = "*",
) -> Middleware:
    async def _mw(req: Request, call_next):
        if req.method == "OPTIONS":
            return Response(
                b"",
                status=204,
                headers={
                    "access-control-allow-origin": allow_origin,
                    "access-control-allow-methods": allow_methods,
                    "access-control-allow-headers": allow_headers,
                },
            )
        resp = await call_next()
        resp.headers.setdefault("access-control-allow-origin", allow_origin)
        resp.headers.setdefault("access-control-allow-methods", allow_methods)
        resp.headers.setdefault("access-control-allow-headers", allow_headers)
        return resp

    return _mw


# ----------------------------
# Example usage
# ----------------------------


def create_app(debug: bool = False) -> Night:
    app = Night(debug=debug)

    # app.use(logger_middleware())

    @app.before_request
    def _add_req_id(req: Request):
        # Example of a before_request hook. Add a simple request id header.
        req.state["request_id"] = os.urandom(8).hex()
        return None

    @app.after_request
    def _add_server_header(req: Request, resp: Response):
        resp.headers.setdefault("server", "night")
        resp.headers.setdefault("x-request-id", str(req.state.get("request_id", "")))
        return resp

    @app.errorhandler(KeyError)
    def _key_error(req: Request, exc: Exception):
        # Example custom error handler.
        return jsonify({"error": "key_error", "detail": str(exc)}, status=400)

    @app.get("/", name="index")
    async def index(req: Request):
        return html(
            """<!doctype html><html><head><meta charset='utf-8'><title>night</title></head>
<body><h1>night</h1><p>It works.</p><p><a href='/health'>health</a></p></body></html>"""
        )

    @app.get("/health", name="health")
    def health():
        return {"ok": True, "ts": _dt.datetime.now().isoformat()}

    @app.get("/hello/<name>", name="hello")
    def hello(name: str):
        # Demonstrate query params: /hello/bob?title=Mr
        q = request().query
        title = q.get("title")
        if isinstance(title, list):
            title = title[0] if title else None
        if title:
            return {"hello": f"{title} {name}"}
        return {"hello": name}

    @app.get("/links", name="links")
    def links():
        return {
            "index": app.url_for("index"),
            "hello": app.url_for("hello", name="night", title="Captain"),
        }

    @app.post("/echo", name="echo")
    async def echo(req: Request):
        data = await req.json()
        return jsonify({"you_sent": data, "cookies": req.cookies, "client": req.client, "url": req.url})

    @app.get("/stream", name="stream")
    async def stream_demo(req: Request):
        async def gen():
            for i in range(5):
                yield f"chunk {i}\n"
                await asyncio.sleep(0.05)

        return StreamingResponse(gen(), content_type="text/plain; charset=utf-8")

    # Mount a static router example if ./public exists.
    pub = os.path.join(os.path.dirname(__file__), "public")
    if os.path.isdir(pub):
        app.mount("", static(pub))

    return app


# ASGI entrypoint convention: `app`
app = create_app(debug=bool(os.environ.get("NIGHT_DEBUG")))


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="night")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("module")
    run_parser.add_argument("--host", default="127.0.0.1")
    run_parser.add_argument("--port", type=int, default=8000)
    sub.add_parser("routes")
    sub.add_parser("shell")
    args = parser.parse_args(argv)

    if args.command == "routes":
        for route in app.routes:
            print(f"{','.join(sorted(route.methods)):20} {route.raw_path}")
        for route in app.websocket_routes:
            print(f"WEBSOCKET             {route.raw_path}")
        return 0
    if args.command in {"run", "shell"}:
        namespace = runpy.run_path(args.module) if args.command == "run" else globals()
        target = namespace.get("app", app)
        if args.command == "shell":
            import code
            code.interact(local={"app": target, **namespace})
            return 0
        import uvicorn
        run_options: dict[str, t.Any] = {}
        if bool(getattr(target, "_fast_mode", False)):
            if importlib.util.find_spec("uvloop") is not None:
                run_options["loop"] = "uvloop"
            if importlib.util.find_spec("httptools") is not None:
                run_options["http"] = "httptools"
            if importlib.util.find_spec("websockets") is not None:
                run_options["ws"] = "websockets"
        uvicorn.run(target, host=args.host, port=args.port, **run_options)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(cli(sys.argv[1:]))
