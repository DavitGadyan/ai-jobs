"""Google sign-in for MCP clients: any verified Google account gets read-only access."""

from fastmcp.server.auth import AuthContext
from fastmcp.server.auth.providers.google import GoogleProvider
from key_value.aio.stores.dynamodb import DynamoDBStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from config import Settings


def build_google_auth(s: Settings) -> GoogleProvider:
    """OAuth proxy: MCP clients register with us, users log in at Google.

    On Lambda, OAuth state (client registrations, upstream tokens) must survive cold
    starts and be shared across instances, so it lives in DynamoDB, encrypted.
    """
    storage = None
    if s.oauth_table:
        if not s.jwt_signing_key:
            raise RuntimeError("JWT_SIGNING_KEY is required when OAUTH_TABLE is set")
        storage = FernetEncryptionWrapper(
            DynamoDBStore(table_name=s.oauth_table, region_name=s.aws_region, auto_create=False),
            source_material=s.jwt_signing_key,
            salt="ai-jobs-mcp-oauth-storage",
        )
    return GoogleProvider(
        client_id=s.google_client_id,
        client_secret=s.google_client_secret,
        base_url=s.base_url,
        required_scopes=["openid", "email"],
        jwt_signing_key=s.jwt_signing_key,
        client_storage=storage,
        # Consent screen (logo + Terms) on first sign-in per client, then auto-approved.
        require_authorization_consent="remember",
    )


def verified_google_email(ctx: AuthContext) -> bool:
    """AuthCheck: the caller signed in with a Google account whose email is verified."""
    claims = (ctx.token.claims if ctx.token else None) or {}
    # Google's tokeninfo sends "true" (string); userinfo sends true (bool).
    return bool(claims.get("email")) and str(claims.get("email_verified")).lower() == "true"
