import json
import uuid

from night import HTMLResponse, Night
from workers import Response as WorkersResponse, WorkerEntrypoint
from workers.rpc import python_from_rpc as _python_from_rpc, python_to_rpc as _python_to_rpc


app = Night()
_kv = None

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Night ToDo</title>
<style>
body{font-family:system-ui,sans-serif;max-width:680px;margin:48px auto;padding:0 16px;background:#111;color:#eee}
h1{margin-bottom:4px}.sub{color:#999;margin-top:0}form{display:flex;gap:8px;margin:28px 0}input{flex:1;padding:12px;border-radius:10px;border:1px solid #444;background:#1c1c1c;color:#fff}button{padding:10px 14px;border:0;border-radius:10px;cursor:pointer}ul{list-style:none;padding:0}li{display:flex;gap:10px;align-items:center;padding:12px;border-bottom:1px solid #333}.title{flex:1}.done .title{text-decoration:line-through;color:#777}.delete{background:#512;color:#fdd}.add{background:#eee;color:#111}
</style>
</head>
<body>
<h1>Night ToDo</h1><p class="sub">Night + Cloudflare Python Workers + KV</p>
<form id="form"><input id="title" placeholder="What needs doing?" autocomplete="off"><button class="add">Add</button></form>
<ul id="list"></ul>
<script>
const list=document.querySelector('#list'), form=document.querySelector('#form'), input=document.querySelector('#title');
async function refresh(){const r=await fetch('/api/todos');const todos=await r.json();list.innerHTML='';for(const todo of todos){const li=document.createElement('li');li.className=todo.done?'done':'';li.innerHTML=`<input type="checkbox" ${todo.done?'checked':''}><span class="title"></span><button class="delete">Delete</button>`;li.querySelector('.title').textContent=todo.title;li.querySelector('input').onchange=async e=>{await fetch('/api/todos/'+todo.id,{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify({done:e.target.checked})});refresh()};li.querySelector('.delete').onclick=async()=>{await fetch('/api/todos/'+todo.id,{method:'DELETE'});refresh()};list.append(li)}}
form.onsubmit=async e=>{e.preventDefault();const title=input.value.trim();if(!title)return;await fetch('/api/todos',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({title})});input.value='';refresh()};refresh();
</script>
</body>
</html>"""


def _todo_key(todo_id: str) -> str:
    return f"todo:{todo_id}"


async def _get_todo(todo_id: str):
    raw = await _kv.get(_todo_key(todo_id))
    if raw is None:
        return None
    return json.loads(str(raw))


@app.get("/")
def index():
    return HTMLResponse(PAGE)


@app.get("/api/todos")
async def list_todos():
    result = await _kv.list(prefix="todo:")
    keys = result.get("keys", [])
    todos = []
    for item in keys:
        name = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
        if not name:
            continue
        raw = await _kv.get(name)
        if raw is not None:
            todos.append(json.loads(str(raw)))
    todos.sort(key=lambda todo: todo.get("created", ""), reverse=True)
    return todos


@app.post("/api/todos")
async def create_todo(req):
    data = await req.json()
    title = str(data.get("title", "")).strip() if isinstance(data, dict) else ""
    if not title:
        return {"error": "title is required"}

    todo_id = uuid.uuid4().hex
    todo = {"id": todo_id, "title": title[:200], "done": False, "created": todo_id}
    await _kv.put(_todo_key(todo_id), json.dumps(todo, separators=(",", ":")))
    return todo


@app.patch("/api/todos/<id>")
async def update_todo(req, id: str):
    todo = await _get_todo(id)
    if todo is None:
        return {"error": "todo not found"}
    data = await req.json()
    if isinstance(data, dict) and "title" in data:
        title = str(data["title"]).strip()
        if title:
            todo["title"] = title[:200]
    if isinstance(data, dict) and "done" in data:
        todo["done"] = bool(data["done"])
    await _kv.put(_todo_key(id), json.dumps(todo, separators=(",", ":")))
    return todo


@app.delete("/api/todos/<id>")
async def delete_todo(id: str):
    todo = await _get_todo(id)
    if todo is None:
        return {"error": "todo not found"}
    await _kv.delete(_todo_key(id))
    return todo


@app.rpc("todo_count")
async def todo_count():
    result = await _kv.list(prefix="todo:")
    keys = result.get("keys", [])
    return len(keys)


# Python Workers snapshot top-level execution at deploy time. Keep Cloudflare
# SDK imports and deterministic router finalization here so the first live
# request does not pay those one-time costs. No I/O or request state is touched.
_EDGE_PREWARM_REFS = (WorkersResponse, _python_from_rpc, _python_to_rpc)
for _method in tuple(app._dynamic_method_routes):
    app._rebuild_dynamic_matcher(_method)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        global _kv
        _kv = self.env.TODOS
        return await app.cloudflare_fetch(request, response_class=WorkersResponse)

    async def night_rpc(self, method, args=None, kwargs=None):
        global _kv
        _kv = self.env.TODOS
        return await app.cloudflare_rpc(method, args, kwargs)
