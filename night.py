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
        if len(vals) == 1:
            out[k] = vals[0]
        else:
            out[k] = vals
    return out


def _parse_cookies(cookie_header: str | None) -> dict[str, str]:
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
    """Raised for invalid Night ORM model definitions or operations."""


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
        message = BytesParser(policy=policy.default).parsebytes((f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n").encode() + body)
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

    def add(self, rules: dict[str, t.Any]): self.rules.append(rules)
    def add_variables(self, variables: dict[str, t.Any]): self.variables.update(variables)
    def add_keyframes(self, name: str, frames: dict[str, dict[str, t.Any]]): self.keyframes[name] = frames
    def _decl(self, key: str, value: t.Any, minify: bool) -> str:
        prop = re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), key)
        return f"{prop}:{value}" if minify else f"  {prop}: {value};"
    def _render_rules(self, selector: str, values: dict[str, t.Any], parent: str | None, minify: bool) -> list[str]:
        current = selector if not parent else ", ".join(s.replace("&", p) if "&" in s else f"{p} {s}" for p in parent.split(", ") for s in selector.split(", "))
        declarations, nested = [], []
        for key, value in values.items():
            if isinstance(value, dict): nested.append((key, value))
            else: declarations.append(self._decl(key, value, minify))
        out = []
        if declarations:
            out.append(current + "{" + ";".join(x.removesuffix(";") for x in declarations) + "}" if minify else current + " {\n" + "\n".join(declarations) + "\n}")
        for child, child_values in nested:
            if child.startswith("@"):
                inner = []
                for nested_selector, nested_values in child_values.items(): inner.extend(self._render_rules(nested_selector, nested_values, None, minify))
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
    def __init__(self, scope: dict, receive, send): self.scope, self.receive, self.send = scope, receive, send
    @property
    def path(self) -> str: return self.scope.get("path") or "/"
    async def accept(self, subprotocol: str | None = None):
        event = {"type": "websocket.accept"}
        if subprotocol: event["subprotocol"] = subprotocol
        await self.send(event)
    async def receive_text(self) -> str:
        event = await self.receive()
        if event["type"] == "websocket.disconnect": raise ConnectionError("WebSocket disconnected")
        if event.get("text") is not None: return event["text"]
        return (event.get("bytes") or b"").decode("utf-8", errors="replace")
    async def send_text(self, data: str): await self.send({"type": "websocket.send", "text": str(data)})
    async def send_bytes(self, data: bytes): await self.send({"type": "websocket.send", "bytes": bytes(data)})
    async def receive_json(self) -> t.Any: return json.loads(await self.receive_text())
    async def send_json(self, data: t.Any): await self.send_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    async def close(self, code: int = 1000, reason: str = ""):
        event = {"type": "websocket.close", "code": int(code)}
        if reason: event["reason"] = reason
        await self.send(event)


class Response:
    def __init__(self, body: t.Union[str, bytes, bytearray] = b"", status: int = 200, headers: t.Mapping[str, str] | None = None, content_type: str | None = None, raw_headers: t.Iterable[tuple[str, str]] | None = None):
        self.status = int(status)
        self.body = _to_bytes(body)
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.raw_headers = list(raw_headers or ())
        if content_type is not None: self.headers["content-type"] = content_type
        if "date" not in self.headers: self.headers["date"] = _cached_http_date()
        if "content-length" not in self.headers: self.headers["content-length"] = str(len(self.body))
    def asgi_headers(self) -> list[tuple[bytes, bytes]]:
        normal = [(k, v) for k, v in self.headers.items() if k != "set-cookie"]
        return [(k.encode("latin-1"), v.encode("latin-1")) for k, v in normal + self.raw_headers]
    def add_header(self, name: str, value: str): self.raw_headers.append((name.lower(), value))
    def set_cookie(self, key: str, value: str = "", *, max_age: int | None = None, expires: str | None = None, path: str = "/", domain: str | None = None, secure: bool = False, httponly: bool = False, samesite: str | None = None):
        parts = [f"{key}={urllib.parse.quote(str(value), safe='')}"]
        if max_age is not None: parts.append(f"Max-Age={int(max_age)}")
        if expires is not None: parts.append(f"Expires={expires}")
        if path: parts.append(f"Path={path}")
        if domain: parts.append(f"Domain={domain}")
        if secure: parts.append("Secure")
        if httponly: parts.append("HttpOnly")
        if samesite: parts.append(f"SameSite={samesite}")
        self.add_header("set-cookie", "; ".join(parts))
    def delete_cookie(self, key: str, *, path: str = "/", domain: str | None = None): self.set_cookie(key, "", max_age=0, expires="Thu, 01 Jan 1970 00:00:00 GMT", path=path, domain=domain)
    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": self.status, "headers": self.asgi_headers()})
        await send({"type": "http.response.body", "body": self.body, "more_body": False})


class TestResponse:
    def __init__(self, status_code: int, headers: dict[str, str], body: bytes): self.status_code, self.headers, self.data = status_code, headers, body
    def get_json(self): return json.loads(self.data.decode("utf-8"))
    @property
    def text(self): return self.data.decode("utf-8", errors="replace")


class TestClient:
    def __init__(self, app: "Night"):
        self.app, self.cookies = app, {}
        self._runner: asyncio.Runner | None = None
    def _run(self, coro):
        if self._runner is None: self._runner = asyncio.Runner()
        return self._runner.run(coro)
    def close(self):
        runner, self._runner = self._runner, None
        if runner is not None: runner.close()
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): self.close()
    def request(self, method: str, path: str, *, data: bytes | str | None = None, headers: dict[str, str] | None = None):
        async def run():
            sent = []
            body = data.encode() if isinstance(data, str) else (data or b"")
            parsed = urllib.parse.urlsplit(path)
            hs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
            if self.cookies: hs.append((b"cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()).encode()))
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
    def __init__(self, body_iter, status: int = 200, headers: t.Mapping[str, str] | None = None, content_type: str | None = "application/octet-stream"):
        self.status = int(status)
        self._body_iter = body_iter
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        if content_type is not None: self.headers.setdefault("content-type", content_type)
        if "date" not in self.headers: self.headers["date"] = _cached_http_date()
        self.body = b""
    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": self.status, "headers": self.asgi_headers()})
        it = self._body_iter
        if hasattr(it, "__aiter__"):
            async for chunk in t.cast(t.AsyncIterable, it): await send({"type": "http.response.body", "body": _to_bytes(chunk), "more_body": True})
        else:
            for chunk in t.cast(t.Iterable, it): await send({"type": "http.response.body", "body": _to_bytes(chunk), "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})


def sse(body_iter, *, status: int = 200, headers: t.Mapping[str, str] | None = None) -> StreamingResponse:
    async def encode_async():
        async for item in t.cast(t.AsyncIterable, body_iter): yield _format_sse(item)
    def encode_sync():
        for item in t.cast(t.Iterable, body_iter): yield _format_sse(item)
    source = encode_async() if hasattr(body_iter, "__aiter__") else encode_sync()
    h = dict(headers or {})
    h.setdefault("cache-control", "no-cache")
    h.setdefault("connection", "keep-alive")
    return StreamingResponse(source, status=status, headers=h, content_type="text/event-stream")


def _format_sse(item: t.Any) -> str:
    if not isinstance(item, dict): item = {"data": item}
    lines: list[str] = []
    for key in ("id", "event", "retry"):
        if item.get(key) is not None: lines.append(f"{key}: {item[key]}")
    data = str(item.get("data", ""))
    lines.extend(f"data: {line}" for line in data.splitlines() or [""])
    return "\n".join(lines) + "\n\n"


class JSONResponse(Response):
    def __init__(self, data: t.Any, status: int = 200, headers: t.Mapping[str, str] | None = None, *, dumps: t.Callable[..., str] = json.dumps):
        encoded = dumps(data, ensure_ascii=False, separators=(",", ":")) if dumps is json.dumps else dumps(data)
        body = encoded if isinstance(encoded, bytes) else str(encoded).encode("utf-8")
        h = dict(headers or {})
        h.setdefault("content-type", "application/json; charset=utf-8")
        super().__init__(body=body, status=status, headers=h)


class PlainTextResponse(Response):
    def __init__(self, text: str, status: int = 200, headers: t.Mapping[str, str] | None = None):
        h = dict(headers or {}); h.setdefault("content-type", "text/plain; charset=utf-8"); super().__init__(body=text, status=status, headers=h)


class HTMLResponse(Response):
    def __init__(self, html: str, status: int = 200, headers: t.Mapping[str, str] | None = None):
        h = dict(headers or {}); h.setdefault("content-type", "text/html; charset=utf-8"); super().__init__(body=html, status=status, headers=h)


class FileResponse(Response):
    def __init__(self, path: str, req: Request | None = None, status: int = 200, headers: t.Mapping[str, str] | None = None, download_name: str | None = None, cache_seconds: int | None = 3600):
        st = os.stat(path)
        mtime = _dt.datetime.fromtimestamp(st.st_mtime, tz=_dt.timezone.utc)
        etag = 'W/"%s"' % hashlib.sha256((str(st.st_size) + ":" + str(int(st.st_mtime))).encode("utf-8")).hexdigest()[:16]
        h = dict(headers or {})
        h.setdefault("content-type", _guess_content_type(path)); h.setdefault("etag", etag); h.setdefault("last-modified", _http_date(mtime))
        if download_name: h.setdefault("content-disposition", f'attachment; filename="{download_name}"')
        if cache_seconds is not None: h.setdefault("cache-control", f"public, max-age={int(cache_seconds)}")
        if req is not None:
            inm = req.header("if-none-match")
            if inm and inm.strip() == etag:
                super().__init__(body=b"", status=304, headers=h); self.headers.pop("content-length", None); return
            ims = req.header("if-modified-since")
            if ims:
                dt = _parse_http_date(ims)
                if dt is not None and mtime.replace(microsecond=0) <= dt.astimezone(_dt.timezone.utc).replace(microsecond=0):
                    super().__init__(body=b"", status=304, headers=h); self.headers.pop("content-length", None); return
        with open(path, "rb") as f: data = f.read()
        super().__init__(body=data, status=status, headers=h)


_converter_patterns = {"str": r"[^/]+", "int": r"\d+", "path": r".+"}


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
            self.signature = inspect.signature(self.endpoint); setattr(self.endpoint, "__night_signature__", self.signature)
        except Exception: self.signature = None


def compile_path(path: str) -> tuple[re.Pattern, list[str]]:
    param_names: list[str] = []
    def repl(m: re.Match) -> str:
        inner = m.group(1)
        conv, name = inner.split(":", 1) if ":" in inner else ("str", inner)
        if conv not in _converter_patterns: conv = "str"
        param_names.append(name)
        return f"(?P<{name}>{_converter_patterns[conv]})"
    regex = re.sub(r"<([^>]+)>", repl, path)
    regex = "^" + regex.rstrip("/") + "/?$"
    return re.compile(regex), param_names


def _format_path(path_template: str, params: dict[str, t.Any]) -> str:
    def repl(m: re.Match) -> str:
        inner = m.group(1)
        name = inner.split(":", 1)[1] if ":" in inner else inner
        if name not in params: raise KeyError(name)
        return urllib.parse.quote(str(params[name]), safe="")
    return re.sub(r"<([^>]+)>", repl, path_template)


_current_request: contextvars.ContextVar[Request | None] = contextvars.ContextVar("night_request", default=None)
def request() -> Request:
    r = _current_request.get()
    if r is None: raise RuntimeError("No active request in context")
    return r

Middleware = t.Callable[[Request, t.Callable[[], t.Awaitable[Response]]], t.Awaitable[Response]]
BeforeHook = t.Callable[[Request], t.Awaitable[t.Optional[Response]] | t.Optional[Response]]
AfterHook = t.Callable[[Request, Response], t.Awaitable[Response] | Response]
ErrorHandler = t.Callable[[Request, Exception], t.Awaitable[Response] | Response]


class Extension:
    def init_app(self, app: "Night", **config: t.Any) -> None: raise NotImplementedError


class GraphQLExtension(Extension):
    name = "graphql"
    def __init__(self, schema: t.Any, *, path: str = "/graphql"): self.schema, self.path = schema, path
    def init_app(self, app: "Night", **config: t.Any) -> None:
        try: from graphql import graphql
        except ImportError as exc: raise RuntimeError("GraphQLExtension requires: pip install graphql-core") from exc
        async def endpoint(req: Request):
            payload = await req.json() if req.method in {"POST", "QUERY"} else None
            if payload is None:
                query = req.query.get("query", ""); variables = req.query.get("variables"); operation_name = req.query.get("operationName")
                if isinstance(variables, str) and variables:
                    try: variables = json.loads(variables)
                    except json.JSONDecodeError: return JSONResponse({"errors": [{"message": "Invalid variables JSON"}]}, status=400)
            else:
                if not isinstance(payload, dict): return JSONResponse({"errors": [{"message": "Request must be a JSON object"}]}, status=400)
                query = payload.get("query", ""); variables = payload.get("variables"); operation_name = payload.get("operationName")
            if not isinstance(query, str) or not query.strip(): return JSONResponse({"errors": [{"message": "Missing GraphQL query"}]}, status=400)
            result = graphql(self.schema, query, variable_values=variables, operation_name=operation_name)
            if inspect.isawaitable(result): result = await t.cast(t.Awaitable, result)
            output: dict[str, t.Any] = {}
            if result.data is not None: output["data"] = result.data
            if result.errors: output["errors"] = [{"message": str(error)} for error in result.errors]
            return JSONResponse(output, status=200 if not result.errors else 400)
        app.route(self.path, methods=("GET", "POST", "QUERY"), name="graphql")(endpoint)


class Router:
    def __init__(self): self.routes: list[Route] = []
    def route(self, path: str, methods: t.Iterable[str] = ("GET",), *, name: str | None = None, body: type | None = None):
        methods_set = {m.upper() for m in methods}
        def decorator(fn: t.Callable):
            pattern, names = compile_path(path)
            route = Route(methods=methods_set, pattern=pattern, param_names=names, endpoint=fn, raw_path=path, name=name, body_model=body)
            if body is not None: setattr(fn, "__night_body_model__", body)
            self.routes.append(route)
            hook = getattr(self, "_on_route_added", None)
            if hook is not None: hook(route)
            return fn
        return decorator
    def get(self, path: str, *, name: str | None = None): return self.route(path, methods=("GET",), name=name)
    def post(self, path: str, *, name: str | None = None, body: type | None = None): return self.route(path, methods=("POST",), name=name, body=body)
    def put(self, path: str, *, name: str | None = None): return self.route(path, methods=("PUT",), name=name)
    def delete(self, path: str, *, name: str | None = None): return self.route(path, methods=("DELETE",), name=name)
    def query(self, path: str, *, name: str | None = None): return self.route(path, methods=("QUERY",), name=name)
    def patch(self, path: str, *, name: str | None = None): return self.route(path, methods=("PATCH",), name=name)
    def purge(self, path: str, *, name: str | None = None): return self.route(path, methods=("PURGE",), name=name)


class Blueprint(Router):
    def __init__(self, name: str, *, url_prefix: str = "", setup: t.Callable | None = None):
        super().__init__(); self.name = name; self.url_prefix = ("/" + url_prefix.strip("/")) if url_prefix else ""; self.setup = setup
    def register(self, app: "Night", *, url_prefix: str | None = None):
        prefix = self.url_prefix if url_prefix is None else url_prefix
        if self.setup is not None: self.setup(self); self.setup = None
        app.mount(prefix, self); return self

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
        try: signature = inspect.signature(fn)
        except (TypeError, ValueError): signature = None
    try: type_hints = t.get_type_hints(fn)
    except Exception: type_hints = {}
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
            if first_type is Request or first.name in {"request", "req"}: call_mode = CALL_REQUEST_POSITIONAL
        for param in params:
            annotation = type_hints.get(param.name, param.annotation)
            if annotation is int: int_params.append(param.name)
            if param.name not in {"req", "request"}: body_candidates.append(param.name)
    return _EndpointPlan(signature=signature, type_hints=type_hints, call_mode=call_mode, is_coro=inspect.iscoroutinefunction(fn), int_params=tuple(int_params), body_model=getattr(fn, "__night_body_model__", None), body_candidates=tuple(body_candidates))


class Night(Router):
    def __init__(self, *, debug: bool = False, max_body_size: int = MAX_BODY_SIZE, secret_key: str | bytes | None = None, session_secure: bool | None = None, css: bool = False, css_minify: bool = False):
        super().__init__(); self.debug = bool(debug); self.max_body_size = int(max_body_size); self.secret_key = secret_key.encode() if isinstance(secret_key, str) else secret_key; self.session_secure = session_secure; self.css_minify = css_minify; self.styles: CSSRegistry | None = None; self._css_cache: str | None = None; self._static_route_index = {}; self._dynamic_route_index = []; self._dynamic_method_routes = {}; self._dynamic_method_matchers = {}; self._dynamic_prefix_index = {}; self._dynamic_terminal_index = {}; self._static_method_index = {}; self._static_methods_by_path = {}; self._endpoint_plans = {}
        if css: self.enable_css(minify=css_minify)
        self.middlewares = []; self.before_hooks = []; self.after_hooks = []; self.error_handlers = {}; self.state = {}; self.extensions = {}; self.websocket_routes = []; self.rpc_methods = {}; self._rpc_route_installed = False; self.startup_hooks = []; self.shutdown_hooks = []
    def test_client(self) -> TestClient: return TestClient(self)
    @staticmethod
    def _classify_route_call(route: Route, plan: _EndpointPlan) -> None:
        if plan.body_model is not None: route._night_call_kind = ROUTE_CALL_GENERIC; return
        if route._night_direct_param is not None: route._night_call_kind = ROUTE_CALL_DIRECT_PARAM; return
        if plan.call_mode == CALL_REQUEST_KEYWORD: route._night_call_kind = ROUTE_CALL_REQUEST_KEYWORD; return
        if plan.call_mode == CALL_REQUEST_POSITIONAL: route._night_call_kind = ROUTE_CALL_REQUEST_POSITIONAL; return
        sig = plan.signature
        if plan.call_mode == CALL_KWARGS and sig is not None and not sig.parameters: route._night_call_kind = ROUTE_CALL_NOARGS; return
        route._night_call_kind = ROUTE_CALL_GENERIC
    def _compile_route_invoker(self, route: Route, plan: _EndpointPlan):
        fn = route.endpoint; coerce = self._coerce_response; kind = route._night_call_kind; route._night_invoke_async = plan.is_coro; route._night_invoke_scalar = None
        if kind == ROUTE_CALL_DIRECT_PARAM:
            name = route._night_direct_param
            if plan.is_coro:
                async def invoke(req, params, _fn=fn, _name=name, _coerce=coerce): return _coerce(await _fn(params[_name]))
                async def invoke_scalar(value, _fn=fn, _coerce=coerce): return _coerce(await _fn(value))
            else:
                def invoke(req, params, _fn=fn, _name=name, _coerce=coerce): return _coerce(_fn(params[_name]))
                def invoke_scalar(value, _fn=fn, _coerce=coerce): return _coerce(_fn(value))
            route._night_invoke_scalar = invoke_scalar; return invoke
        if kind == ROUTE_CALL_NOARGS:
            if plan.is_coro:
                async def invoke(req, params, _fn=fn, _coerce=coerce): return _coerce(await _fn())
            else:
                def invoke(req, params, _fn=fn, _coerce=coerce): return _coerce(_fn())
            return invoke
        if kind == ROUTE_CALL_REQUEST_KEYWORD:
            if plan.is_coro:
                async def invoke(req, params, _fn=fn, _coerce=coerce): return _coerce(await _fn(req=req))
            else:
                def invoke(req, params, _fn=fn, _coerce=coerce): return _coerce(_fn(req=req))
            return invoke
        if kind == ROUTE_CALL_REQUEST_POSITIONAL:
            if plan.is_coro:
                async def invoke(req, params, _fn=fn, _coerce=coerce): return _coerce(await _fn(req))
            else:
                def invoke(req, params, _fn=fn, _coerce=coerce): return _coerce(_fn(req))
            return invoke
        route._night_invoke_async = True
        async def invoke(req, params, _route=route): return await self._call_route_generic(_route, req, params)
        return invoke
    @staticmethod
    def _simple_dynamic_value(route: Route, path: str):
        prefix, suffix, _name, converter = route._night_simple_dynamic
        if not path.startswith(prefix): return None
        if suffix:
            if not path.endswith(suffix): return None
            value = path[len(prefix):len(path)-len(suffix)]
        else: value = path[len(prefix):]
        if not value or '/' in value: return None
        if converter == 'int':
            try: value = int(value)
            except ValueError: return None
        return value
    def _match_direct_for_dispatch(self, path: str, method: str): return None
    def _on_route_added(self, route: Route):
        key = route.raw_path.rstrip("/") or "/"; plan = _compile_endpoint(route.endpoint); self._endpoint_plans[route.endpoint] = plan; route._night_plan = plan; route._night_simple_dynamic = None; route._night_direct_param = None; route._night_call_kind = ROUTE_CALL_GENERIC
        if "<" in route.raw_path:
            self._dynamic_route_index.append(route)
            tokens = list(re.finditer(r"<([^>]+)>", key))
            if len(tokens) == 1:
                token = tokens[0]; inner = token.group(1); converter, name = inner.split(":", 1) if ":" in inner else ("str", inner)
                if converter in {"str", "int"}:
                    prefix = key[:token.start()]; suffix = key[token.end():]; route._night_simple_dynamic = (prefix, suffix, name, converter)
                    sig = plan.signature
                    if plan.call_mode == CALL_KWARGS and plan.body_model is None and sig is not None:
                        ps = tuple(sig.parameters.values())
                        if len(ps) == 1 and ps[0].name == name and ps[0].kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD): route._night_direct_param = name
            for method in route.methods:
                self._dynamic_method_routes.setdefault(method, []).append(route)
            self._classify_route_call(route, plan); route._night_invoke = self._compile_route_invoker(route, plan); return
        self._classify_route_call(route, plan); route._night_invoke = self._compile_route_invoker(route, plan); self._static_route_index.setdefault(key, []).append(route); methods = self._static_methods_by_path.setdefault(key, set());
        for method in route.methods: methods.add(method); self._static_method_index.setdefault(method, {})[key] = route
    @staticmethod
    def _match_simple_dynamic(route: Route, path: str):
        prefix, suffix, name, converter = route._night_simple_dynamic
        if not path.startswith(prefix): return None
        if suffix:
            if not path.endswith(suffix): return None
            value = path[len(prefix):len(path)-len(suffix)]
        else: value = path[len(prefix):]
        if not value or "/" in value: return None
        if converter == "int":
            try: value = int(value)
            except ValueError: return None
        return {name: value}
    def _match_method(self, path: str, method: str):
        key = path.rstrip('/') or '/'
        routes = self._dynamic_method_routes.get(method)
        if routes:
            for route in routes:
                if route._night_simple_dynamic is not None:
                    params = self._match_simple_dynamic(route, key)
                    if params is not None: return route, params
        route = self._static_method_index.get(method, {}).get(key)
        if route is not None: return route, {}
        raise NotFound()
    def _coerce_response(self, value: t.Any) -> Response:
        kind = type(value)
        if kind is dict or kind is list: return JSONResponse(value)
        if kind is str: return PlainTextResponse(value)
        if kind is bytes: return Response(value)
        if value is None: return Response(b"", status=204)
        if isinstance(value, Response): return value
        if kind is bytearray: return Response(value)
        return PlainTextResponse(str(value))
    async def _call_route_generic(self, route: Route, req: Request, params: dict[str,t.Any]) -> Response:
        plan = route._night_plan; fn = route.endpoint; kwargs = params
        if plan.body_model is not None:
            payload = await req.json(); validated = _validate_dataclass(plan.body_model, payload); target = next((name for name in plan.body_candidates if name not in kwargs), None); kwargs[target] = validated if target is not None else kwargs.setdefault("data", validated)
        if plan.call_mode == CALL_REQUEST_KEYWORD: result = fn(req=req, **kwargs)
        elif plan.call_mode == CALL_REQUEST_POSITIONAL: result = fn(req, **kwargs)
        elif kwargs: result = fn(**kwargs)
        else: result = fn()
        if plan.is_coro: result = await t.cast(t.Awaitable, result)
        return self._coerce_response(result)
    async def _dispatch(self, req: Request, path: str | None = None, method: str | None = None) -> Response:
        route, params = self._match_method(path or req.path, method or req.method); req.path_params = params; invoke = route._night_invoke; result = invoke(req, params); return await result if route._night_invoke_async else result
    async def __call__(self, scope, receive, send):
        req = Request(scope=scope, receive=receive, send=send, max_body_size=self.max_body_size); token = _current_request.set(req)
        try:
            try: resp = await self._dispatch(req)
            except HTTPError as he: resp = PlainTextResponse(he.detail or "Error", status=he.status)
            except Exception: resp = PlainTextResponse(traceback.format_exc() if self.debug else "Internal Server Error", status=500)
            await resp(scope, receive, send)
        finally: _current_request.reset(token)


def jsonify(data: t.Any, status: int = 200, headers: dict[str, str] | None = None) -> JSONResponse: return JSONResponse(data, status=status, headers=headers)
def text(s: str, status: int = 200, headers: dict[str, str] | None = None) -> PlainTextResponse: return PlainTextResponse(s, status=status, headers=headers)
def html(s: str, status: int = 200, headers: dict[str, str] | None = None) -> HTMLResponse: return HTMLResponse(s, status=status, headers=headers)
def redirect(location: str, status: int = 302, *, headers: dict[str, str] | None = None) -> Response: return Response(b"", status=status, headers={**(headers or {}), "location": location})
def query_result(data: t.Any, *, content_location: str | None = None, cache_seconds: int | None = None) -> JSONResponse: return JSONResponse(data)
def stream(body_iter, *, status: int = 200, headers: dict[str, str] | None = None, content_type: str | None = "application/octet-stream") -> StreamingResponse: return StreamingResponse(body_iter, status=status, headers=headers, content_type=content_type)
def send_file(path: str, *, req: Request | None = None, status: int = 200, headers: dict[str,str] | None = None, download_name: str | None = None, cache_seconds: int | None = 3600) -> FileResponse: return FileResponse(path, req=req, status=status, headers=headers, download_name=download_name, cache_seconds=cache_seconds)
def static(root: str, *, url_prefix: str = "/static", cache_seconds: int | None = 3600) -> Router:
    r = Router()
    @r.get(url_prefix + "/<path:path>", name="static")
    def _static(path: str):
        full = _safe_join(root, path)
        if not os.path.exists(full) or not os.path.isfile(full): raise NotFound()
        return FileResponse(full, req=request(), cache_seconds=cache_seconds)
    return r

def create_app(debug: bool = False) -> Night:
    app = Night(debug=debug)
    @app.get("/health")
    def health(): return {"ok": True}
    return app

app = create_app(debug=bool(os.environ.get("NIGHT_DEBUG")))
