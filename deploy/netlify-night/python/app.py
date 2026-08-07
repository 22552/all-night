"""Minimal Night application used by the Netlify + Pyodide template."""

from night import Night

app = Night()


@app.get("/")
def index():
    return {
        "framework": "Night",
        "runtime": "Netlify Functions + Pyodide",
        "message": "Hello from Night on Netlify",
    }


@app.get("/users/<int:user_id>")
def user(user_id: int):
    return {"id": user_id}


@app.post("/echo")
async def echo(req):
    return {"received": await req.text()}


@app.get("/health")
def health():
    return {"ok": True}
