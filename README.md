# wiki-mcp

An MCP bridge to Rolf's Obsidian wiki through a separate `vault` command. Chat apps can search pages, read sources and stage edits using the same workflow as coding agents.

This public repository contains code only. It does not include Rolf's vault, credentials or deployment configuration. All page names and paths in examples are fictional.

## Requirements

- Python 3.13 or newer and uv.
- A separately installed wiki `vault` command for tool calls. This is not HashiCorp Vault. The backend is not included or downloadable through this project.
- A vault directory containing `AGENTS.md` for reading the rules.
- Tailscale with Funnel enabled for public serving, URL printing and token rotation. Local serving does not require Tailscale.

The bridge searches PATH for `vault`, then uses `~/.local/bin/vault` if it is not found. The backend must locate its own wiki and enforce its schema and review gate. The bridge inherits the working directory and environment. Setting the rules directory below does not change either the working directory or the backend's configuration.

## Install and run locally

These commands assume a POSIX shell and a clone named `wiki-mcp`:

```sh
cd wiki-mcp
uv sync --locked
uv run --locked wiki-mcp --help
export XDG_CONFIG_HOME="$PWD/.runtime/config"
export WIKI_MCP_VAULT_DIR="/absolute/path/to/example-vault"
uv run --locked wiki-mcp --local
```

Replace the placeholder rules directory for real tool use. Keep the real vault outside this clone. `--local` binds to `127.0.0.1:8766` without publishing it. Stop with Ctrl+C. If the port is occupied, set `WIKI_MCP_PORT` in both terminals to an unused port.

Without the external backend, the HTTP server still starts and lists tools. Wiki operations cannot work until the backend is installed and configured. There is no bundled demo backend.

### Connect a local client

In a second terminal, from the same clone, use this Python client to list the available tools without printing the secret URL:

```sh
export XDG_CONFIG_HOME="$PWD/.runtime/config"
uv run --locked python - <<'PY'
import asyncio
import os
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "wiki-mcp"
    secret = (config / "token").read_text().strip()
    port = os.environ.get("WIKI_MCP_PORT", "8766")
    async with streamable_http_client(f"http://127.0.0.1:{port}/{secret}/mcp") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            for tool in tools.tools:
                print(tool.name)

asyncio.run(main())
PY
```

The local endpoint is `http://127.0.0.1:<port>/<secret>/mcp`. A hosted chat app cannot normally reach it. Anyone with the secret URL can call all tools. Keep it out of issues, logs and screenshots.

## Configuration and commands

| Setting | Meaning |
| --- | --- |
| `WIKI_MCP_VAULT_DIR` | Directory containing `AGENTS.md`. Required when calling `wiki_read("AGENTS")`. A leading `~` is expanded. |
| `WIKI_MCP_PORT` | Local port. Default: `8766`. |
| `XDG_CONFIG_HOME` | Base configuration directory. Default: `~/.config`. The token lives under `wiki-mcp/token`. |

Tokens are generated when needed and written with mode `0600`. Keep the configuration directory private.

| Command | Behavior |
| --- | --- |
| `wiki-mcp` | Serve locally and publish through Tailscale Funnel. This is the default. |
| `wiki-mcp --local` | Serve locally without Funnel. |
| `wiki-mcp url` | Print the secret public connector URL using Tailscale status. |
| `wiki-mcp rotate` | Replace the token, then print the new public URL using Tailscale status. |
| `wiki-mcp --help` | Print command help. |

There are no `--demo`, `--funnel` or `--port` options. Use `--local` to avoid public serving and `WIKI_MCP_PORT` to select a port. The CLI does not validate unknown arguments.

Token rotation changes the file, not a running server's route. Stop the server before rotating, then restart it and update every connected app. If Tailscale status fails during rotation, the token has already been replaced.

## Tools and backend contract

The server exposes 14 tools over Streamable HTTP. Each backend command gets `--by <client>` appended and receives `VAULT_CLIENT` in its environment. The label is inferred from the HTTP agent header: `chatgpt`, `claude-ai` or `chat`. It is attribution, not authentication.

| MCP tool | Arguments after `vault` |
| --- | --- |
| `wiki_find(terms)` | `find <terms>` |
| `wiki_read(page)` | `read <page>` |
| `sources_search(terms)` | `sources search <terms>` |
| `sources_text(stub)` | `sources text <stub>` |
| `run_status()` | `run status` |
| `run_start(mode)` | `run start <mode>`; edit by default, also ask or nightly |
| `run_write(path, content)` | `run write <path>`; complete file content on stdin |
| `receipts_find(stub, words)` | `receipts find <stub> <words>` |
| `receipts_add(page, stub, quote, claim)` | `receipts add <page> <stub> <quote> --claim <claim>` |
| `receipts_check()` | `receipts check` |
| `wiki_index()` | `index` |
| `wiki_lint()` | `lint` |
| `run_finish(subject, summary)` | `run finish <subject> --summary <summary>` |
| `run_drop()` | `run drop` |

`wiki_read("AGENTS")` is the exception. It reads `AGENTS.md` directly from `WIKI_MCP_VAULT_DIR` rather than invoking the backend.

Read pages before editing. Open a run, follow the backend rules, write whole files, add source receipts for numerical claims, regenerate the index and lint before finishing. The backend decides whether changes reach the wiki or wait for Rolf's review. The bridge does not implement that gate. Read-only knowledge-base pages and their cited source notes remain backend features.

Arguments are passed without a shell. Stdout and nonempty stderr are returned to the client. A nonzero exit adds an `[exit <code>]` prefix rather than raising a tool error. A timeout returns a message after 300 seconds. Returned text is cut at 150,000 characters. Output is buffered before that cut, so this is not a memory limit. `AGENTS.md` is returned in full.

## Public serving

Use this only after installing and authenticating Tailscale and reviewing the backend's access rules:

```sh
uv run --locked wiki-mcp
```

In a second terminal with the same configuration:

```sh
uv run --locked wiki-mcp url
```

The public connector URL has the form `https://<host>/wiki/<secret>/mcp`. The bridge searches PATH for `tailscale`, then tries `/opt/homebrew/bin/tailscale`.

Serving configures a background Funnel path on HTTPS port 443. It attempts to remove `/wiki` on normal exit. Funnel command failures are not checked. A crash can leave the mapping configured. To remove it manually:

```sh
tailscale funnel --https=443 --set-path=/wiki off
```

Use a dedicated `/wiki` mapping. Startup can replace an existing mapping at that path. No launch-agent configuration is included.

## Privacy and limits

- The secret URL grants access to every tool, including source reads and staged writes. There is no OAuth, per-client authorization or separate write approval inside the bridge.
- Tool annotations and model instructions do not enforce backend policies. The backend must enforce staging, safe paths, receipts, schema rules and its review gate. The bridge is not a sandbox.
- Retrieved sources can contain prompt injection. Only connect trusted clients.
- The bridge logs one stderr line per request (method, path with the secret replaced by `<token>`, status, client) and one per backend call (the first two backend arguments, outcome, time, client). With Funnel on, it also prints the public host name. Treat these logs as private. Backend stderr still goes to the client. A backend, proxy or chat provider may record sensitive content.
- Real vault operations, public Funnel deployment and hosted chat connectors are not verified by the local check below.
- Ignore rules are not a privacy guarantee. Keep real vault pages and credentials outside this repository. Git history needs separate review before publication.
- There are no scientific results, figures, benchmarks or associated paper in this tree.

## Local verification

Ran `uv sync --locked` in a newly created environment with Python 3.13.15. Installation and CLI help succeeded. Local serving with `--local` succeeded on an unused loopback port. The exact Python client above initialized MCP and listed all 14 tools. The server stopped cleanly.

The external backend was not installed or invoked. Public serving, URL printing, rotation and Funnel removal were skipped because they need Rolf's authenticated Tailscale setup. No paid services, GPUs or large downloads were used. Build caches, the environment and generated token were removed afterward. No automated tests were added. Earlier demo and wheel verification does not describe this trimmed code.

## How this was built

AI coding agents did much of the implementation under Rolf's direction. Rolf chose the command-based wiki workflow and kept staged edits and review decisions in the backend. This cleanup removes private deployment details and keeps the existing runtime behavior. It adds no compatibility layers or tests. Local checks do not establish that Rolf independently reviewed every generated line. Rolf's final review and live deployment checks remain pending.

## License

MIT. Copyright (c) 2026 Rolf. See `LICENSE`.
