# One-click deployment

The recommended path is the official Cloudflare Deploy Button in this template's README.

Cloudflare will:

1. ask you to sign in,
2. copy this template into a repository you control,
3. configure the Worker project,
4. run the build/deploy commands from `package.json`, and
5. deploy it through Workers Builds.

This template is isolated inside `deploy/cloudflare-night` so Cloudflare can treat the subdirectory as the root of the copied project.
