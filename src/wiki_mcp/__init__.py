"""wiki-mcp: Rolf's wiki for chat apps (ChatGPT, claude.ai, Cowork), as MCP tools over the `vault` command.

wiki-mcp            serve on 127.0.0.1 and publish it with a Tailscale Funnel on :8443 (launchd runs this)
wiki-mcp --local    serve on 127.0.0.1 only, for testing
wiki-mcp url        print the connector URL to paste into ChatGPT or claude.ai
wiki-mcp rotate     replace the secret in the URL (connected apps stop working until updated)

Every tool shells out to `vault`, so chat apps read and change the wiki exactly the way Grok Bot, Codex and Claude
do: changes happen in a run, and the vault's gate decides what reaches main.
"""

from __future__ import annotations

import contextvars
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "wiki-mcp"
TOKEN_FILE = CONFIG_DIR / "token"
PORT = int(os.environ.get("WIKI_MCP_PORT", "8766"))
FUNNEL_PORT = int(os.environ.get("WIKI_MCP_FUNNEL_PORT", "8443"))

client = contextvars.ContextVar("client", default="chat")


def token() -> str:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return rotate_token()


def rotate_token() -> str:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(value + "\n")
    TOKEN_FILE.chmod(0o600)
    return value


def tailscale() -> str:
    return shutil.which("tailscale") or "/opt/homebrew/bin/tailscale"


def tailnet_host() -> str:
    out = subprocess.run([tailscale(), "status", "--json"], capture_output=True, text=True, check=True).stdout
    return json.loads(out)["Self"]["DNSName"].rstrip(".")


def mcp_path() -> str:
    return f"/{token()}/mcp"


def public_url() -> str:
    return f"https://{tailnet_host()}:{FUNNEL_PORT}{mcp_path()}"


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return
    if args and args[0] == "url":
        print(public_url())
        return
    if args and args[0] == "rotate":
        rotate_token()
        print(f"new URL: {public_url()}")
        return
    serve(local_only="--local" in args)


def client_from(user_agent: str) -> str:
    ua = user_agent.lower()
    if "openai" in ua or "chatgpt" in ua:
        return "chatgpt"
    if "claude" in ua or "anthropic" in ua:
        return "claude-ai"
    return "chat"


def with_client_and_log(app, secret: str):
    """Names the calling app for `vault --by`, and logs one line per request with the secret redacted."""

    async def wrapped(scope, receive, send):
        if scope["type"] != "http":
            return await app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        who = client_from(headers.get("user-agent", ""))
        status = {"code": 0}

        async def snd(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)

        reset = client.set(who)
        try:
            await app(scope, receive, snd)
        finally:
            client.reset(reset)
            path = scope["path"].replace(secret, "<token>")
            print(f"{time.strftime('%H:%M:%S')}  {scope['method']} {path} -> {status['code']}  {who}",
                  file=sys.stderr, flush=True)

    return wrapped


def build_app(local_only: bool):
    import logging

    from mcp.server.transport_security import TransportSecuritySettings

    from .server import mcp

    hosts = [f"127.0.0.1:{PORT}", f"localhost:{PORT}"]
    if not local_only:
        host = tailnet_host()
        hosts += [host, f"{host}:{FUNNEL_PORT}"]
    app = mcp.streamable_http_app(
        streamable_http_path=mcp_path(),
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=["https://chatgpt.com", "https://chat.openai.com", "https://claude.ai"],
        ),
    )
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.WARNING)
    return with_client_and_log(app, token())


def start_funnel() -> subprocess.Popen:
    # Foreground funnel inside a watchdog shell: it stops when this process exits, so the public URL only exists
    # while wiki-mcp runs. Port 8443 keeps it clear of pro-mcp's funnel on 443.
    watchdog = (
        f'"{tailscale()}" funnel --https={FUNNEL_PORT} {PORT} >/dev/null 2>&1 & f=$!; '
        'trap \'kill $f 2>/dev/null\' EXIT HUP INT TERM; '
        f'while kill -0 {os.getpid()} 2>/dev/null && kill -0 $f 2>/dev/null; do sleep 1; done'
    )
    return subprocess.Popen(["/bin/sh", "-c", watchdog], start_new_session=True)


def stop_funnel(funnel: subprocess.Popen | None) -> None:
    if funnel and funnel.poll() is None:
        os.killpg(funnel.pid, signal.SIGTERM)
        try:
            funnel.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(funnel.pid, signal.SIGKILL)


def serve(local_only: bool) -> None:
    import uvicorn

    app = build_app(local_only)
    print(f"local:   http://127.0.0.1:{PORT}/<token>/mcp", file=sys.stderr, flush=True)
    funnel = None if local_only else start_funnel()
    if funnel:
        print(f"public:  https://{tailnet_host()}:{FUNNEL_PORT}/<token>/mcp  (wiki-mcp url)", file=sys.stderr, flush=True)
    try:
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    finally:
        stop_funnel(funnel)
