from night import Night
from web_runtime import CloudflareWorkerMixin
from workers import Response, WorkerEntrypoint


app = Night()


@app.get("/")
def index():
    return {
        "framework": "Night",
        "runtime": "Cloudflare Python Workers",
        "deployed": True,
    }


@app.get("/hello/<name>")
def hello(name: str):
    return {"hello": name}


@app.post("/echo")
async def echo(req):
    return {"echo": await req.json()}


class Default(CloudflareWorkerMixin, WorkerEntrypoint):
    app = app
    web_response_class = Response
