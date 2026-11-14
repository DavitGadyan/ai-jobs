import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from leads import LeadsClient, Schema, build_params, filter_param, keyword_filter

SPEC = {
    "definitions": {
        "ai_leads": {
            "properties": {
                "job_id": {"format": "text", "description": "Note:\nThis is a Primary Key.<pk/>"},
                "title": {"format": "text"},
                "company": {"format": "text"},
                "score": {"format": "smallint"},
                "found_at": {"format": "timestamp with time zone"},
                "required_skills": {"format": "text[]"},
            }
        }
    }
}
SCHEMA = Schema.from_openapi(SPEC, "ai_leads")


def test_schema_detects_primary_key_and_arrays():
    assert SCHEMA.primary_key == "job_id"
    assert SCHEMA.is_array("required_skills") and not SCHEMA.is_array("title")
    with pytest.raises(RuntimeError):
        Schema.from_openapi(SPEC, "missing")


@pytest.mark.parametrize(
    ("column", "spec", "expected"),
    [
        ("title", "AI Engineer", "eq.AI Engineer"),
        ("company", {"op": "ilike", "value": "open"}, "ilike.*open*"),
        ("score", {"op": "gte", "value": 70}, "gte.70"),
        ("company", ["A", 'B "x"'], 'in.("A","B \\"x\\"")'),
        ("required_skills", "Python", 'ov.{"Python"}'),
        ("required_skills", {"op": "contains", "value": ["a", "b"]}, 'cs.{"a","b"}'),
        ("title", {"op": "is_null"}, "is.null"),
        ("title", {"op": "is_null", "value": False}, "not.is.null"),
    ],
)
def test_filter_param(column, spec, expected):
    assert filter_param(SCHEMA, column, spec) == (column, expected)


@pytest.mark.parametrize("filters", [{"nope": 1}, {"title": {"op": "delete", "value": 1}}])
def test_rejects_unknown_columns_and_ops(filters):
    with pytest.raises(ToolError):
        build_params(SCHEMA, None, filters)


def test_keyword_filter_strips_postgrest_syntax():
    expr = keyword_filter(SCHEMA, 'ml,) or(title.eq."x"')
    assert expr.startswith("(or(") and '"' not in expr and ",)" not in expr
    assert expr.count("or(") == 4  # one group per word: ml / or / title.eq. / x
    assert keyword_filter(SCHEMA, " ,() ") is None


@respx.mock
async def test_search_caps_limit_and_reads_total():
    base = "https://x.supabase.co/rest/v1"
    respx.get(f"{base}/").mock(return_value=httpx.Response(200, json=SPEC))
    route = respx.get(f"{base}/ai_leads").mock(
        return_value=httpx.Response(
            200, json=[{"job_id": "1"}], headers={"content-range": "0-0/42"}
        )
    )
    client = LeadsClient("https://x.supabase.co", "key", "ai_leads")
    result = await client.search(query="ml", limit=500)
    params = route.calls.last.request.url.params
    assert params["limit"] == "100" and params["order"] == "found_at.desc.nullslast"
    assert result == {"total": 42, "offset": 0, "has_more": True, "leads": [{"job_id": "1"}]}
