"""Logo, Terms, Privacy and the footer added to FastMCP's consent page."""

import base64
from html import escape

from fastmcp import FastMCP
from fastmcp.server.auth.oauth_proxy import consent
from mcp.types import Icon
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response

from config import Settings

NAME = "AI Jobs"
LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="14" fill="#4f46e5"/>
<rect x="14" y="24" width="36" height="24" rx="4" fill="#fff"/>
<path d="M25 24v-4a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v4" fill="none" stroke="#fff" stroke-width="3"/>
<path d="M32 29l2.2 4.6 4.8.7-3.5 3.4.8 4.8-4.3-2.3-4.3 2.3.8-4.8-3.5-3.4 4.8-.7z" fill="#4f46e5"/>
</svg>"""
# data: URI so the logo also shows on the consent page, whose CSP only allows https:/data: images.
LOGO_URI = "data:image/svg+xml;base64," + base64.b64encode(LOGO_SVG.encode()).decode()
ICONS = [Icon(src=LOGO_URI, mimeType="image/svg+xml", sizes=["any"])]

TERMS = f"""
<h1>Terms of Service</h1>
<p>{NAME} gives AI assistants read-only access to job leads collected from public job boards
and company career pages.</p>
<h2>Access</h2>
<p>Anyone with a verified Google account can sign in. Access is read-only: the service never
creates, changes or deletes data on your behalf. Access can be suspended for abuse.</p>
<h2>Acceptable use</h2>
<p>Do not try to get around authentication, overload the service, or resell the data in bulk.
Job listings belong to their original publishers; follow each source's own terms when you apply.</p>
<h2>No warranty</h2>
<p>Leads are aggregated automatically and may be incomplete, outdated or wrong. The service is
provided "as is", without warranty of any kind, and may change or stop at any time.</p>
"""
PRIVACY = """
<h1>Privacy Policy</h1>
<h2>What we receive</h2>
<p>When you sign in with Google we receive your email address, whether it is verified, and your
name. We request no other Google data and never access Gmail, Drive or contacts.</p>
<h2>How we use it</h2>
<p>Only to decide whether to let you in and to show who is signed in. Sign-in tokens are stored
encrypted and expire automatically. Request logs are kept in AWS CloudWatch for operations.</p>
<h2>Sharing</h2>
<p>We do not sell or share your data. You can revoke access at any time from your Google account
(Security &rarr; Third-party connections).</p>
"""


def page(title: str, body: str, s: Settings) -> HTMLResponse:
    contact = (
        f'<p>Contact: <a href="mailto:{escape(s.contact_email)}">{escape(s.contact_email)}</a></p>'
        if s.contact_email
        else ""
    )
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<link rel="icon" href="{LOGO_URI}"><style>
:root{{color-scheme:light dark;--fg:#111827;--muted:#6b7280;--bg:#fff;--link:#4f46e5}}
@media (prefers-color-scheme:dark){{
:root{{--fg:#f3f4f6;--muted:#9ca3af;--bg:#0b0f19;--link:#a5b4fc}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,sans-serif}}
main{{max-width:680px;margin:0 auto;padding:48px 16px}}a{{color:var(--link)}}
header{{display:flex;align-items:center;gap:12px}}header img{{width:40px;height:40px}}
footer,.muted{{color:var(--muted);font-size:14px}}
</style></head><body><main>
<header><img src="{LOGO_URI}" alt=""><strong>{NAME}</strong></header>
{body}{contact}
<footer><a href="/">Home</a> · <a href="/terms">Terms</a> · <a href="/privacy">Privacy</a></footer>
</main></body></html>""")


def consent_footer(base_url: str) -> str:
    return (
        '<p style="text-align:center;font-size:13px;color:#6b7280;margin:16px 0">'
        f'By continuing you agree to the <a href="{base_url}/terms" target="_blank">Terms</a> '
        f'and <a href="{base_url}/privacy" target="_blank">Privacy Policy</a>. '
        "Access is read-only.</p>"
    )


def install(mcp: FastMCP, s: Settings) -> None:
    """Serve the brand pages and add the Terms/Privacy footer to the consent screen."""
    home = f"""<h1>{NAME} MCP</h1><p>Read-only search over AI job leads for Claude, Cursor and
other MCP clients. Sign in with any verified Google account.</p>
<p>Server URL: <code>{escape(s.mcp_server_url)}</code></p>"""
    routes = {
        "/": ("AI Jobs MCP", home),
        "/terms": ("Terms", TERMS),
        "/privacy": ("Privacy", PRIVACY),
    }
    for path, (title, body) in routes.items():
        mcp.custom_route(path, methods=["GET"])(_handler(title, body, s))

    @mcp.custom_route("/logo.svg", methods=["GET"])
    async def logo(_request: Request) -> Response:
        return Response(LOGO_SVG, media_type="image/svg+xml")

    render = consent.create_consent_html
    footer = consent_footer(s.base_url)

    def branded(*args, **kwargs) -> str:
        html = render(*args, **kwargs)
        head, sep, tail = html.rpartition("</body>")
        return head + footer + sep + tail if sep else html + footer

    consent.create_consent_html = branded


def _handler(title: str, body: str, s: Settings):
    async def handler(_request: Request) -> HTMLResponse:
        return page(title, body, s)

    return handler
