from night import Night

app = Night()


@app.get("/")
def index():
    return {
        "framework": "Night",
        "runtime": "Browser + Pyodide",
        "message": "Night is running entirely in your browser",
    }


@app.get("/hello/<name>")
def hello(name: str):
    return {"hello": name}


@app.post("/echo")
async def echo(req):
    return {"received": await req.text()}
