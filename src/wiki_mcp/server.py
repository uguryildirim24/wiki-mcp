"""The MCP tools: each one runs a `vault` command as the calling app."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import client

VAULT = shutil.which("vault") or str(Path.home() / ".local/bin/vault")
TIMEOUT_S = 300
MAX_OUT = 150_000

INSTRUCTIONS = """\
Rolf's wiki: notes, decisions and sources, synthesized into pages.
Reading: wiki_find, then wiki_read the pages; when the wiki is thin, sources_search and sources_text read the raw
chats and sources behind it. Answer short and direct, name the pages ([[Page]]) and say plainly when the wiki doesn't know.
Changing the wiki: only inside a run. run_start("edit") opens one and returns the rules; follow them exactly
(AGENTS.md via wiki_read("AGENTS") is the schema). Write whole files with run_write, add receipts for every number
with a unit, run wiki_index and wiki_lint until 0 errors, then run_finish. A script decides whether the change
reaches the wiki or waits for Rolf's review; tell him which from run_finish's reply. File back an answer only when
it's worth keeping: a comparison, a decision, a timeline, a connection across pages, or something he'd ask again.
One run at a time across all of Rolf's agents; if one is open, say so instead of forcing it."""

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

mcp = MCPServer(name="rolf-wiki", title="Rolf's wiki", instructions=INSTRUCTIONS)


def vault(*args: str, stdin: str | None = None) -> str:
    started = time.monotonic()
    who = client.get()
    try:
        done = subprocess.run([VAULT, *args, "--by", who], input=stdin, capture_output=True, text=True,
                              timeout=TIMEOUT_S, env={**os.environ, "VAULT_CLIENT": who})
        out = (done.stdout + (f"\n{done.stderr}" if done.stderr.strip() else "")).strip()
        outcome = "ok" if done.returncode == 0 else f"exit {done.returncode}"
    except subprocess.TimeoutExpired:
        out, outcome = f"vault {args[0]} took longer than {TIMEOUT_S}s", "timeout"
    ms = int((time.monotonic() - started) * 1000)
    print(f"{time.strftime('%H:%M:%S')}  vault {' '.join(args[:2])[:60]:<40} {outcome:<8} {ms:>6}ms  {who}",
          file=sys.stderr, flush=True)
    if outcome != "ok" and outcome != "timeout":
        out = f"[{outcome}] {out}"
    if len(out) > MAX_OUT:
        out = out[:MAX_OUT] + f"\n… cut at {MAX_OUT} characters"
    return out or "(no output)"


@mcp.tool(annotations=READ)
def wiki_find(terms: str) -> str:
    """Wiki and read-only knowledge-base pages whose name or text contain all the terms,
    best first, with a one-line summary each."""
    return vault("find", terms)


@mcp.tool(annotations=READ)
def wiki_read(page: str) -> str:
    """A wiki page by name ("Example project") or path ("Wiki/entities/Example project").
    "AGENTS" returns the vault schema. Also reads read-only knowledge-base pages and their cited
    source notes. A name in both prefers the wiki page. Inside an open run it reads the run's copy."""
    if page.strip().removesuffix(".md").lower() == "agents":
        return (Path(os.environ["WIKI_MCP_VAULT_DIR"]).expanduser() / "AGENTS.md").read_text(encoding="utf-8")
    return vault("read", page)


@mcp.tool(annotations=READ)
def sources_search(terms: str) -> str:
    """Full-text search over Rolf's raw sources (Claude and ChatGPT chats, sessions, clips). Returns stub names."""
    return vault("sources", "search", terms)


@mcp.tool(annotations=READ)
def sources_text(stub: str) -> str:
    """The full text of one raw source stub, e.g. "raw/sources/example-note.md"."""
    return vault("sources", "text", stub)


@mcp.tool(annotations=READ)
def run_status() -> str:
    """The open run across all of Rolf's agents, if any."""
    return vault("run", "status")


@mcp.tool(annotations=WRITE)
def run_start(mode: Literal["edit", "ask", "nightly"] = "edit") -> str:
    """Open a run (a private copy of the wiki) and get the rules for it. Use "edit" to file an answer or change pages."""
    return vault("run", "start", mode)


@mcp.tool(annotations=WRITE)
def run_write(path: str, content: str) -> str:
    """Write a whole markdown file in the open run, under Wiki/ (e.g. "Wiki/analyses/Example plan.md").
    Read the page first and send the complete new text; this replaces the file in the run's copy only."""
    return vault("run", "write", path, stdin=content)


@mcp.tool(annotations=READ)
def receipts_find(stub: str, words: str) -> str:
    """Find exact lines in a cited source that contain a number you want to add, to use as a receipt."""
    return vault("receipts", "find", stub, words)


@mcp.tool(annotations=WRITE)
def receipts_add(page: str, stub: str, quote: str, claim: str) -> str:
    """Tie a number on a page to exact words from a source. claim is 10+ characters copied from your sentence."""
    return vault("receipts", "add", page, stub, quote, "--claim", claim)


@mcp.tool(annotations=READ)
def receipts_check() -> str:
    """Check every receipt in the open run. Must show 0 failed before run_finish."""
    return vault("receipts", "check")


@mcp.tool(annotations=WRITE)
def wiki_index() -> str:
    """Regenerate Wiki/index.md in the open run after adding or renaming pages."""
    return vault("index")


@mcp.tool(annotations=READ)
def wiki_lint() -> str:
    """Lint the wiki (the open run's copy if there is one). Must show 0 errors before run_finish."""
    return vault("lint")


@mcp.tool(annotations=WRITE)
def run_finish(subject: str, summary: str) -> str:
    """Commit the open run and hand it to the gate. subject like "Update example plan"; summary is 2-5 plain
    lines for Rolf. The reply says whether it reached the wiki or waits for his review."""
    return vault("run", "finish", subject, "--summary", summary)


@mcp.tool(annotations=WRITE)
def run_drop() -> str:
    """Throw away the open run you started, without changing the wiki."""
    return vault("run", "drop")
