"""Per-IP rate limit on tool calls (fixed one-minute window).

On Lambda the counters live in the OAuth DynamoDB table (its `ttl` attribute expires them),
so the limit holds across instances. Locally they live in memory.
"""

import json
import time
from collections import Counter

from aiobotocore.session import get_session
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import Middleware
from starlette.requests import Request

WINDOW = 60


def client_ip(request: Request) -> str:
    """Caller IP. Lambda Web Adapter passes the Function URL's request context, which can't be
    spoofed; otherwise use the last X-Forwarded-For hop (the one our proxy appended)."""
    try:
        return json.loads(request.headers["x-amzn-request-context"])["http"]["sourceIp"]
    except (KeyError, TypeError, ValueError):
        pass
    if forwarded := request.headers.get("x-forwarded-for"):
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


class RateLimit(Middleware):
    def __init__(self, per_minute: int, table: str = "", region: str | None = None):
        self.per_minute, self.table, self.region = per_minute, table, region
        self._dynamo = None
        self._local: Counter = Counter()
        self._local_window = 0

    async def _count(self, ip: str, window: int) -> int:
        """Increment and return this IP's call count for the window."""
        if not self.table:
            if window != self._local_window:
                self._local, self._local_window = Counter(), window
            self._local[ip] += 1
            return self._local[ip]
        if self._dynamo is None:  # one client per Lambda instance, reused across calls
            self._dynamo = await get_session().create_client("dynamodb", self.region).__aenter__()
        response = await self._dynamo.update_item(
            TableName=self.table,
            Key={"collection": {"S": "ratelimit"}, "key": {"S": f"{ip}#{window}"}},
            UpdateExpression="ADD hits :one SET #ttl = :ttl",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={
                ":one": {"N": "1"},
                ":ttl": {"N": str((window + 2) * WINDOW)},
            },
            ReturnValues="UPDATED_NEW",
        )
        return int(response["Attributes"]["hits"]["N"])

    async def on_call_tool(self, context, call_next):
        try:
            request = get_http_request()
        except RuntimeError:  # stdio / in-memory transport: no IP to limit
            return await call_next(context)
        now = int(time.time())
        window = now // WINDOW
        if await self._count(client_ip(request), window) > self.per_minute:
            retry = (window + 1) * WINDOW - now
            raise ToolError(
                f"Rate limit: {self.per_minute} tool calls per minute per IP. Retry in {retry}s."
            )
        return await call_next(context)
