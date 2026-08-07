import { cp, mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";

const root = process.cwd();
const out = resolve(root, "netlify/functions/_python");

await rm(out, { recursive: true, force: true });
await mkdir(out, { recursive: true });
await cp(resolve(root, "../../night.py"), resolve(out, "night.py"));
await cp(resolve(root, "../../night_web.py"), resolve(out, "night_web.py"));
await cp(resolve(root, "python/app.py"), resolve(out, "app.py"));

console.log("Prepared Night Python sources for the Netlify function bundle.");
