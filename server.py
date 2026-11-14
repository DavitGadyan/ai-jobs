"""AI Jobs MCP server: read-only search over job leads stored in Supabase.

Local:   uv run server.py                  -> http://localhost:8000/mcp
Lambda:  uvicorn server:app (via Lambda Web Adapter, see run.sh)
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import AuthMiddleware
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import PlainTextResponse

import branding
from auth import build_google_auth, verified_google_email
from config import Settings
from leads import OPS, LeadsClient
from ratelimit import RateLimit

settings = Settings()
leads = LeadsClient(settings.supabase_url, settings.supabase_secret_key, settings.supabase_table)

if not settings.auth_disabled and not settings.google_client_id:
    raise RuntimeError("Set GOOGLE_CLIENT_ID/SECRET, or AUTH_DISABLED=true for local testing only")

mcp = FastMCP(
    "AI Jobs",
    website_url=f"{settings.base_url}/",
    icons=branding.ICONS,
    instructions=(
        "Read-only search over AI job leads collected from many sources. "
        "Call describe_leads_schema first if you need to filter on a column the typed "
        f"parameters don't cover. Limit: {settings.rate_limit_per_minute} tool calls per minute; "
        "prefer one well-filtered search over many small ones."
    ),
    auth=None if settings.auth_disabled else build_google_auth(settings),
    middleware=[
        RateLimit(settings.rate_limit_per_minute, settings.oauth_table, settings.aws_region),
        *([] if settings.auth_disabled else [AuthMiddleware(auth=verified_google_email)]),
    ],
)
branding.install(mcp, settings)
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

Filters = Annotated[
    dict[str, Any] | None,
    Field(
        description=(
            "Extra filters by column. Value forms: scalar (equals; for array columns, contains"
            ' it), list (any of), or {"op": ..., "value": ...} with op in '
            f"{', '.join(OPS)}. Example: "
            '{"tier": {"op": "lte", "value": 2}, "ats": ["greenhouse", "lever"]}'
        )
    ),
]


@mcp.tool(annotations=READ_ONLY)
def whoami() -> dict:
    """Show the signed-in Google account and the MCP client it came through."""
    token = get_access_token()
    if token is None:
        return {"authenticated": False}
    claims = token.claims or {}
    return {"email": claims.get("email"), "name": claims.get("name"), "client_id": token.client_id}


@mcp.tool(annotations=READ_ONLY)
async def describe_leads_schema() -> dict:
    """List the leads table's columns and their types, for building `filters`."""
    schema = await leads.schema()
    return {"table": leads.table, "primary_key": schema.primary_key, "columns": schema.columns}


@mcp.tool(annotations=READ_ONLY)
async def search_leads(
    query: Annotated[str | None, "Keywords; every word must match title/company/summary/…"] = None,
    company: Annotated[str | None, "Company name, partial match"] = None,
    location: Annotated[str | None, "Location, partial match"] = None,
    source: Annotated[str | None, "Where the lead was found, exact"] = None,
    status: Annotated[str | None, "Lead status, exact"] = None,
    seniority: Annotated[str | None, "Seniority, exact"] = None,
    remote_policy: Annotated[str | None, "Remote policy, exact"] = None,
    skills: Annotated[
        list[str] | None, "Required skills; matches leads needing any of them"
    ] = None,
    min_score: Annotated[int | None, "Minimum fit score"] = None,
    found_within_days: Annotated[int | None, "Only leads found in the last N days"] = None,
    filters: Filters = None,
    sort_by: Annotated[str, "Column to sort by"] = "found_at",
    descending: bool = True,
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict:
    """Search job leads. Returns compact rows plus `total`; use get_lead for full detail."""
    since = found_within_days and (datetime.now(UTC) - timedelta(days=found_within_days))
    typed = {
        "company": company and {"op": "ilike", "value": company},
        "location": location and {"op": "ilike", "value": location},
        "source": source,
        "status": status,
        "seniority": seniority,
        "remote_policy": remote_policy,
        "required_skills": skills,
        "score": None if min_score is None else {"op": "gte", "value": min_score},
        "found_at": since and {"op": "gte", "value": since.isoformat()},
    }
    merged = {k: v for k, v in typed.items() if v} | (filters or {})
    return await leads.search(query, merged, sort_by, descending, limit, offset)


@mcp.tool(annotations=READ_ONLY)
async def get_lead(job_id: Annotated[str, "The lead's job_id from search results"]) -> dict:
    """Get every field of one lead: description, requirements, skills gap, research notes."""
    lead = await leads.get(job_id)
    if lead is None:
        raise ToolError(f"No lead with job_id {job_id!r}")
    return lead


@mcp.tool(annotations=READ_ONLY)
async def lead_stats(
    group_by: Annotated[str, "Column to count by, e.g. source, company, status, required_skills"],
    filters: Filters = None,
    top: Annotated[int, Field(ge=1, le=100)] = 20,
) -> dict:
    """Count leads per value of a column (array columns such as skills count each item)."""
    return await leads.stats(group_by, filters, top)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> PlainTextResponse:
    """Unauthenticated liveness probe (Lambda Web Adapter readiness check)."""
    return PlainTextResponse("ok")


# Stateless JSON responses: any Lambda instance can answer any request.
app = mcp.http_app(path="/mcp", stateless_http=True, json_response=True)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
