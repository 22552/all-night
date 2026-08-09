"""Direct browser WebSocket transport for Midnight.

This module is the normal CPython/server counterpart to Browser Night's
postMessage adapter. It connects browser DOM events and Midnight commands over
one persistent WebSocket, while keeping the core :mod:`night_midnight` runtime
transport-independent.
"""

from __future__ import annotations

import secrets
import typing as t

from night_midnight import Midnight, trusted_session_id


MIDNIGHT_WS_RUNTIME = r'''(() => {
  const state = {
    socket: null,
    url: null,
    reconnect: true,
    reconnectDelayMs: 500,
    reconnectMaxDelayMs: 5000,
    reconnectAttempt: 0,
    reconnectTimer: null,
    subscriptions: [],
    listeners: new Map(),
    compiled: new Map(),
    pendingEvents: new Map(),
    outbox: [],
    nextEventId: 1,
    serverEvents: 0,
    localCompiledEvents: 0,
  };

  const compiledKey = (eventName, selector) => `${eventName}\u0000${selector ?? ""}`;

  function runtimeEvent(name, detail = null) {
    window.dispatchEvent(new CustomEvent(`midnight:${name}`, { detail }));
  }

  function targetInfo(element) {
    if (!(element instanceof Element)) return {};
    const info = {
      tag: element.tagName.toLowerCase(),
      id: element.id || null,
      name: element.getAttribute("name"),
      value: "value" in element ? element.value : null,
      checked: "checked" in element ? Boolean(element.checked) : null,
    };
    if (element.dataset && Object.keys(element.dataset).length) info.dataset = { ...element.dataset };
    return info;
  }

  function formDataFor(element) {
    const form = element instanceof HTMLFormElement ? element : element?.closest?.("form");
    if (!form) return null;
    const out = {};
    for (const [key, value] of new FormData(form)) {
      const text = String(value);
      if (key in out) out[key] = Array.isArray(out[key]) ? [...out[key], text] : [out[key], text];
      else out[key] = text;
    }
    return out;
  }

  function serializeEvent(event, selector, matched) {
    const payload = {
      type: event.type,
      selector,
      target: targetInfo(matched || event.target),
      time_stamp: Number(event.timeStamp || 0),
    };
    if (event instanceof KeyboardEvent) {
      payload.key = event.key;
      payload.code = event.code;
      payload.repeat = event.repeat;
      payload.alt = event.altKey;
      payload.ctrl = event.ctrlKey;
      payload.meta = event.metaKey;
      payload.shift = event.shiftKey;
    }
    if (event instanceof MouseEvent) {
      payload.button = event.button;
      payload.buttons = event.buttons;
      payload.x = event.clientX;
      payload.y = event.clientY;
    }
    if (event.type === "submit" || event.type === "change" || event.type === "input") {
      payload.form = formDataFor(matched || event.target);
    }
    return payload;
  }

  function propertyName(name) {
    if (name === "text") return "textContent";
    if (name === "html") return "innerHTML";
    return String(name);
  }

  function readDom(selector, property) {
    const element = document.querySelector(selector);
    return element ? element[propertyName(property)] : null;
  }

  function setDom(selector, property, value) {
    for (const element of document.querySelectorAll(selector)) {
      const key = propertyName(property);
      if (key in element) element[key] = value ?? "";
      else if (value == null) element.removeAttribute(key);
      else element.setAttribute(key, String(value));
    }
  }

  function resolvePath(value, path) {
    let current = value;
    for (const part of path || []) current = current?.[part];
    return current;
  }

  function resolveJsRef(path) {
    let parent = null;
    let value = globalThis;
    for (const part of path || []) {
      parent = value;
      value = value?.[part];
    }
    return { parent, value };
  }

  async function evalClient(node, sourceEvent = null) {
    if (!node || typeof node !== "object") return null;
    switch (node.kind) {
      case "literal": return node.value;
      case "dom": return readDom(node.selector, node.property);
      case "event": return resolvePath(sourceEvent, node.path);
      case "event_get": {
        const value = resolvePath(sourceEvent, node.path);
        return value == null ? node.default : value;
      }
      case "js_ref": return resolveJsRef(node.path).value;
      case "call": {
        const args = [];
        for (const arg of node.args || []) args.push(await evalClient(arg, sourceEvent));
        if (node.callee?.kind === "js_ref") {
          const ref = resolveJsRef(node.callee.path);
          if (typeof ref.value !== "function") throw new TypeError(`${node.callee.path.join(".")} is not callable`);
          return await ref.value.apply(ref.parent, args);
        }
        const fn = await evalClient(node.callee, sourceEvent);
        if (typeof fn !== "function") throw new TypeError("client expression is not callable");
        return await fn(...args);
      }
      case "binary": {
        const left = await evalClient(node.left, sourceEvent);
        const right = await evalClient(node.right, sourceEvent);
        switch (node.op) {
          case "add": return left + right;
          case "sub": return left - right;
          case "mul": return left * right;
          case "div": return left / right;
          case "mod": return left % right;
          case "pow": return left ** right;
          default: throw new Error(`unknown client operation: ${node.op}`);
        }
      }
      default: throw new Error(`unknown client expression node: ${node.kind}`);
    }
  }

  async function runProgram(program, sourceEvent = null) {
    for (const instruction of program || []) {
      if (instruction.op === "dom_set_expr") {
        setDom(instruction.selector, instruction.property, await evalClient(instruction.expr, sourceEvent));
      } else if (instruction.op === "dom_set") {
        setDom(instruction.selector, instruction.property, instruction.value);
      } else {
        throw new Error(`unknown compiled Midnight instruction: ${instruction.op}`);
      }
    }
  }

  function programsFor(eventName, selector) {
    const bucket = state.compiled.get(compiledKey(eventName, selector));
    return bucket ? [...bucket.values()] : [];
  }

  function installCompiled(command) {
    const key = compiledKey(command.event, command.selector);
    let bucket = state.compiled.get(key);
    if (!bucket) {
      bucket = new Map();
      state.compiled.set(key, bucket);
    }
    bucket.set(String(command.handler_id), command);
    runtimeEvent("compiled-install", {
      handler_id: command.handler_id,
      event: command.event,
      selector: command.selector,
      exclusive: Boolean(command.exclusive),
    });
  }

  function sendRaw(message) {
    const text = typeof message === "string" ? message : JSON.stringify(message);
    const socket = state.socket;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(text);
      return true;
    }
    state.outbox.push(text);
    if (state.outbox.length > 256) state.outbox.splice(0, state.outbox.length - 256);
    return false;
  }

  function sendEvent(payload, sourceEvent = null) {
    const eventId = state.nextEventId++;
    if (sourceEvent) state.pendingEvents.set(eventId, sourceEvent);
    state.serverEvents += 1;
    sendRaw({ type: "midnight-event", event_id: eventId, event: payload });
    runtimeEvent("server-event", { event_id: eventId, payload });
    return eventId;
  }

  async function applyCommand(command, sourceEvent = null) {
    if (!command || typeof command !== "object") return;
    const selector = command.selector;
    switch (command.op) {
      case "emit":
        runtimeEvent(command.name, command.detail);
        break;
      case "text":
        for (const element of document.querySelectorAll(selector)) element.textContent = String(command.value ?? "");
        break;
      case "html":
        for (const element of document.querySelectorAll(selector)) element.innerHTML = String(command.value ?? "");
        break;
      case "value":
        setDom(selector, "value", command.value);
        break;
      case "attr":
        for (const element of document.querySelectorAll(selector)) {
          if (command.value == null) element.removeAttribute(command.name);
          else element.setAttribute(command.name, String(command.value));
        }
        break;
      case "class_add":
        for (const element of document.querySelectorAll(selector)) element.classList.add(...(command.names || []));
        break;
      case "class_remove":
        for (const element of document.querySelectorAll(selector)) element.classList.remove(...(command.names || []));
        break;
      case "focus":
        document.querySelector(selector)?.focus?.();
        break;
      case "bind":
        for (const element of document.querySelectorAll("[data-midnight-bind]")) {
          if (element.getAttribute("data-midnight-bind") === String(command.name)) {
            element.textContent = String(command.value ?? "");
          }
        }
        break;
      case "dom_set":
        setDom(command.selector, command.property, command.value);
        break;
      case "hybrid_client_set":
        setDom(command.selector, command.property, await evalClient(command.expr, sourceEvent));
        break;
      case "hybrid_server_set": {
        const values = (command.reads || []).map(item => readDom(item.selector, item.property));
        sendEvent({
          type: "custom:__hybrid_result",
          selector: null,
          detail: { request_id: command.request_id, values },
        });
        break;
      }
      case "compiled_install":
        installCompiled(command);
        if (command.execute_now) await runProgram(command.program, sourceEvent);
        break;
      case "hybrid_error":
        runtimeEvent("error", command);
        console.error("Midnight hybrid error", command);
        break;
      default:
        runtimeEvent("unknown-command", command);
    }
  }

  async function applyCommands(commands, sourceEvent = null) {
    for (const command of commands || []) await applyCommand(command, sourceEvent);
  }

  function clearDomListeners() {
    for (const [eventName, handler] of state.listeners) document.removeEventListener(eventName, handler, true);
    state.listeners.clear();
  }

  function configure(subscriptions = []) {
    clearDomListeners();
    state.subscriptions = Array.isArray(subscriptions) ? subscriptions : [];
    const events = [...new Set(state.subscriptions.map(item => item.event).filter(Boolean))];
    for (const eventName of events) {
      const handler = event => {
        const items = state.subscriptions.filter(item => item.event === eventName);
        for (const item of items) {
          const selector = item.selector ?? null;
          const matched = selector
            ? event.target instanceof Element ? event.target.closest(selector) : null
            : event.target;
          if (selector && !matched) continue;
          if (item.prevent_default) event.preventDefault();

          const programs = programsFor(eventName, selector);
          if (programs.length) {
            state.localCompiledEvents += 1;
            void Promise.all(programs.map(program => runProgram(program.program, event))).then(() => {
              runtimeEvent("compiled-execute", {
                event: eventName,
                selector,
                handlers: programs.map(program => program.handler_id),
              });
            }).catch(error => runtimeEvent("error", { error: String(error) }));
            if (programs.every(program => Boolean(program.exclusive))) continue;
          }

          sendEvent(serializeEvent(event, selector, matched), event);
        }
      };
      state.listeners.set(eventName, handler);
      document.addEventListener(eventName, handler, true);
    }
    runtimeEvent("configured", { subscriptions: state.subscriptions });
  }

  function clearReconnectTimer() {
    if (state.reconnectTimer != null) clearTimeout(state.reconnectTimer);
    state.reconnectTimer = null;
  }

  function scheduleReconnect() {
    if (!state.reconnect || !state.url) return;
    clearReconnectTimer();
    state.reconnectAttempt += 1;
    const delay = Math.min(
      state.reconnectMaxDelayMs,
      state.reconnectDelayMs * (2 ** Math.max(0, state.reconnectAttempt - 1)),
    );
    state.reconnectTimer = setTimeout(() => connectTransport(state.url, { _reconnect: true }), delay);
    runtimeEvent("transport", { state: "reconnecting", attempt: state.reconnectAttempt, delay });
  }

  function connectTransport(url, options = {}) {
    const reconnecting = Boolean(options._reconnect);
    if (!reconnecting) {
      state.url = String(url);
      state.reconnect = options.reconnect !== false;
      state.reconnectDelayMs = Math.max(0, Number(options.reconnectDelayMs ?? 500));
      state.reconnectMaxDelayMs = Math.max(state.reconnectDelayMs, Number(options.reconnectMaxDelayMs ?? 5000));
      state.reconnectAttempt = 0;
      clearReconnectTimer();
      if (state.socket) {
        const old = state.socket;
        state.socket = null;
        old.close(1000, "replaced");
      }
    }

    const socket = new WebSocket(state.url);
    state.socket = socket;
    runtimeEvent("transport", { state: "connecting", url: state.url });

    socket.addEventListener("open", () => {
      if (state.socket !== socket) return;
      state.reconnectAttempt = 0;
      runtimeEvent("transport", { state: "open", url: state.url });
      const queued = state.outbox.splice(0);
      for (const item of queued) socket.send(item);
    });

    socket.addEventListener("message", event => {
      if (typeof event.data !== "string") return;
      let message;
      try { message = JSON.parse(event.data); }
      catch { return; }
      if (message.type === "midnight-config") {
        configure(message.subscriptions || []);
        return;
      }
      if (message.type === "midnight-commands") {
        const eventId = Number(message.event_id || 0);
        const sourceEvent = state.pendingEvents.get(eventId) || null;
        state.pendingEvents.delete(eventId);
        void applyCommands(message.commands || [], sourceEvent).catch(error => {
          runtimeEvent("error", { error: String(error) });
        });
        return;
      }
      if (message.type === "midnight-error") runtimeEvent("error", message);
    });

    socket.addEventListener("close", event => {
      if (state.socket !== socket) return;
      state.socket = null;
      runtimeEvent("transport", { state: "closed", code: event.code, reason: event.reason });
      scheduleReconnect();
    });

    socket.addEventListener("error", () => runtimeEvent("transport", { state: "error" }));
    return socket;
  }

  function disconnectTransport(code = 1000, reason = "") {
    state.reconnect = false;
    clearReconnectTimer();
    const socket = state.socket;
    state.socket = null;
    if (socket) socket.close(Number(code), String(reason));
  }

  window.midnight = Object.freeze({
    connectTransport,
    disconnectTransport,
    emit(name, detail = null) {
      sendEvent({ type: `custom:${name}`, selector: null, detail });
    },
    on(name, handler, options) {
      const wrapped = event => handler(event.detail, event);
      window.addEventListener(`midnight:${name}`, wrapped, options);
      return () => window.removeEventListener(`midnight:${name}`, wrapped, options);
    },
    stats() {
      return {
        connected: Boolean(state.socket && state.socket.readyState === WebSocket.OPEN),
        serverEvents: state.serverEvents,
        localCompiledEvents: state.localCompiledEvents,
        compiledPrograms: [...state.compiled.values()].reduce((count, bucket) => count + bucket.size, 0),
        queued: state.outbox.length,
      };
    },
  });

  runtimeEvent("ready", null);
})();'''


class MidnightWebSocketAdapter:
    """Serve one :class:`Midnight` instance over a Night WebSocket route.

    The adapter mints an unguessable server-side session identifier for each
    accepted socket and binds every event on that socket to that trusted
    session. Reconnects currently create a new logical server session; browser
    compiled programs remain cached for the lifetime of the page.
    """

    def __init__(self, midnight: Midnight) -> None:
        self.midnight = midnight

    async def serve(self, ws: t.Any) -> None:
        session_id = trusted_session_id(secrets.token_urlsafe(24))
        await ws.accept()
        await ws.send_json(
            {
                "type": "midnight-config",
                "subscriptions": self.midnight.subscriptions(),
            }
        )
        try:
            while True:
                message = await ws.receive_json()
                if not isinstance(message, dict) or message.get("type") != "midnight-event":
                    await ws.send_json(
                        {
                            "type": "midnight-error",
                            "error": "expected midnight-event",
                        }
                    )
                    continue
                payload = message.get("event")
                if not isinstance(payload, dict):
                    await ws.send_json(
                        {
                            "type": "midnight-error",
                            "error": "event must be an object",
                        }
                    )
                    continue
                commands = await self.midnight.dispatch_trusted(session_id, payload)
                await ws.send_json(
                    {
                        "type": "midnight-commands",
                        "event_id": message.get("event_id"),
                        "commands": commands,
                    }
                )
        except ConnectionError:
            return
        finally:
            self.midnight.drop_session(session_id)


async def serve_midnight_ws(midnight: Midnight, ws: t.Any) -> None:
    """Convenience one-shot adapter for ``@app.websocket`` routes."""
    await MidnightWebSocketAdapter(midnight).serve(ws)


__all__ = ["MIDNIGHT_WS_RUNTIME", "MidnightWebSocketAdapter", "serve_midnight_ws"]
