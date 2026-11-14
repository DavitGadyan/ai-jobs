"""Read-only access to the leads table through Supabase's REST API (PostgREST).

Only GET requests are ever sent. Every column name is checked against the live
schema and every value is quoted, so tool input cannot reshape the query.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Any

import httpx
from fastmcp.exceptions import ToolError

MAX_LIMIT = 100
STATS_PAGE = 1000
STATS_MAX_ROWS = 20_000

# Compact row for list views; get_lead returns every column.
SUMMARY_COLUMNS = [
    "job_id", "title", "company", "location", "remote_policy", "seniority", "source", "status",
    "score", "tier_label", "salary_text", "posted_at", "found_at", "url", "apply_url",
]  # fmt: skip
# Searched by the free-text `query`. Falls back to every text column if none exist.
KEYWORD_COLUMNS = [
    "title", "company", "location", "summary", "description", "role_family",
    "ai_stack", "company_one_liner", "what_they_do",
]  # fmt: skip

SCALAR_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "ilike"}
LIST_OPS = {"in": "in", "contains": "cs", "overlaps": "ov"}
OPS = sorted(SCALAR_OPS | LIST_OPS.keys() | {"is_null"})


@dataclass(frozen=True)
class Schema:
    columns: dict[str, str]  # name -> Postgres type, e.g. "text", "text[]", "smallint"
    primary_key: str

    @classmethod
    def from_openapi(cls, spec: dict, table: str) -> "Schema":
        definition = spec.get("definitions", {}).get(table)
        if not definition:
            raise RuntimeError(f"Table {table!r} is not exposed by the Supabase REST API")
        props = definition["properties"]
        pk = next((n for n, p in props.items() if "<pk/>" in p.get("description", "")), None)
        return cls({n: p.get("format", "") for n, p in props.items()}, pk or next(iter(props)))

    def is_array(self, column: str) -> bool:
        return self.columns[column].endswith("[]")

    def check(self, column: str) -> str:
        if column not in self.columns:
            raise ToolError(
                f"Unknown column {column!r}. Use describe_leads_schema to list columns."
            )
        return column

    def present(self, wanted: list[str]) -> list[str]:
        return [c for c in wanted if c in self.columns]


def quote(value: Any) -> str:
    """Quote one value for a PostgREST list/array literal."""
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def keyword_filter(schema: Schema, query: str) -> str | None:
    """`and=(or(...),or(...))`: every word must appear in at least one keyword column."""
    words = "".join(" " if ch in ',()"\\*' else ch for ch in query).split()
    columns = schema.present(KEYWORD_COLUMNS) or [
        c for c, t in schema.columns.items() if t == "text"
    ]
    if not words or not columns:
        return None
    groups = (",".join(f"{c}.ilike.*{w}*" for c in columns) for w in words)
    return "(" + ",".join(f"or({g})" for g in groups) + ")"


def filter_param(schema: Schema, column: str, spec: Any) -> tuple[str, str]:
    """Turn one filter into a PostgREST query param.

    spec forms: scalar -> eq (overlaps for array columns); list -> in (overlaps for arrays);
    {"op": <op>, "value": <v>} for anything else.
    """
    schema.check(column)
    if isinstance(spec, dict):
        op, value = spec.get("op", "eq"), spec.get("value")
    elif isinstance(spec, list):
        op, value = ("overlaps" if schema.is_array(column) else "in"), spec
    else:
        op, value = ("overlaps" if schema.is_array(column) else "eq"), spec

    if op == "is_null":
        return column, "is.null" if value in (None, True) else "not.is.null"
    if op in LIST_OPS:
        items = value if isinstance(value, list) else [value]
        inner = ",".join(quote(v) for v in items)
        return column, f"in.({inner})" if op == "in" else f"{LIST_OPS[op]}.{{{inner}}}"
    if op in SCALAR_OPS:
        if op == "ilike" and "*" not in str(value):
            value = f"*{value}*"
        return column, f"{op}.{value}"
    raise ToolError(f"Unknown op {op!r}. Allowed: {', '.join(OPS)}")


def build_params(schema: Schema, query: str | None, filters: dict[str, Any] | None) -> list:
    params = [filter_param(schema, col, spec) for col, spec in (filters or {}).items()]
    if query and (expr := keyword_filter(schema, query)):
        params.append(("and", expr))
    return params


def total_from(response: httpx.Response) -> int | None:
    """Content-Range looks like `0-19/345` or `*/0`."""
    total = response.headers.get("content-range", "").rpartition("/")[2]
    return int(total) if total.isdigit() else None


class LeadsClient:
    def __init__(self, url: str, key: str, table: str, http: httpx.AsyncClient | None = None):
        self.table = table
        self.http = http or httpx.AsyncClient(
            base_url=f"{url.rstrip('/')}/rest/v1",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=20,
        )
        self._schema: Schema | None = None

    async def _get(self, path: str, params=None, headers=None) -> httpx.Response:
        response = await self.http.get(path, params=params, headers=headers)
        if response.is_error:
            try:
                detail = response.json().get("message", response.text)
            except ValueError:
                detail = response.text
            raise ToolError(f"Supabase error {response.status_code}: {detail}")
        return response

    async def schema(self) -> Schema:
        if self._schema is None:
            spec = (await self._get("/")).json()
            self._schema = Schema.from_openapi(spec, self.table)
        return self._schema

    async def search(
        self,
        query: str | None = None,
        filters: dict[str, Any] | None = None,
        sort_by: str = "found_at",
        descending: bool = True,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        schema = await self.schema()
        limit = max(1, min(limit, MAX_LIMIT))
        direction = "desc" if descending else "asc"
        params = [
            *build_params(schema, query, filters),
            ("select", ",".join(schema.present(SUMMARY_COLUMNS)) or "*"),
            ("order", f"{schema.check(sort_by)}.{direction}.nullslast"),
            ("limit", str(limit)),
            ("offset", str(max(0, offset))),
        ]
        response = await self._get(f"/{self.table}", params, {"Prefer": "count=exact"})
        leads = response.json()
        total = total_from(response)
        has_more = total is not None and offset + len(leads) < total
        return {"total": total, "offset": offset, "has_more": has_more, "leads": leads}

    async def get(self, lead_id: str) -> dict | None:
        schema = await self.schema()
        params = {schema.primary_key: f"eq.{lead_id}", "select": "*", "limit": "1"}
        rows = (await self._get(f"/{self.table}", params)).json()
        return rows[0] if rows else None

    async def stats(self, column: str, filters: dict[str, Any] | None = None, top: int = 20):
        """Count leads per value of `column` (array columns count each element)."""
        schema = await self.schema()
        schema.check(column)
        base = [*build_params(schema, None, filters), ("select", column)]
        counts: Counter = Counter()
        scanned = 0
        while scanned < STATS_MAX_ROWS:
            page = [*base, ("limit", str(STATS_PAGE)), ("offset", str(scanned))]
            rows = (await self._get(f"/{self.table}", page)).json()
            for row in rows:
                value = row.get(column)
                counts.update(value if isinstance(value, list) else [value])
            scanned += len(rows)
            if len(rows) < STATS_PAGE:
                break
        return {
            "column": column,
            "rows_scanned": scanned,
            "truncated": scanned >= STATS_MAX_ROWS,
            "counts": [
                {"value": "(none)" if v is None else v, "count": n}
                for v, n in counts.most_common(top)
            ],
        }
