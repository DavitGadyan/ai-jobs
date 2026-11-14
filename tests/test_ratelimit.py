import json

import pytest
from fastmcp.exceptions import ToolError
from starlette.requests import Request

import ratelimit
from ratelimit import RateLimit, client_ip


def make_request(headers: dict[str, str], host: str = "10.0.0.9") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (host, 1234)})


def test_client_ip_prefers_lambda_context_over_spoofable_headers():
    context = json.dumps({"http": {"sourceIp": "1.2.3.4"}})
    request = make_request({"x-amzn-request-context": context, "x-forwarded-for": "6.6.6.6"})
    assert client_ip(request) == "1.2.3.4"
    assert client_ip(make_request({"x-forwarded-for": "6.6.6.6, 5.5.5.5"})) == "5.5.5.5"
    assert client_ip(make_request({})) == "10.0.0.9"


async def test_third_call_in_a_minute_is_refused(monkeypatch):
    requests = {"a": make_request({"x-forwarded-for": "1.1.1.1"})}
    current = {"ip": "a"}
    monkeypatch.setattr(ratelimit, "get_http_request", lambda: requests[current["ip"]])
    monkeypatch.setattr(ratelimit.time, "time", lambda: 6000.0)
    limiter = RateLimit(per_minute=2)

    async def call_next(_context):
        return "ok"

    assert await limiter.on_call_tool(None, call_next) == "ok"
    assert await limiter.on_call_tool(None, call_next) == "ok"
    with pytest.raises(ToolError, match="2 tool calls per minute"):
        await limiter.on_call_tool(None, call_next)

    requests["b"] = make_request({"x-forwarded-for": "2.2.2.2"})  # other IPs unaffected
    current["ip"] = "b"
    assert await limiter.on_call_tool(None, call_next) == "ok"

    monkeypatch.setattr(ratelimit.time, "time", lambda: 6060.0)  # next window resets
    current["ip"] = "a"
    assert await limiter.on_call_tool(None, call_next) == "ok"


async def test_no_http_request_means_no_limit(monkeypatch):
    def no_request():
        raise RuntimeError

    monkeypatch.setattr(ratelimit, "get_http_request", no_request)
    limiter = RateLimit(per_minute=0)

    async def call_next(_context):
        return "ok"

    assert await limiter.on_call_tool(None, call_next) == "ok"
