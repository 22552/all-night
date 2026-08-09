"""Unified Midnight runtime API.

This module is the preferred public entry point for Midnight's hybrid DOM
expressions, client compilation, and direct WebSocket transport. The older
``night_midnight_hybrid``, ``night_midnight_compile``, and ``night_midnight_ws``
modules remain available for compatibility.
"""

from __future__ import annotations

from night_midnight_hybrid import (
    ClientExpr,
    DOMRef,
    DOMValue,
    HybridExpressionError,
    HybridMidnight,
    JSRef,
    get,
    js,
)
from night_midnight_compile import (
    CompiledMidnight,
    EventExpr,
    MidnightCompileError,
)
from night_midnight_ws import (
    MIDNIGHT_WS_RUNTIME,
    MidnightWebSocketAdapter,
    serve_midnight_ws,
)

__all__ = [
    "ClientExpr",
    "CompiledMidnight",
    "DOMRef",
    "DOMValue",
    "EventExpr",
    "HybridExpressionError",
    "HybridMidnight",
    "JSRef",
    "MIDNIGHT_WS_RUNTIME",
    "MidnightCompileError",
    "MidnightWebSocketAdapter",
    "get",
    "js",
    "serve_midnight_ws",
]
