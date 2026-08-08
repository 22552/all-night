"""Form helpers for Midnight event snapshots.

Midnight's browser bridge attaches a serialized form snapshot to ``input``,
``change`` and ``submit`` events. This module keeps convenience APIs separate
from the core bridge so applications that do not need forms pay no extra cost.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import typing as t

FormValue = str | list[str]
FormData = dict[str, FormValue]


class FormSnapshot(Mapping[str, FormValue]):
    """Read-only view of a Midnight ``event['form']`` payload.

    Repeated successful controls with the same name are represented as a list.
    ``getone()`` returns one scalar value, while ``getlist()`` always returns a
    list and is convenient for checkbox groups and multi-select controls.
    """

    def __init__(self, data: Mapping[str, t.Any] | None = None) -> None:
        normalized: FormData = {}
        for key, value in (data or {}).items():
            name = str(key)
            if isinstance(value, (list, tuple)):
                normalized[name] = [str(item) for item in value]
            elif value is not None:
                normalized[name] = str(value)
        self._data = normalized

    @classmethod
    def from_event(cls, event: Mapping[str, t.Any] | None) -> "FormSnapshot":
        """Build a snapshot from a Midnight event payload.

        Missing or malformed ``form`` payloads produce an empty snapshot. This
        makes the helper safe to use in handlers shared across event types.
        """
        if not isinstance(event, Mapping):
            return cls()
        data = event.get("form")
        return cls(data if isinstance(data, Mapping) else None)

    def __getitem__(self, key: str) -> FormValue:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def getone(self, name: str, default: t.Any = None) -> str | t.Any:
        """Return the first value for ``name`` or ``default`` when absent."""
        value = self._data.get(str(name))
        if isinstance(value, list):
            return value[0] if value else default
        return default if value is None else value

    def getlist(self, name: str) -> list[str]:
        """Return all values for ``name`` as a new list."""
        value = self._data.get(str(name))
        if value is None:
            return []
        if isinstance(value, list):
            return list(value)
        return [value]

    def as_dict(self) -> FormData:
        """Return a detached mutable copy of the normalized form payload."""
        return {
            key: list(value) if isinstance(value, list) else value
            for key, value in self._data.items()
        }


def form(event: Mapping[str, t.Any] | None) -> FormSnapshot:
    """Convenience alias for :meth:`FormSnapshot.from_event`."""
    return FormSnapshot.from_event(event)


__all__ = ["FormData", "FormSnapshot", "FormValue", "form"]
