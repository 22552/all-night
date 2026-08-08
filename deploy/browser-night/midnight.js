(() => {
  const state = {
    subscriptions: [],
    listeners: new Map(),
    sockets: new Map(),
    persistence: new Map(),
  };

  const post = (type, event) => parent.postMessage({ type, event }, "*");

  function targetInfo(element) {
    if (!(element instanceof Element)) return {};
    const info = {
      tag: element.tagName.toLowerCase(),
      id: element.id || null,
      name: element.getAttribute("name"),
      value: "value" in element ? element.value : null,
      checked: "checked" in element ? Boolean(element.checked) : null,
    };
    if (element.dataset && Object.keys(element.dataset).length) {
      info.dataset = { ...element.dataset };
    }
    return info;
  }

  function formDataFor(element) {
    const form = element instanceof HTMLFormElement ? element : element.closest?.("form");
    if (!form) return null;
    const out = {};
    for (const [key, value] of new FormData(form)) {
      if (key in out) {
        out[key] = Array.isArray(out[key]) ? [...out[key], String(value)] : [out[key], String(value)];
      } else {
        out[key] = String(value);
      }
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

  function clearDomListeners() {
    for (const [eventName, handler] of state.listeners) {
      document.removeEventListener(eventName, handler, true);
    }
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
          post("midnight-event", serializeEvent(event, selector, matched));
        }
      };
      state.listeners.set(eventName, handler);
      document.addEventListener(eventName, handler, true);
    }
  }

  function socketPayload(socketId, type, extra = {}) {
    return { type, socket_id: socketId, ...extra };
  }

  function connect(url, options = {}) {
    const socketId = String(options.socketId ?? options.socket_id ?? "default");
    const protocols = options.protocols;
    state.sockets.get(socketId)?.close(1000, "replaced");
    const ws = protocols?.length ? new WebSocket(url, protocols) : new WebSocket(url);
    state.sockets.set(socketId, ws);
    ws.addEventListener("open", () => post("midnight-ws", socketPayload(socketId, "open", { url: ws.url })));
    ws.addEventListener("message", event => {
      let json = null;
      if (typeof event.data === "string") {
        try { json = JSON.parse(event.data); } catch {}
      }
      post("midnight-ws", socketPayload(socketId, "message", {
        data: typeof event.data === "string" ? event.data : null,
        json,
      }));
    });
    ws.addEventListener("close", event => {
      post("midnight-ws", socketPayload(socketId, "close", {
        code: event.code,
        reason: event.reason,
        clean: event.wasClean,
      }));
      if (state.sockets.get(socketId) === ws) state.sockets.delete(socketId);
    });
    ws.addEventListener("error", () => post("midnight-ws", socketPayload(socketId, "error")));
    return ws;
  }

  function send(data, socketId = "default") {
    const ws = state.sockets.get(String(socketId));
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(typeof data === "string" || data instanceof ArrayBuffer || ArrayBuffer.isView(data)
      ? data
      : JSON.stringify(data));
    return true;
  }

  function close(socketId = "default", code = 1000, reason = "") {
    const ws = state.sockets.get(String(socketId));
    if (!ws) return false;
    ws.close(Number(code), String(reason));
    return true;
  }

  function persistBody(item) {
    if (typeof item.data === "string") return item.data;
    return JSON.stringify(item.data ?? null);
  }

  function persistHeaders(item) {
    const headers = { ...(item.headers || {}) };
    const hasContentType = Object.keys(headers).some(name => name.toLowerCase() === "content-type");
    if (!hasContentType && item.content_type) headers["Content-Type"] = item.content_type;
    return headers;
  }

  function sendPersist(item) {
    const body = persistBody(item);
    const customHeaders = item.headers && Object.keys(item.headers).length > 0;
    const canBeacon = item.transport !== "fetch" && !customHeaders && typeof navigator.sendBeacon === "function";

    if (canBeacon) {
      try {
        const payload = new Blob([body], { type: item.content_type || "application/json" });
        if (navigator.sendBeacon(item.url, payload)) return Promise.resolve(true);
      } catch {}
      if (item.transport === "beacon") return Promise.resolve(false);
    }

    if (item.transport === "beacon") return Promise.resolve(false);
    try {
      return fetch(item.url, {
        method: "POST",
        body,
        headers: persistHeaders(item),
        keepalive: true,
        credentials: "same-origin",
      }).then(() => true, () => false);
    } catch {
      return Promise.resolve(false);
    }
  }

  function registerPersist(item) {
    const normalized = {
      key: String(item.key ?? "default"),
      url: String(item.url),
      data: item.data ?? null,
      transport: String(item.transport ?? "auto"),
      when: String(item.when ?? "leave"),
      headers: item.headers && typeof item.headers === "object" ? { ...item.headers } : {},
      content_type: String(item.content_type ?? "application/json"),
    };
    state.persistence.set(normalized.key, normalized);
    if (normalized.when === "now") sendPersist(normalized);
    return normalized.key;
  }

  function cancelPersist(key = "default") {
    return state.persistence.delete(String(key));
  }

  function flushPersist({ key = null, when = null } = {}) {
    const jobs = [];
    for (const [persistKey, item] of state.persistence) {
      if (key != null && persistKey !== String(key)) continue;
      if (when != null && item.when !== String(when)) continue;
      jobs.push(sendPersist(item));
    }
    return Promise.allSettled(jobs);
  }

  function lifecycle(name, detail = {}) {
    post("midnight-event", {
      type: `custom:__lifecycle_${name}`,
      selector: null,
      detail: {
        visibility_state: document.visibilityState,
        persisted: Boolean(detail.persisted),
      },
    });
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      lifecycle("hide");
      void flushPersist({ when: "hide" });
    } else if (document.visibilityState === "visible") {
      lifecycle("show");
    }
  });

  window.addEventListener("pagehide", event => {
    lifecycle("leave", { persisted: event.persisted });
    void flushPersist({ when: "leave" });
  });

  function each(selector, fn) {
    for (const element of document.querySelectorAll(selector)) fn(element);
  }

  function applyCommand(command) {
    if (!command || typeof command !== "object") return;
    const selector = command.selector;
    switch (command.op) {
      case "emit":
        window.dispatchEvent(new CustomEvent(`midnight:${command.name}`, { detail: command.detail }));
        break;
      case "text":
        each(selector, element => { element.textContent = String(command.value ?? ""); });
        break;
      case "html":
        each(selector, element => { element.innerHTML = String(command.value ?? ""); });
        break;
      case "value":
        each(selector, element => { if ("value" in element) element.value = command.value ?? ""; });
        break;
      case "attr":
        each(selector, element => {
          if (command.value == null) element.removeAttribute(command.name);
          else element.setAttribute(command.name, String(command.value));
        });
        break;
      case "class_add":
        each(selector, element => element.classList.add(...(command.names || [])));
        break;
      case "class_remove":
        each(selector, element => element.classList.remove(...(command.names || [])));
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
      case "persist":
        registerPersist(command);
        break;
      case "persist_cancel":
        cancelPersist(command.key);
        break;
      case "persist_flush":
        void flushPersist({ key: command.key ?? null });
        break;
      case "ws_connect":
        connect(command.url, { socketId: command.socket_id, protocols: command.protocols || [] });
        break;
      case "ws_send":
        send(command.data, command.socket_id);
        break;
      case "ws_close":
        close(command.socket_id, command.code, command.reason);
        break;
    }
  }

  window.midnight = Object.freeze({
    emit(name, detail = null) {
      post("midnight-event", { type: `custom:${name}`, selector: null, detail });
    },
    on(name, handler, options) {
      const wrapped = event => handler(event.detail, event);
      window.addEventListener(`midnight:${name}`, wrapped, options);
      return () => window.removeEventListener(`midnight:${name}`, wrapped, options);
    },
    connect,
    send,
    close,
    persist(url, data = null, options = {}) {
      return registerPersist({ url, data, ...options });
    },
    cancelPersist,
    flushPersist(key = null) {
      return flushPersist({ key });
    },
  });

  window.addEventListener("message", event => {
    const message = event.data;
    if (!message) return;
    if (message.type === "midnight-config") configure(message.subscriptions);
    else if (message.type === "midnight-command") applyCommand(message.command);
  });

  parent.postMessage({ type: "midnight-ready" }, "*");
})();
