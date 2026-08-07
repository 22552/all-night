"""Minimal Night application for Vercel's Python ASGI runtime."""

from night import Night

app = Night()


@app.get("/")
def index():
    return {
        "framework": "Night",
        "runtime": "Vercel Python",
        "message": "Hello from Night on Vercel",
    }


@app.get("/users/<int:user_id>")
def user(user_id: int):
    return {"id": user_id}


@app.get("/health")
def health():
    return {"ok": True}
