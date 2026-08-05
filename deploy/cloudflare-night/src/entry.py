from night import HTMLResponse, Night
from web_runtime import CloudflareWorkerMixin
from workers import Response, WorkerEntrypoint


app = Night()
_todos: list[dict] = [
    {"id": 1, "title": "Deploy Night to Cloudflare", "done": True},
    {"id": 2, "title": "Add a todo", "done": False},
]
_next_id = 3

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
<h1>Night ToDo</h1><p class="sub">Night + Cloudflare Python Workers</p>
<form id="form"><input id="title" placeholder="What needs doing?" autocomplete="off"><button class="add">Add</button></form>
<ul id="list"></ul>
<script>
const list=document.querySelector('#list'), form=document.querySelector('#form'), input=document.querySelector('#title');
async function refresh(){const r=await fetch('/api/todos');const todos=await r.json();list.innerHTML='';for(const todo of todos){const li=document.createElement('li');li.className=todo.done?'done':'';li.innerHTML=`<input type="checkbox" ${todo.done?'checked':''}><span class="title"></span><button class="delete">Delete</button>`;li.querySelector('.title').textContent=todo.title;li.querySelector('input').onchange=async e=>{await fetch('/api/todos/'+todo.id,{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify({done:e.target.checked})});refresh()};li.querySelector('.delete').onclick=async()=>{await fetch('/api/todos/'+todo.id,{method:'DELETE'});refresh()};list.append(li)}}
form.onsubmit=async e=>{e.preventDefault();const title=input.value.trim();if(!title)return;await fetch('/api/todos',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({title})});input.value='';refresh()};refresh();
</script>
</body>
</html>"""


@app.get("/")
def index():
    return HTMLResponse(PAGE)


@app.get("/api/todos")
def list_todos():
    return list(_todos)


@app.post("/api/todos")
async def create_todo(req):
    global _next_id
    data = await req.json()
    title = str(data.get("title", "")).strip() if isinstance(data, dict) else ""
    if not title:
        return {"error": "title is required"}
    todo = {"id": _next_id, "title": title[:200], "done": False}
    _next_id += 1
    _todos.append(todo)
    return todo


@app.patch("/api/todos/<int:id>")
async def update_todo(req, id: int):
    data = await req.json()
    for todo in _todos:
        if todo["id"] == id:
            if isinstance(data, dict) and "title" in data:
                title = str(data["title"]).strip()
                if title:
                    todo["title"] = title[:200]
            if isinstance(data, dict) and "done" in data:
                todo["done"] = bool(data["done"])
            return todo
    return {"error": "todo not found"}


@app.delete("/api/todos/<int:id>")
def delete_todo(id: int):
    for index, todo in enumerate(_todos):
        if todo["id"] == id:
            return _todos.pop(index)
    return {"error": "todo not found"}


class Default(CloudflareWorkerMixin, WorkerEntrypoint):
    app = app
    web_response_class = Response
