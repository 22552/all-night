# Cloudflare build notes

Cloudflare Python Workers installs Python dependencies without building arbitrary source distributions. To avoid the `all-night` Git dependency being rejected as a source-only package, this deployment template has no runtime Python package dependencies.

During the Cloudflare build step, `package.json` downloads the pinned `night.py` source file and copies the portable runtime adapters into `src/`. `pywrangler deploy` then sees Night as local Python modules instead of a package that must be built inside the Pyodide dependency environment.

The pinned Night source commit is `9a241910b8f888a67720c8b80bde1b139604faff`.
