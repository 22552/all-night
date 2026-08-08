"""Scoped, reusable UI components for Midnight.

This module intentionally builds on the public ``Midnight`` API instead of
reaching into its registries. Components therefore remain a thin namespace and
selector layer rather than a second event system.
"""

from __future__ import annotations

import re
import typing as t

from night_midnight import Midnight, midnight


_COMPONENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


class Component:
    """A reusable Midnight event/DOM scope.

    ``root`` is the CSS selector for one component instance. ``name`` is the
    logical namespace used for custom events and live template bindings. Two
    instances can therefore reuse the same local selectors without colliding.
    """

    def __init__(
        self,
        root: str,
        *,
        name: str | None = None,
        bridge: Midnight | None = None,
    ) -> None:
        root = str(root).strip()
        if not root:
            raise ValueError("component root selector cannot be empty")
        inferred = root[1:] if root[:1] in {"#", "."} else root
        namespace = str(name or inferred).strip()
        if not _COMPONENT_NAME.fullmatch(namespace):
            raise ValueError("component name must be a simple namespace")
        self.root = root
        self.name = namespace
        self.midnight = bridge or midnight

    def selector(self, local: str | None = None) -> str:
        """Return a selector scoped to this component instance.

        ``&`` may be used as an explicit root placeholder, similar to nested
        CSS. ``None`` and ``&`` both select the component root itself.
        """
        if local is None:
            return self.root
        local = str(local).strip()
        if not local or local == "&":
            return self.root
        if "&" in local:
            return local.replace("&", self.root)
        return f"{self.root} {local}"

    def binding(self, name: str) -> str:
        return f"{self.name}.{str(name)}"

    def event_name(self, name: str) -> str:
        return f"{self.name}:{str(name)}"

    def on(
        self,
        event: str,
        selector: str | None = None,
        *,
        prevent_default: bool = False,
    ):
        return self.midnight.on(
            event,
            self.selector(selector),
            prevent_default=prevent_default,
        )

    def on_event(self, name: str):
        return self.midnight.on_event(self.event_name(name))

    def emit(self, name: str, detail: t.Any = None) -> None:
        self.midnight.emit(self.event_name(name), detail)

    def set(self, name: str, value: t.Any) -> None:
        self.midnight.set(self.binding(name), value)

    def text(self, selector: str | None, value: t.Any) -> None:
        self.midnight.text(self.selector(selector), value)

    def html(self, selector: str | None, value: t.Any) -> None:
        self.midnight.html(self.selector(selector), value)

    def value(self, selector: str | None, value: t.Any) -> None:
        self.midnight.value(self.selector(selector), value)

    def attr(self, selector: str | None, name: str, value: t.Any = None) -> None:
        self.midnight.attr(self.selector(selector), name, value)

    def add_class(self, selector: str | None, *names: str) -> None:
        self.midnight.add_class(self.selector(selector), *names)

    def remove_class(self, selector: str | None, *names: str) -> None:
        self.midnight.remove_class(self.selector(selector), *names)

    def focus(self, selector: str | None = None) -> None:
        self.midnight.focus(self.selector(selector))


__all__ = ["Component"]
