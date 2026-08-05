from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import json
import traceback
import typing as t

from night import (
    HTTPError,
    JSONResponse,
    MethodNotAllowed,
    PlainTextResponse,
    Request,
    Response,
    ValidationError,
    MAX_SESSION_COOKIE_SIZE,
)


async def handle(app, req: Request) -> Response:
    """Run Night's HTTP application pipeline independently of ASGI transport.

    This is intentionally implemented as a standalone helper first so the
    behavior can be validated before moving it into ``Night.handle``.
    """

    async def call_next(i: int = 0) -> Response:
        if i >= len(app.middlewares):
            return await app._dispatch(req)

        middleware = app.middlewares[i]

        async def nxt() -> Response:
            return await call_next(i + 1)

        return await middleware(req, nxt)

    if req.method == "OPTIONS":
        allowed = app._allowed_methods_for_path(req.path)
        if allowed:
            headers = {"allow": ",".join(sorted(set(allowed) | {"OPTIONS"}))}
            return Response(b"", status=204, headers=headers)
        return PlainTextResponse("Not Found", status=404)

    is_head = req.method == "HEAD"
    if is_head:
        req.scope = dict(req.scope)
        req.scope["method"] = "GET"

    try:
        resp = await call_next(0)
    except HTTPError as exc:
        handler = app._find_error_handler(exc)
        if handler is not None:
            out = handler(req, exc)
            if inspect.isawaitable(out):
                out = await t.cast(t.Awaitable, out)
            resp = app._coerce_response(out)
        else:
            error_headers = {}
            if isinstance(exc, MethodNotAllowed) and exc.allowed:
                error_headers["allow"] = ",".join(exc.allowed)
            if isinstance(exc, ValidationError):
                resp = JSONResponse({"errors": exc.errors}, status=exc.status, headers=error_headers)
            elif app.debug:
                resp = PlainTextResponse(f"{exc.status} {exc.detail}", status=exc.status, headers=error_headers)
            else:
                resp = PlainTextResponse(exc.detail or "Error", status=exc.status, headers=error_headers)
    except Exception as exc:
        handler = app._find_error_handler(exc)
        if handler is not None:
            out = handler(req, exc)
            if inspect.isawaitable(out):
                out = await t.cast(t.Awaitable, out)
            resp = app._coerce_response(out)
        elif app.debug:
            resp = PlainTextResponse(traceback.format_exc(), status=500)
        else:
            resp = PlainTextResponse("Internal Server Error", status=500)

    if is_head:
        content_length = resp.headers.get("content-length")
        resp.body = b""
        if content_length is not None:
            resp.headers["content-length"] = content_length
        else:
            resp.headers.pop("content-length", None)

    if app.secret_key and "_session" in req.scope:
        current = json.dumps(req.scope["_session"], sort_keys=True, separators=(",", ":"))
        original = req.scope.get("_session_original", "")
        if current != original or req.scope.get("_session_regenerated"):
            encoded = base64.urlsafe_b64encode(current.encode()).decode().rstrip("=")
            signature = hmac.new(app.secret_key, encoded.encode(), hashlib.sha256).hexdigest()
            cookie_overhead = len("night_session=; Path=/; HttpOnly; SameSite=Lax")
            if len(encoded) + len(signature) + cookie_overhead > MAX_SESSION_COOKIE_SIZE:
                message = "Session data exceeds cookie size limit" if app.debug else "Internal Server Error"
                resp = PlainTextResponse(message, status=500)
            else:
                secure = app.session_secure if app.session_secure is not None else req.scope.get("scheme") == "https"
                resp.set_cookie(
                    "night_session",
                    encoded + "." + signature,
                    httponly=True,
                    secure=secure,
                    samesite="Lax",
                )

    return resp
