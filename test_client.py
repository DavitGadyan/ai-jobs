"""Call the running server from the terminal.

uv run test_client.py                              # local, AUTH_DISABLED=true
uv run test_client.py --oauth                      # Google sign-in once; tokens cached after that
uv run test_client.py --oauth --url https://<function-url>/mcp
uv run test_client.py --logout                     # forget cached tokens
"""

import asyncio
import shutil
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.auth import OAuth
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)

url = sys.argv[sys.argv.index("--url") + 1] if "--url" in sys.argv else "http://localhost:8000/mcp"
# FastMCP's client keeps tokens in memory by default, so every run would sign in again.
CACHE = Path.home() / ".cache" / "ai-jobs-mcp" / "oauth"


def token_store() -> FileTreeStore:
    CACHE.mkdir(parents=True, exist_ok=True, mode=0o700)
    return FileTreeStore(
        data_directory=CACHE,
        key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(CACHE),
        collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(CACHE),
    )


async def main() -> None:
    auth = OAuth(url, client_name="AI Jobs test client", token_storage=token_store())
    async with Client(url, auth=auth if "--oauth" in sys.argv else None) as client:
        print("tools:", [t.name for t in await client.list_tools()])
        print("whoami:", (await client.call_tool("whoami")).data)
        result = (await client.call_tool("search_leads", {"query": "engineer", "limit": 3})).data
        print(f"search: {result['total']} matches")
        for lead in result["leads"]:
            print(f"  - {lead['title']} @ {lead['company']} ({lead['source']})")


if __name__ == "__main__":
    if "--logout" in sys.argv:
        shutil.rmtree(CACHE, ignore_errors=True)
        print(f"Removed cached tokens in {CACHE}")
    else:
        asyncio.run(main())
