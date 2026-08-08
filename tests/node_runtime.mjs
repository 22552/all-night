import assert from "node:assert/strict";
import { copyFile, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createNightNodeHandler, NIGHT_NODE_SUPPORT } from "../night_node.mjs";

assert.equal(NIGHT_NODE_SUPPORT.node, ">=22");
assert.deepEqual(NIGHT_NODE_SUPPORT.tested, [22, 24]);
assert.equal(NIGHT_NODE_SUPPORT.pyodide, "314.0.3");

const root = resolve(new URL("..", import.meta.url).pathname);
const dir = await mkdtemp(join(tmpdir(), "night-node-"));

try {
  for (const name of ["night.py", "night_web.py", "night_request_info.py"]) {
    await copyFile(join(root, name), join(dir, name));
  }

  await writeFile(join(dir, "app.py"), `
from night import Night

app = Night()

@app.get("/hello")
def hello():
    return {"hello": "node"}

@app.get("/users/<int:user_id>")
def user(user_id: int):
    return {"id": user_id}

@app.post("/echo")
async def echo(req):
    return {"body": await req.text()}
`, "utf8");

  const handler = createNightNodeHandler({ sourceDir: dir });
  await handler.ready();

  const hello = await handler(new Request("https://night.test/hello"));
  assert.equal(hello.status, 200);
  assert.deepEqual(await hello.json(), { hello: "node" });

  const echo = await handler(new Request("https://night.test/echo", {
    method: "POST",
    headers: { "content-type": "text/plain" },
    body: "from-node",
  }));
  assert.equal(echo.status, 200);
  assert.deepEqual(await echo.json(), { body: "from-node" });

  const [one, two] = await Promise.all([
    handler(new Request("https://night.test/users/1")),
    handler(new Request("https://night.test/users/2")),
  ]);
  assert.deepEqual(await one.json(), { id: 1 });
  assert.deepEqual(await two.json(), { id: 2 });

  console.log(`Night Node runtime OK on ${process.version}`);
} finally {
  await rm(dir, { recursive: true, force: true });
}
