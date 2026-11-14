"""Portfolio demo: typed prompt → Google sign-in → live AI jobs in Barcelona from the deployed MCP.

uv run --with rich python portfolio/demo.py            # starts right away
DEMO_WAIT=1 uv run --with rich python portfolio/demo.py  # waits for /tmp/ai-jobs-demo.go
"""
# ruff: noqa: E402

import asyncio
import os
import subprocess
import sys
import time
import warnings
import webbrowser
from pathlib import Path

os.environ.setdefault("FASTMCP_LOG_LEVEL", "WARNING")  # hide OAuth URL logs on camera
warnings.filterwarnings("ignore", message="Using in-memory token storage")

from fastmcp import Client
from fastmcp.client.auth import OAuth
from key_value.aio.stores.memory import MemoryStore
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Sign-in opens in a new Chrome window instead of a tab.
webbrowser.register(
    "chrome-new-window",
    None,
    webbrowser.GenericBrowser(["open", "-na", "Google Chrome", "--args", "--new-window", "%s"]),
    preferred=True,
)

URL = "https://colrcdcmzfsme424n4wr4dehfi0mehor.lambda-url.eu-central-1.on.aws/mcp"
PROMPT = "Find the most recent AI jobs in Barcelona"
console = Console()


def type_out(text: str, delay: float = 0.045) -> None:
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    print()


async def main() -> None:
    console.clear()
    console.print(
        Panel.fit(
            "[bold]AI Jobs MCP[/]  ·  remote MCP server on AWS Lambda  ·  live Supabase data",
            border_style="bright_blue",
        )
    )
    console.print("\n[bold cyan]you ›[/] ", end="")
    type_out(PROMPT)
    time.sleep(0.6)

    console.print(f"\n[dim]connecting to[/] {URL}")
    console.print("[yellow]🔐 Sign-in required → opening browser (AI Jobs consent → Google)…[/]")
    auth = OAuth(
        URL, client_name="AI Jobs demo", token_storage=MemoryStore()
    )  # fresh: always signs in
    async with Client(URL, auth=auth) as client:
        tools = [t.name for t in await client.list_tools()]
        subprocess.run(["osascript", "-e", 'tell application "Terminal" to activate'], check=False)
        console.print(f"[green]✓ signed in[/]  ·  tools: {', '.join(tools)}\n")
        time.sleep(0.8)

        console.print(
            "[bold magenta]tool ›[/] search_leads(location='Barcelona', query='AI', newest first)"
        )
        with console.status("querying live data…"):
            result = (
                await client.call_tool(
                    "search_leads",
                    {"location": "Barcelona", "query": "AI", "limit": 8, "sort_by": "found_at"},
                )
            ).data

    table = Table(
        title=f"Recent AI jobs in Barcelona  ·  {result['total']} matches",
        title_style="bold",
        border_style="bright_blue",
        show_lines=False,
    )
    for col, style in [
        ("Role", "bold"),
        ("Company", "cyan"),
        ("Remote", ""),
        ("Seniority", ""),
        ("Score", "green"),
        ("Found", "dim"),
    ]:
        table.add_column(col, style=style)
    for lead in result["leads"]:
        table.add_row(
            lead["title"][:48],
            lead["company"],
            lead.get("remote_policy") or "",
            lead.get("seniority") or "",
            str(lead.get("score") or ""),
            lead["found_at"][:10],
        )
    console.print(table)
    console.print(
        "\n[dim]read-only · Google sign-in · 2 tool calls/min/IP · AWS Lambda eu-central-1[/]"
    )


if __name__ == "__main__":
    console.clear()
    while os.environ.get("DEMO_WAIT") and not Path("/tmp/ai-jobs-demo.go").exists():
        time.sleep(0.2)
    asyncio.run(main())
    Path("/tmp/ai-jobs-demo.done").touch()
