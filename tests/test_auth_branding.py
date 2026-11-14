import os
from types import SimpleNamespace

import pytest
from fastmcp import Client

from auth import verified_google_email
from branding import consent, consent_footer


@pytest.mark.parametrize(
    ("claims", "ok"),
    [
        ({"email": "a@gmail.com", "email_verified": "true"}, True),  # tokeninfo form
        ({"email": "a@acme.io", "email_verified": True}, True),  # userinfo form
        ({"email": "a@gmail.com", "email_verified": "false"}, False),
        ({"email": "a@gmail.com"}, False),
        ({"email_verified": True}, False),
    ],
)
def test_any_verified_google_email_is_allowed(claims, ok):
    assert verified_google_email(SimpleNamespace(token=SimpleNamespace(claims=claims))) is ok


def test_no_token_is_denied():
    assert verified_google_email(SimpleNamespace(token=None)) is False


@pytest.fixture(scope="module")
def server():
    os.environ.setdefault("SUPABASE_URL", "https://x.supabase.co")
    os.environ.setdefault("SUPABASE_SECRET_KEY", "test")
    os.environ["AUTH_DISABLED"] = "true"
    import server as srv

    return srv


async def test_every_tool_is_read_only(server):
    async with Client(server.mcp) as client:
        tools = await client.list_tools()
    assert tools and all(t.annotations.read_only_hint for t in tools)


async def test_brand_pages_and_consent_footer(server):
    from starlette.testclient import TestClient

    with TestClient(server.app) as http:
        for path in ("/", "/terms", "/privacy"):
            response = http.get(path)
            assert response.status_code == 200 and "AI Jobs" in response.text
        assert http.get("/logo.svg").headers["content-type"].startswith("image/svg+xml")

    html = consent.create_consent_html(
        client_id="c", redirect_uri="http://x/cb", scopes=[], txn_id="t", csrf_token="k",
        server_name="AI Jobs", server_icon_url="data:image/svg+xml;base64,AA==",
    )  # fmt: skip
    assert consent_footer(server.settings.base_url) in html
    assert html.index("/terms") < html.index("</body>")
