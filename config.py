"""Settings from environment / .env. One place for every knob."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase (REST / PostgREST). The secret key stays server-side; we only issue GETs.
    supabase_url: str
    supabase_secret_key: str
    supabase_table: str = "ai_leads"

    # Public URL of this server, ending in /mcp.
    mcp_server_url: str = "http://localhost:8000/mcp"

    # Google OAuth client (type "Web application").
    google_client_id: str = ""
    google_client_secret: str = ""
    # Stable secret for signing the tokens FastMCP issues to clients. Required on Lambda.
    jwt_signing_key: str | None = None

    # Local testing only: no sign-in at all. Never set this on a deployed server.
    auth_disabled: bool = False

    # Shown on the Terms / Privacy pages. Optional.
    contact_email: str = ""

    # DynamoDB table for OAuth state. Empty -> FastMCP's local encrypted file store (dev only).
    oauth_table: str = ""
    aws_region: str | None = None

    # Tool calls allowed per client IP per minute.
    rate_limit_per_minute: int = 2

    @property
    def base_url(self) -> str:
        return self.mcp_server_url.removesuffix("/mcp")
