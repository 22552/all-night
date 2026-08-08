import { cp, mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";

const root = process.cwd();
const pythonOut = resolve(root, "netlify/functions/_python");
const sharedOut = resolve(root, "netlify/functions/_shared");
const publicOut = resolve(root, "public");

await rm(pythonOut, { recursive: true, force: true });
await rm(sharedOut, { recursive: true, force: true });
await mkdir(pythonOut, { recursive: true });
await mkdir(sharedOut, { recursive: true });
await mkdir(publicOut, { recursive: true });

for (const name of ["night.py", "night_web.py", "night_request_info.py"]) {
  await cp(resolve(root, `../../${name}`), resolve(pythonOut, name));
}
await cp(resolve(root, "python/app.py"), resolve(pythonOut, "app.py"));
await cp(resolve(root, "../../night_node.mjs"), resolve(sharedOut, "night_node.mjs"));

console.log("Prepared Night Node/Pyodide sources for the Netlify function bundle.");
