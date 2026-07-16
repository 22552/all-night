# All-Night

A tiny, single-file Flask-like ASGI web framework.

```bash
pip install all-night
```

```python
from night import Night

app = Night()

@app.get("/")
def index():
    return {"hello": "night"}
```

Run with `uvicorn app:app --reload` or `night run app.py`.

See the [documentation](docs/README.md) for guides and the API reference.

