# Midnight forms

Midnight serializes the nearest HTML form into the event payload for `input`, `change`, and `submit` events. The core bridge exposes that snapshot as `event["form"]`; the optional `night_midnight_form` helper module adds a small read-only wrapper around it.

## Live form snapshots

```html
<form id="profile">
  <input name="user">
  <input name="email" type="email">
</form>
```

```python
from night_midnight import midnight
from night_midnight_form import form

@midnight.on("input", "#profile")
def editing(event):
    data = form(event)
    midnight.text("#preview", data.getone("user", ""))
```

Every `input` event contains the values that are currently successful form controls according to the browser's `FormData` rules. `change` and `submit` use the same snapshot format.

## Snapshot shape

A normal field is a string:

```python
{"user": "Ada"}
```

Repeated controls with the same `name` are represented as a list:

```html
<input type="checkbox" name="lang" value="python" checked>
<input type="checkbox" name="lang" value="rust" checked>
```

```python
{"lang": ["python", "rust"]}
```

`FormSnapshot` makes both cases convenient:

```python
data = form(event)

data.getone("user")       # "Ada"
data.getlist("user")      # ["Ada"]
data.getone("lang")       # first selected value
data.getlist("lang")      # all selected values
data.as_dict()             # detached mutable dict copy
```

The wrapper implements `Mapping`, so normal operations such as `data["user"]`, `"user" in data`, iteration, and `len(data)` also work.

## Submit handling

```python
@midnight.on("submit", "#signup", prevent_default=True)
async def signup(event):
    data = form(event)
    user = data.getone("user", "")
    email = data.getone("email", "")

    if not user or not email:
        midnight.text("#error", "Fill in all required fields")
        return

    # Validate again on the trusted server boundary before persistence.
    midnight.text("#status", "Ready")
```

`prevent_default=True` prevents normal browser submission, but it does not validate or sanitize values. Treat every event payload as client-controlled input.

## `input`, `change`, or `submit`?

Use `input` for live previews, search boxes, counters, and draft UI. Use `change` when you only need committed control changes. Use `submit` for the final form action.

## Browser `FormData` semantics

Midnight intentionally follows browser `FormData` behavior rather than inventing a second form model. This means:

- controls need a `name` to appear in the snapshot;
- unchecked checkboxes and radio buttons are omitted;
- disabled controls are omitted;
- multiple selected values or repeated names may become a list;
- values arrive as strings in the current bridge.

For numeric, date, boolean, or structured values, parse and validate them in Python.

## File inputs

The current Midnight event snapshot is intended for small serializable form state, not file transfer. Do not rely on `event["form"]` for file contents. Use Night's normal HTTP upload/multipart APIs or another explicit upload transport for files.

## Core payload vs helper extension

The helper is optional. Existing code remains valid:

```python
@midnight.on("input", "#profile")
def editing(event):
    raw = event.get("form") or {}
```

`night_midnight_form` only normalizes this existing payload and adds `getone()` / `getlist()` convenience methods. It does not change the browser protocol or add a runtime dependency.
