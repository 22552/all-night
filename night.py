#!/usr/bin/env python3
"""night.py - a tiny, single-file Flask-like ASGI web framework.

This module intentionally evolves over time.

Goals
- Single file.
- Flask-ish decorator routing.
- ASGI 3.0 app callable.
- Minimal but practical: request/response, query, path params, JSON, middleware.

This revision adds:
- Query params parsing and cookie parsing.
- URL generation (url_for) and named routes.
- Before/after request hooks.
- Error handlers (@app.errorhandler).
- Streaming responses.
- Static files helper with safe path join.
- Blueprint-like router mounting via app.mount(prefix, router).
- Request.state (dict-like) and app.state for shared state.
- Request.client, Request.url, and robust header access.
- 304 / ETag / If-Modified-Since for FileResponse.
- HEAD support (auto) and OPTIONS auto-response.

Dependencies: none (optional uvicorn for running).
"""

from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import datetime as _dt
import email.utils
import hashlib
import hmac
import inspect
import json
import mimetypes
import os
import re
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
    if not qs:
        return {}
    parsed = urllib.parse.parse_qs(qs.decode("latin-1"), keep_blank_values=True)
    out: dict[str, t.Union[str, list[str]]] = {}
    for k, vals in parsed.items():
        out[k] = vals[0] if len(vals) == 1 else vals
    return out


def _parse_cookies(cookie_header: str | None) -> dict[str, str]:
    if not cookie_header:
        return {}
    cookies: dict[str, str] = {}
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if not k:
            continue
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            v = v[1:-1]
        try:
            v = urllib.parse.unquote(v)
        except Exception:
            pass
        cookies[k] = v
    return cookies


def _safe_join(root: str, path: str) -> str:
    root_abs = os.path.abspath(root)
    target = os.path.abspath(os.path.join(root_abs, path.lstrip("/")))
    if os.path.commonpath([root_abs, target]) != root_abs:
        raise HTTPError(403, "Forbidden")
    return target


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
    pass


class Database:
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
        if typ is bool and not isinstance(value, bool): raise ValueError
        if typ is int and isinstance(value, bool): raise ValueError
        if typ in (int, float, str, bool) and not isinstance(value, typ): value = typ(value)
    except (TypeError, ValueError):
        errors.append({"field": field, "message": f"Expected {getattr(typ, '__name__', str(typ))}"})
    return value


def _validate_dataclass(model: type, value: t.Any, errors: list[dict[str, str]] | None = None, prefix: str = "") -> t.Any:
    errors = errors if errors is not None else []
    error_count = len(errors)
    if not dataclasses.is_dataclass(model) or not isinstance(value, dict):
        errors.append({"field": prefix or "body", "message": "Expected an object"})
        if prefix: return value
        raise ValidationError(errors)
    hints = t.get_type_hints(model)
    result: dict[str, t.Any] = {}
    for field in dataclasses.fields(model):
        name = f"{prefix}.{field.name}" if prefix else field.name
        if field.name not in value:
            if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING: continue
            errors.append({"field": name, "message": "Field is required"})
            continue
        result[field.name] = _validate_value(value[field.name], hints.get(field.name, field.type), name, errors)
    if not prefix and errors: raise ValidationError(errors)
    if prefix and len(errors) > error_count: return value
    return model(**result)


def _dataclass_schema(model: type) -> dict[str, t.Any]:
    primitive = {str: "string", int: "integer", float: "number", bool: "boolean"}
    if not dataclasses.is_dataclass(model): return {"type": "object"}
    properties, required = {}, []
    for field in dataclasses.fields(model):
        typ = t.get_type_hints(model).get(field.name, field.type)
        origin, args = t.get_origin(typ), t.get_args(typ)
        nullable = origin in (t.Union, types.UnionType) and type(None) in args
        if nullable: typ = next(item for item in args if item is not type(None))
        if t.get_origin(typ) is list: schema = {"type": "array", "items": _dataclass_schema(t.get_args(typ)[0])}
        elif dataclasses.is_dataclass(typ): schema = _dataclass_schema(typ)
        else: schema = {"type": primitive.get(typ, "object")}
        if nullable: schema["type"] = [schema.get("type", "object"), "null"]
        properties[field.name] = schema
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING: required.append(field.name)
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
    if req.method not in {"POST", "PUT", "PATCH", "DELETE", "QUERY"}: return
    supplied = req.header("x-csrf-token")
    if not supplied and (req.header("content-type") or "").split(";", 1)[0].lower() in {"application/x-www-form-urlencoded", "multipart/form-data"}:
        supplied = (await req.form()).get("csrf_token")
    expected = session().get("_csrf_token")
    if not isinstance(supplied, str) or not isinstance(expected, str) or not hmac.compare_digest(supplied, expected):
        raise HTTPError(403, "CSRF validation failed")


def csrf_middleware() -> Middleware:
    async def middleware(req: Request, call_next: t.Callable[[], t.Awaitable[Response]]) -> Response:
        await csrf_protect(req)
        return await call_next()
    return middleware


@dataclasses.dataclass(slots=True)
class Request:
    scope: dict
    receive: t.Callable
    send: t.Callable
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
    def method(self) -> str: return (self.scope.get("method") or "GET").upper()
    @property
    def path(self) -> str: return self.scope.get("path") or "/"
    @property
    def query_string(self) -> bytes: return self.scope.get("query_string") or b""
    @property
    def query(self) -> dict[str, t.Union[str, list[str]]]:
        if self._query is None: self._query = _parse_query(self.query_string)
        return self._query
    @property
    def headers(self) -> dict[str, str]:
        if self._headers is not None: return self._headers
        hs = {}
        for k, v in self.scope.get("headers") or []: hs[k.decode("latin-1").lower()] = v.decode("latin-1")
        self._headers = hs
        return hs
    def header(self, name: str, default: str | None = None) -> str | None:
        key = name.lower()
        if self._headers is not None: return self._headers.get(key, default)
        if key in self._header_cache:
            value = self._header_cache[key]
            return default if value is None else value
        target = key.encode("latin-1")
        value = None
        for raw_name, raw_value in reversed(self.scope.get("headers") or ()):
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
    def trace_headers(self) -> dict[str, str]: return {"traceparent": f"00-{self.trace_id}-{self.span_id}-01"}
    @property
    def cookies(self) -> dict[str, str]:
        if self._cookies is None: self._cookies = _parse_cookies(self.header("cookie"))
        return self._cookies
    @property
    def client(self) -> tuple[str, int] | None:
        c = self.scope.get("client")
        if not c: return None
        try:
            host, port = c
            return str(host), int(port)
        except Exception: return None
    @property
    def info(self):
        from night_request_info import from_scope
        return from_scope(self.scope)
    @property
    def client_ip(self) -> str | None: return self.info.client_ip
    @property
    def user_agent(self) -> str | None: return self.info.user_agent
    @property
    def country(self) -> str | None: return self.info.country
    @property
    def request_id(self) -> str | None: return self.info.request_id
    @property
    def platform(self) -> str | None: return self.info.platform
    @property
    def scheme(self) -> str: return self.scope.get("scheme") or "http"
    @property
    def host(self) -> str | None:
        h = self.header("host")
        if h: return h
        c = self.client
        return c[0] if c else None
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
        if not isinstance(st, dict): self.scope["state"] = {}
        return self.scope["state"]
    async def body(self) -> bytes:
        if self._body is not None: return self._body
        body = bytearray()
        content_length = self.header("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_body_size: raise HTTPError(413, "Request body too large")
        more = True
        while more:
            event = await self.receive()
            if event["type"] != "http.request": continue
            body += event.get("body", b"")
            if len(body) > self.max_body_size: raise HTTPError(413, "Request body too large")
            more = event.get("more_body", False)
        self._body = bytes(body)
        return self._body
    async def text(self, encoding: str = "utf-8") -> str: return (await self.body()).decode(encoding, errors="replace")
    async def json(self) -> t.Any:
        if self._json_loaded: return self._json
        b = await self.body()
        self._json = None if not b else json.loads(b.decode("utf-8"))
        self._json_loaded = True
        return self._json
    async def form(self) -> "QueryDict":
        if "_form" in self.scope: return self.scope["_form"]
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
        message = BytesParser(policy=policy.default).parsebytes((f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n").encode() + body)
        fields: dict[str, list[str]] = {}
        files: dict[str, UploadFile] = {}
        for part in message.iter_parts():
            disposition = part.get_content_disposition()
            name = part.get_param("name", header="content-disposition")
            if disposition != "form-data" or not name: continue
            data = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if filename:
                if len(data) > self.max_body_size: raise HTTPError(413, "Uploaded file too large")
                files[name] = UploadFile(filename, part.get_content_type(), data)
            else:
                fields.setdefault(name, []).append(data.decode(part.get_content_charset() or "utf-8", errors="replace"))
        return QueryDict(fields), files


def session() -> dict[str, t.Any]:
    req = request()
    secret = req.scope.get("session_secret")
    if not secret: raise RuntimeError("Session requires secret_key")
    if "_session" not in req.scope:
        raw = req.cookies.get("night_session")
        data = {}
        if raw and secret and "." in raw:
            encoded, signature = raw.rsplit(".", 1)
            expected = hmac.new(secret, encoded.encode(), hashlib.sha256).hexdigest()
            if hmac.compare_digest(signature, expected):
                try: data = json.loads(base64.urlsafe_b64decode(encoded + "=="))
                except Exception: data = {}
        req.scope["_session"] = data if isinstance(data, dict) else {}
        req.scope["_session_original"] = json.dumps(req.scope["_session"], sort_keys=True)
    return req.scope["_session"]


def flash(message: str, category: str = "message"): session().setdefault("_flashes", []).append([category, message])
def get_flashed_messages(*, with_categories: bool = False) -> list[t.Any]:
    values = session().pop("_flashes", [])
    return values if with_categories else [message for _, message in values]
def session_clear():
    req = request(); req.scope["_session"] = {}; req.scope["_session_regenerated"] = True
def session_regenerate():
    data = dict(session()); data.pop("_nonce", None); data["_nonce"] = os.urandom(16).hex(); request().scope["_session"] = data; request().scope["_session_regenerated"] = True


class QueryDict(dict[str, list[str]]):
    def __init__(self, values: t.Mapping[str, t.Any] | None = None): super().__init__({k: list(v) if isinstance(v, list) else [str(v)] for k, v in (values or {}).items()})
    def get(self, key: str, default: t.Any = None):
        values = super().get(key); return values[-1] if values else default
    def getlist(self, key: str) -> list[str]: return list(super().get(key, []))


@dataclasses.dataclass
class UploadFile:
    filename: str
    content_type: str | None
    data: t.Any
    def __post_init__(self):
        if isinstance(self.data, bytes):
            spool = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b"); spool.write(self.data); spool.seek(0); self.data = spool
    async def read(self) -> bytes: self.data.seek(0); return self.data.read()
    def save(self, path: str):
        self.data.seek(0)
        with open(path, "wb") as f: f.write(self.data.read())


class CSSRegistry:
    def __init__(self): self.rules=[]; self.variables={}; self.keyframes={}
    def add(self, rules): self.rules.append(rules)
    def add_variables(self, variables): self.variables.update(variables)
    def add_keyframes(self, name, frames): self.keyframes[name] = frames
    def _decl(self, key, value, minify):
        prop = re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), key); return f"{prop}:{value}" if minify else f"  {prop}: {value};"
    def _render_rules(self, selector, values, parent, minify):
        current = selector if not parent else ", ".join(s.replace("&", p) if "&" in s else f"{p} {s}" for p in parent.split(", ") for s in selector.split(", "))
        declarations, nested = [], []
        for key, value in values.items(): (nested if isinstance(value, dict) else declarations).append((key, value) if isinstance(value, dict) else self._decl(key, value, minify))
        out=[]
        if declarations: out.append(current + ("{"+";".join(x.removesuffix(";") for x in declarations)+"}" if minify else " {\n"+"\n".join(declarations)+"\n}"))
        for child, child_values in nested: out.extend(self._render_rules(child, child_values, current, minify))
        return out
    def render(self, *, minify=False):
        chunks=[]
        if self.variables: chunks.extend(self._render_rules(":root", {f"--{k.lstrip('-')}":v for k,v in self.variables.items()}, None, minify))
        for rules in self.rules:
            for selector, values in rules.items(): chunks.extend(self._render_rules(selector, values, None, minify))
        return ("" if minify else "\n\n").join(chunks) + ("" if minify else "\n")


class WebSocket:
    def __init__(self, scope, receive, send): self.scope=scope; self.receive=receive; self.send=send
    @property
    def path(self): return self.scope.get("path") or "/"
    async def accept(self, subprotocol=None):
        event={"type":"websocket.accept"};
        if subprotocol: event["subprotocol"]=subprotocol
        await self.send(event)
    async def receive_text(self):
        event=await self.receive()
        if event["type"]=="websocket.disconnect": raise ConnectionError("WebSocket disconnected")
        return event["text"] if event.get("text") is not None else (event.get("bytes") or b"").decode("utf-8",errors="replace")
    async def send_text(self,data): await self.send({"type":"websocket.send","text":str(data)})
    async def send_bytes(self,data): await self.send({"type":"websocket.send","bytes":bytes(data)})
    async def receive_json(self): return json.loads(await self.receive_text())
    async def send_json(self,data): await self.send_text(json.dumps(data,ensure_ascii=False,separators=(",",":")))
    async def close(self,code=1000,reason=""):
        event={"type":"websocket.close","code":int(code)}
        if reason: event["reason"]=reason
        await self.send(event)


class Response:
    def __init__(self,body: t.Union[str,bytes,bytearray]=b"",status=200,headers=None,content_type=None,raw_headers=None):
        self.status=int(status); self.body=_to_bytes(body); self.headers={k.lower():v for k,v in (headers or {}).items()}; self.raw_headers=list(raw_headers or ())
        if content_type is not None: self.headers["content-type"]=content_type
        if "date" not in self.headers: self.headers["date"]=_cached_http_date()
        if "content-length" not in self.headers: self.headers["content-length"]=str(len(self.body))
    def asgi_headers(self):
        normal=[(k,v) for k,v in self.headers.items() if k!="set-cookie"]; return [(k.encode("latin-1"),v.encode("latin-1")) for k,v in normal+self.raw_headers]
    def add_header(self,name,value): self.raw_headers.append((name.lower(),value))
    def set_cookie(self,key,value="",*,max_age=None,expires=None,path="/",domain=None,secure=False,httponly=False,samesite=None):
        parts=[f"{key}={urllib.parse.quote(str(value),safe='')}"]
        if max_age is not None: parts.append(f"Max-Age={int(max_age)}")
        if expires is not None: parts.append(f"Expires={expires}")
        if path: parts.append(f"Path={path}")
        if domain: parts.append(f"Domain={domain}")
        if secure: parts.append("Secure")
        if httponly: parts.append("HttpOnly")
        if samesite: parts.append(f"SameSite={samesite}")
        self.add_header("set-cookie","; ".join(parts))
    async def __call__(self,scope,receive,send): await send({"type":"http.response.start","status":self.status,"headers":self.asgi_headers()}); await send({"type":"http.response.body","body":self.body,"more_body":False})

class TestResponse:
    def __init__(self,status_code,headers,body): self.status_code=status_code; self.headers=headers; self.data=body
    def get_json(self): return json.loads(self.data.decode("utf-8"))
    @property
    def text(self): return self.data.decode("utf-8",errors="replace")

class TestClient:
    def __init__(self,app): self.app=app; self.cookies={}; self._runner=None
    def _run(self,coro):
        if self._runner is None: self._runner=asyncio.Runner()
        return self._runner.run(coro)
    def close(self):
        runner,self._runner=self._runner,None
        if runner is not None: runner.close()
    def __enter__(self): return self
    def __exit__(self,exc_type,exc,tb): self.close()
    def request(self,method,path,*,data=None,headers=None):
        async def run():
            sent=[]; body=data.encode() if isinstance(data,str) else (data or b""); parsed=urllib.parse.urlsplit(path); hs=[(k.lower().encode(),v.encode()) for k,v in (headers or {}).items()]
            if self.cookies: hs.append((b"cookie","; ".join(f"{k}={v}" for k,v in self.cookies.items()).encode()))
            if body and not any(k==b"content-length" for k,_ in hs): hs.append((b"content-length",str(len(body)).encode()))
            events=[{"type":"http.request","body":body,"more_body":False}]
            async def receive(): return events.pop(0) if events else {"type":"http.disconnect"}
            async def send(event): sent.append(event)
            scope={"type":"http","method":method.upper(),"path":parsed.path or "/","query_string":parsed.query.encode(),"headers":hs}
            await self.app(scope,receive,send); start=next(e for e in sent if e["type"]=="http.response.start"); chunks=[e.get("body",b"") for e in sent if e["type"]=="http.response.body"]
            return TestResponse(start["status"],{k.decode():v.decode() for k,v in start["headers"]},b"".join(chunks))
        return self._run(run())
    def get(self,path,**kwargs): return self.request("GET",path,**kwargs)
    def post(self,path,**kwargs): return self.request("POST",path,**kwargs)
    def query(self,path,**kwargs): return self.request("QUERY",path,**kwargs)

class StreamingResponse(Response):
    def __init__(self,body_iter,status=200,headers=None,content_type="application/octet-stream"):
        self.status=int(status); self._body_iter=body_iter; self.headers={k.lower():v for k,v in (headers or {}).items()}; self.raw_headers=[]; self.body=b""
        if content_type is not None: self.headers.setdefault("content-type",content_type)
        if "date" not in self.headers: self.headers["date"]=_cached_http_date()
    async def __call__(self,scope,receive,send):
        await send({"type":"http.response.start","status":self.status,"headers":self.asgi_headers()}); it=self._body_iter
        if hasattr(it,"__aiter__"):
            async for chunk in t.cast(t.AsyncIterable,it): await send({"type":"http.response.body","body":_to_bytes(chunk),"more_body":True})
        else:
            for chunk in t.cast(t.Iterable,it): await send({"type":"http.response.body","body":_to_bytes(chunk),"more_body":True})
        await send({"type":"http.response.body","body":b"","more_body":False})

def _format_sse(item):
    if not isinstance(item,dict): item={"data":item}
    lines=[]
    for key in ("id","event","retry"):
        if item.get(key) is not None: lines.append(f"{key}: {item[key]}")
    lines.extend(f"data: {line}" for line in str(item.get("data","")).splitlines() or [""])
    return "\n".join(lines)+"\n\n"

def sse(body_iter,*,status=200,headers=None):
    async def encode_async():
        async for item in t.cast(t.AsyncIterable,body_iter): yield _format_sse(item)
    def encode_sync():
        for item in t.cast(t.Iterable,body_iter): yield _format_sse(item)
    source=encode_async() if hasattr(body_iter,"__aiter__") else encode_sync(); h=dict(headers or {}); h.setdefault("cache-control","no-cache"); h.setdefault("connection","keep-alive")
    return StreamingResponse(source,status=status,headers=h,content_type="text/event-stream")

class JSONResponse(Response):
    def __init__(self,data,status=200,headers=None,*,dumps=json.dumps):
        encoded=dumps(data,ensure_ascii=False,separators=(",",":")) if dumps is json.dumps else dumps(data); body=encoded if isinstance(encoded,bytes) else str(encoded).encode("utf-8"); h=dict(headers or {}); h.setdefault("content-type","application/json; charset=utf-8"); super().__init__(body=body,status=status,headers=h)
class PlainTextResponse(Response):
    def __init__(self,text,status=200,headers=None): h=dict(headers or {}); h.setdefault("content-type","text/plain; charset=utf-8"); super().__init__(body=text,status=status,headers=h)
class HTMLResponse(Response):
    def __init__(self,html,status=200,headers=None): h=dict(headers or {}); h.setdefault("content-type","text/html; charset=utf-8"); super().__init__(body=html,status=status,headers=h)
class FileResponse(Response):
    def __init__(self,path,req=None,status=200,headers=None,download_name=None,cache_seconds=3600):
        st=os.stat(path); mtime=_dt.datetime.fromtimestamp(st.st_mtime,tz=_dt.timezone.utc); etag='W/"%s"'%hashlib.sha256((str(st.st_size)+":"+str(int(st.st_mtime))).encode()).hexdigest()[:16]; h=dict(headers or {}); h.setdefault("content-type",_guess_content_type(path)); h.setdefault("etag",etag); h.setdefault("last-modified",_http_date(mtime));
        if download_name: h.setdefault("content-disposition",f'attachment; filename="{download_name}"')
        if cache_seconds is not None: h.setdefault("cache-control",f"public, max-age={int(cache_seconds)}")
        with open(path,"rb") as f: data=f.read()
        super().__init__(body=data,status=status,headers=h)

_converter_patterns={"str":r"[^/]+","int":r"\d+","path":r".+"}
@dataclasses.dataclass
class Route:
    methods:set[str]; pattern:re.Pattern; param_names:list[str]; endpoint:t.Callable; raw_path:str; name:str|None=None; signature:inspect.Signature|None=dataclasses.field(default=None,init=False); body_model:type|None=None
    def __post_init__(self):
        try: self.signature=inspect.signature(self.endpoint); setattr(self.endpoint,"__night_signature__",self.signature)
        except Exception: self.signature=None

def compile_path(path):
    param_names=[]
    def repl(m):
        inner=m.group(1); conv,name=(inner.split(":",1) if ":" in inner else ("str",inner)); conv=conv if conv in _converter_patterns else "str"; param_names.append(name); return f"(?P<{name}>{_converter_patterns[conv]})"
    regex=re.sub(r"<([^>]+)>",repl,path); return re.compile("^"+regex.rstrip("/")+"/?$"),param_names

def _format_path(path_template,params):
    def repl(m):
        inner=m.group(1); name=inner.split(":",1)[1] if ":" in inner else inner
        if name not in params: raise KeyError(name)
        return urllib.parse.quote(str(params[name]),safe="")
    return re.sub(r"<([^>]+)>",repl,path_template)

_current_request: contextvars.ContextVar[Request|None]=contextvars.ContextVar("night_request",default=None)
def request():
    r=_current_request.get()
    if r is None: raise RuntimeError("No active request in context")
    return r
Middleware=t.Callable[[Request,t.Callable[[],t.Awaitable[Response]]],t.Awaitable[Response]]
BeforeHook=t.Callable[[Request],t.Awaitable[t.Optional[Response]]|t.Optional[Response]]
AfterHook=t.Callable[[Request,Response],t.Awaitable[Response]|Response]
ErrorHandler=t.Callable[[Request,Exception],t.Awaitable[Response]|Response]

class Extension:
    def init_app(self,app:"Night",**config): raise NotImplementedError
class GraphQLExtension(Extension):
    name="graphql"
    def __init__(self,schema,*,path="/graphql"): self.schema=schema; self.path=path
    def init_app(self,app,**config):
        try: from graphql import graphql
        except ImportError as exc: raise RuntimeError("GraphQLExtension requires: pip install graphql-core") from exc
        async def endpoint(req):
            payload=await req.json() if req.method in {"POST","QUERY"} else None; query=(payload or {}).get("query","") if isinstance(payload,dict) else req.query.get("query",""); result=graphql(self.schema,query)
            if inspect.isawaitable(result): result=await result
            return JSONResponse({"data":result.data} if result.data is not None else {"errors":[{"message":str(e)} for e in result.errors or []]})
        app.route(self.path,methods=("GET","POST","QUERY"),name="graphql")(endpoint)

class Router:
    def __init__(self): self.routes=[]
    def route(self,path,methods=("GET",),*,name=None,body=None):
        methods_set={m.upper() for m in methods}
        def decorator(fn):
            pattern,names=compile_path(path); route=Route(methods_set,pattern,names,fn,path,name,body_model=body); self.routes.append(route); hook=getattr(self,"_on_route_added",None); hook(route) if hook else None; return fn
        return decorator
    def get(self,path,*,name=None): return self.route(path,methods=("GET",),name=name)
    def post(self,path,*,name=None,body=None): return self.route(path,methods=("POST",),name=name,body=body)
    def put(self,path,*,name=None): return self.route(path,methods=("PUT",),name=name)
    def delete(self,path,*,name=None): return self.route(path,methods=("DELETE",),name=name)
    def query(self,path,*,name=None): return self.route(path,methods=("QUERY",),name=name)
    def patch(self,path,*,name=None): return self.route(path,methods=("PATCH",),name=name)
    def purge(self,path,*,name=None): return self.route(path,methods=("PURGE",),name=name)
class Blueprint(Router):
    def __init__(self,name,*,url_prefix="",setup=None): super().__init__(); self.name=name; self.url_prefix=("/"+url_prefix.strip("/")) if url_prefix else ""; self.setup=setup
    def register(self,app,*,url_prefix=None):
        prefix=self.url_prefix if url_prefix is None else url_prefix
        if self.setup is not None: self.setup(self); self.setup=None
        app.mount(prefix,self); return self

CALL_KWARGS=0; CALL_REQUEST_POSITIONAL=1; CALL_REQUEST_KEYWORD=2; ROUTE_CALL_GENERIC=0; ROUTE_CALL_DIRECT_PARAM=1; ROUTE_CALL_NOARGS=2; ROUTE_CALL_REQUEST_KEYWORD=3; ROUTE_CALL_REQUEST_POSITIONAL=4
@dataclasses.dataclass(frozen=True,slots=True)
class _EndpointPlan:
    signature:inspect.Signature|None; type_hints:dict[str,t.Any]; call_mode:int; is_coro:bool; int_params:tuple[str,...]; body_model:type|None; body_candidates:tuple[str,...]
def _compile_endpoint(fn):
    try: signature=inspect.signature(fn)
    except Exception: signature=None
    try: type_hints=t.get_type_hints(fn)
    except Exception: type_hints={}
    call_mode=CALL_KWARGS; int_params=[]; body_candidates=[]
    if signature is not None:
        params=tuple(signature.parameters.values())
        if "req" in signature.parameters: call_mode=CALL_REQUEST_KEYWORD
        elif params and (type_hints.get(params[0].name,params[0].annotation) is Request or params[0].name in {"request","req"}): call_mode=CALL_REQUEST_POSITIONAL
        for param in params:
            if type_hints.get(param.name,param.annotation) is int: int_params.append(param.name)
            if param.name not in {"req","request"}: body_candidates.append(param.name)
    return _EndpointPlan(signature,type_hints,call_mode,inspect.iscoroutinefunction(fn),tuple(int_params),getattr(fn,"__night_body_model__",None),tuple(body_candidates))

class Night(Router):
    def __init__(self,*,debug=False,max_body_size=MAX_BODY_SIZE,secret_key=None,session_secure=None,css=False,css_minify=False):
        super().__init__(); self.debug=bool(debug); self.max_body_size=int(max_body_size); self.secret_key=secret_key.encode() if isinstance(secret_key,str) else secret_key; self.session_secure=session_secure; self.css_minify=css_minify; self.styles=CSSRegistry() if css else None; self.middlewares=[]; self.before_hooks=[]; self.after_hooks=[]; self.error_handlers={}; self.state={}; self.extensions={}; self.websocket_routes=[]; self.rpc_methods={}; self.startup_hooks=[]; self.shutdown_hooks=[]; self._endpoint_plans={}; self._static_method_index={}; self._static_methods_by_path={}; self._dynamic_route_index=[]; self._dynamic_method_routes={}
    def test_client(self): return TestClient(self)
    def _on_route_added(self,route): self._endpoint_plans[route.endpoint]=_compile_endpoint(route.endpoint); self._dynamic_route_index.append(route) if "<" in route.raw_path else self._static_method_index.setdefault(next(iter(route.methods)),{}).__setitem__(route.raw_path.rstrip("/") or "/",route)
    def openapi(self): return {"openapi":"3.1.0","info":{"title":"Night API","version":"1.0.0"},"paths":{}}
    def rpc(self,name):
        def deco(fn): self.rpc_methods[name]=fn; return fn
        return deco
    async def cloudflare_rpc(self,method,args=None,kwargs=None):
        try: from workers.rpc import python_from_rpc, python_to_rpc
        except ImportError as exc: raise RuntimeError("Cloudflare RPC requires workers-runtime-sdk inside a Python Worker") from exc
        fn=self.rpc_methods.get(str(method));
        if fn is None: raise KeyError(f"Unknown Night RPC method: {method}")
        call_args=python_from_rpc(args) if args is not None else []; call_kwargs=python_from_rpc(kwargs) if kwargs is not None else {}; result=fn(*call_args,**call_kwargs); result=await result if inspect.isawaitable(result) else result; return python_to_rpc(result)
    async def cloudflare_fetch(self,request:t.Any,*,response_class:t.Any=None)->t.Any:
        try:
            if response_class is None: from workers import Response as response_class
        except ImportError as exc: raise RuntimeError("Cloudflare fetch integration requires workers-runtime-sdk") from exc
        parsed=urllib.parse.urlsplit(str(request.url)); method_value=getattr(request.method,"value",request.method); method=str(method_value).upper(); header_source=getattr(request,"headers",())
        try: header_items=list(header_source.items())
        except Exception:
            try: header_items=list(dict(header_source).items())
            except Exception: header_items=[]
        header_values={str(k).lower():str(v) for k,v in header_items}
        headers=[(k.encode("latin-1"),v.encode("latin-1")) for k,v in header_values.items()]
        cf=getattr(request,"cf",None)
        def cf_get(name,default=None):
            if cf is None: return default
            try:
                if isinstance(cf,dict): return cf.get(name,default)
                return getattr(cf,name,default)
            except Exception: return default
        edge_l4=cf_get("edgeL4")
        try: delivery_rate=edge_l4.get("deliveryRate") if isinstance(edge_l4,dict) else getattr(edge_l4,"deliveryRate",None)
        except Exception: delivery_rate=None
        info={
            "platform":"cloudflare",
            "client_ip":header_values.get("cf-connecting-ip"),
            "request_id":header_values.get("cf-ray"),
            "country":cf_get("country") or header_values.get("cf-ipcountry"),
            "city":cf_get("city"),
            "region":cf_get("region"),
            "region_code":cf_get("regionCode"),
            "postal_code":cf_get("postalCode"),
            "continent":cf_get("continent"),
            "timezone":cf_get("timezone"),
            "latitude":cf_get("latitude"),
            "longitude":cf_get("longitude"),
            "colo":cf_get("colo"),
            "asn":cf_get("asn"),
            "as_organization":cf_get("asOrganization"),
            "http_protocol":cf_get("httpProtocol"),
            "tls_version":cf_get("tlsVersion"),
            "tls_cipher":cf_get("tlsCipher"),
            "client_tcp_rtt":cf_get("clientTcpRtt"),
            "client_quic_rtt":cf_get("clientQuicRtt"),
            "delivery_rate":delivery_rate,
            "user_agent":header_values.get("user-agent"),
            "accept_language":header_values.get("accept-language"),
            "referrer":header_values.get("referer"),
        }
        info={k:v for k,v in info.items() if v not in (None,"")}
        body=b""
        if method not in {"GET","HEAD"}:
            if hasattr(request,"bytes"): body=bytes(await request.bytes())
            else:
                raw=await request.arrayBuffer()
                try: body=bytes(raw.to_py())
                except Exception: body=bytes(raw)
            if len(body)>self.max_body_size: raise HTTPError(413,"Request body too large")
        encoded_path=parsed.path or "/"; decoded_path=urllib.parse.unquote(encoded_path); scheme=parsed.scheme or "https"; port=parsed.port or (443 if scheme=="https" else 80); client=(str(info["client_ip"]),0) if info.get("client_ip") else None
        scope={"type":"http","http_version":str(info.get("http_protocol") or "1.1").replace("HTTP/",""),"method":method,"scheme":scheme,"path":decoded_path,"raw_path":encoded_path.encode("utf-8"),"query_string":parsed.query.encode("latin-1"),"headers":headers,"server":(parsed.hostname or "edge",port),"client":client,"state":{"night_request_info":info}}
        received=False
        async def receive():
            nonlocal received
            if received: return {"type":"http.request","body":b"","more_body":False}
            received=True; return {"type":"http.request","body":body,"more_body":False}
        events=[]
        async def send(event): events.append(event)
        await self(scope,receive,send); start=next((event for event in events if event.get("type")=="http.response.start"),None)
        if start is None: raise RuntimeError("Night produced no HTTP response start event")
        chunks=[event.get("body",b"") for event in events if event.get("type")=="http.response.body"]; web_headers=[(key.decode("latin-1"),value.decode("latin-1")) for key,value in start.get("headers",())]
        return response_class(b"".join(chunks),status=int(start["status"]),headers=web_headers)
    def _match_method(self,path,method):
        key=path.rstrip("/") or "/"; route=self._static_method_index.get(method,{}).get(key)
        if route: return route,{}
        for route in self.routes:
            if method in route.methods:
                m=route.pattern.match(path)
                if m: return route,m.groupdict()
        allowed=set()
        for route in self.routes:
            if route.pattern.match(path): allowed|=route.methods
        if allowed: raise MethodNotAllowed(allowed)
        raise NotFound()
    def _coerce_response(self,value):
        if type(value) in (dict,list): return JSONResponse(value)
        if type(value) is str: return PlainTextResponse(value)
        if type(value) is bytes: return Response(value)
        if value is None: return Response(b"",status=204)
        if isinstance(value,Response): return value
        return PlainTextResponse(str(value))
    async def _dispatch(self,req,path=None,method=None):
        path=req.path if path is None else path; method=req.method if method is None else method; route,params=self._match_method(path,method); req.path_params=params; fn=route.endpoint; plan=self._endpoint_plans.get(fn) or _compile_endpoint(fn); kwargs=dict(params)
        if plan.call_mode==CALL_REQUEST_KEYWORD: result=fn(req=req,**kwargs)
        elif plan.call_mode==CALL_REQUEST_POSITIONAL: result=fn(req,**kwargs)
        else: result=fn(**kwargs) if kwargs else fn()
        if inspect.isawaitable(result): result=await result
        return self._coerce_response(result)
    async def __call__(self,scope,receive,send):
        if scope.get("type")!="http": return
        req=Request(scope=scope,receive=receive,send=send,max_body_size=self.max_body_size); method=req.method; path=req.path; token=_current_request.set(req)
        try:
            try: resp=await self._dispatch(req,path,method)
            except HTTPError as he: resp=PlainTextResponse(he.detail or "Error",status=he.status)
            except Exception: resp=PlainTextResponse(traceback.format_exc() if self.debug else "Internal Server Error",status=500)
            await resp(scope,receive,send)
        finally: _current_request.reset(token)
    def mount(self,prefix,router):
        prefix=("/"+prefix.strip("/")) if prefix else ""
        for r in router.routes:
            mounted_path=prefix+("/"+r.raw_path.lstrip("/")); pattern,names=compile_path(mounted_path); self.routes.append(Route(set(r.methods),pattern,names,r.endpoint,mounted_path,r.name)); self._on_route_added(self.routes[-1])
        return router
    def url_for(self,name,/,**params):
        for r in self.routes:
            if r.name==name: return _format_path(r.raw_path,params)
        raise KeyError(name)
    def websocket(self,path,*,name=None):
        def deco(fn): self.websocket_routes.append(Route({"WEBSOCKET"},*compile_path(path),fn,path,name)); return fn
        return deco
    def use(self,middleware): self.middlewares.append(middleware); return middleware
    def before_request(self,fn): self.before_hooks.append(fn); return fn
    def after_request(self,fn): self.after_hooks.append(fn); return fn
    def errorhandler(self,exc_type):
        def deco(fn): self.error_handlers[exc_type]=fn; return fn
        return deco
    def register_extension(self,extension,*,name=None,**config):
        key=name or getattr(extension,"name",None) or extension.__class__.__name__.lower(); extension.init_app(self,**config) if hasattr(extension,"init_app") else extension(self,**config); self.extensions[key]=extension; return extension
    def register_blueprint(self,blueprint,*,url_prefix=None): return blueprint.register(self,url_prefix=url_prefix)
    def on_startup(self,fn): self.startup_hooks.append(fn); return fn
    def on_shutdown(self,fn): self.shutdown_hooks.append(fn); return fn


def jsonify(data,status=200,headers=None): return JSONResponse(data,status=status,headers=headers)
def text(s,status=200,headers=None): return PlainTextResponse(s,status=status,headers=headers)
def html(s,status=200,headers=None): return HTMLResponse(s,status=status,headers=headers)
def redirect(location,status=302,*,headers=None): h=dict(headers or {}); h["location"]=location; return Response(b"",status=status,headers=h)
def clear_client_storage(*,cookies=(),status=204,headers=None):
    h=dict(headers or {}); h.setdefault("cache-control","no-store"); h.setdefault("clear-site-data",'"cache", "storage"'); raw=[("set-cookie",f"{name}=; Max-Age=0; Path=/; HttpOnly") for name in cookies]; return Response(b"",status=status,headers=h,raw_headers=raw)
def query_result(data,*,content_location=None,cache_seconds=None):
    headers={}
    if content_location is not None: headers["content-location"]=content_location
    if cache_seconds is not None: headers["cache-control"]=f"public, max-age={int(cache_seconds)}"
    return JSONResponse(data,headers=headers)
def stream(body_iter,*,status=200,headers=None,content_type="application/octet-stream"): return StreamingResponse(body_iter,status=status,headers=headers,content_type=content_type)
def send_file(path,*,req=None,status=200,headers=None,download_name=None,cache_seconds=3600): return FileResponse(path,req=req,status=status,headers=headers,download_name=download_name,cache_seconds=cache_seconds)
def static(root,*,url_prefix="/static",cache_seconds=3600):
    r=Router()
    @r.get(url_prefix+"/<path:path>",name="static")
    def _static(path):
        req=request(); full=_safe_join(root,path)
        if not os.path.exists(full) or not os.path.isfile(full): raise NotFound()
        return FileResponse(full,req=req,cache_seconds=cache_seconds)
    return r

def logger_middleware(*,print_fn=print):
    async def _mw(req,call_next):
        start=asyncio.get_event_loop().time(); resp=await call_next(); print_fn(f"[night] {req.method} {req.path} -> {resp.status} ({(asyncio.get_event_loop().time()-start)*1000:.1f}ms)"); return resp
    return _mw
def cors_middleware(*,allow_origin="*",allow_methods="GET,POST,PUT,DELETE,OPTIONS",allow_headers="*"):
    async def _mw(req,call_next):
        resp=await call_next(); resp.headers.setdefault("access-control-allow-origin",allow_origin); resp.headers.setdefault("access-control-allow-methods",allow_methods); resp.headers.setdefault("access-control-allow-headers",allow_headers); return resp
    return _mw

def create_app(debug=False):
    app=Night(debug=debug)
    @app.get("/",name="index")
    def index(): return {"ok":True}
    @app.get("/health",name="health")
    def health(): return {"ok":True,"ts":_dt.datetime.now().isoformat()}
    return app

app=create_app(debug=bool(os.environ.get("NIGHT_DEBUG")))
def cli(argv=None):
    parser=argparse.ArgumentParser(prog="night"); sub=parser.add_subparsers(dest="command",required=True); run_parser=sub.add_parser("run"); run_parser.add_argument("module"); run_parser.add_argument("--host",default="127.0.0.1"); run_parser.add_argument("--port",type=int,default=8000); sub.add_parser("routes"); sub.add_parser("shell"); args=parser.parse_args(argv)
    if args.command=="routes":
        for route in app.routes: print(f"{','.join(sorted(route.methods)):20} {route.raw_path}")
        return 0
    if args.command=="run":
        namespace=runpy.run_path(args.module); target=namespace.get("app",app); import uvicorn; uvicorn.run(target,host=args.host,port=args.port); return 0
    return 2
if __name__=="__main__": raise SystemExit(cli(sys.argv[1:]))
