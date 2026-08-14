"""Application settings, loaded from the environment.

Single source of truth for configuration — nothing else in the codebase reads
os.environ directly. Alembic pulls the DB URL from here too, so the connection
string isn't duplicated in alembic.ini.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    database_url: str = "postgresql://app:app@localhost:5432/app"
    redis_url: str = "redis://localhost:6379/0"
    supertokens_connection_uri: str = "http://localhost:3567"

    # The product name, in one place on this side. The frontend twin of this is
    # apps/web/src/lib/brand.ts.
    brand_name: str = "ayeayecaptain"

    # --- where we are ------------------------------------------------------
    # ONE origin for everything: the SPA, the API, the auth routes and object
    # storage all live behind it. That is what keeps the session cookie,
    # CORS and (later) S3 presigning simple, and it's why there is no second
    # hostname anywhere in this product. Caddy is what makes it true — see
    # infra/caddy/Caddyfile.
    #
    # Include the scheme: `http://localhost` in dev, `https://tasks.example.com`
    # in production. Compose passes the same SITE_URL to Caddy as its site
    # address, so one variable configures the whole deployment.
    site_url: str = "http://localhost"

    # Shared secret so only our API can talk to the SuperTokens core. Empty in
    # local dev (the core then allows unauthenticated callers); set in production.
    supertokens_api_key: str = ""

    # --- object storage (RustFS, S3-compatible) ---------------------------
    # `s3_endpoint` is what the API calls; `s3_public_endpoint` is what
    # presigned URLs are SIGNED AGAINST, because SigV4 covers the Host header.
    # Sign with the internal name and the browser's request fails the signature
    # check with an error that mentions nothing about hostnames.
    #
    # Both default to the site origin: Caddy fronts /media/*, so in dev and in
    # production alike the browser reaches storage on the same host as
    # everything else — which is why uploads need no CORS at all.
    s3_endpoint: str = "http://rustfs:9000"
    s3_public_endpoint: str = ""
    s3_access_key: str = "rustfsadmin"
    s3_secret_key: str = "rustfsadmin"
    s3_region: str = "us-east-1"
    # Named `media` on purpose: with path-style addressing the object URL is
    # literally /media/<key>, so Caddy forwards it untouched. Stripping the
    # prefix would invalidate every signature.
    s3_bucket: str = "media"

    # Presigned URL lifetimes. Short for reading — the URL is a bearer token
    # until it expires — and longer for upload, so a big file on a slow
    # connection can finish.
    s3_view_url_ttl: int = 300
    s3_upload_url_ttl: int = 3600

    # Enforced in step 3, against the object that actually landed.
    attachment_max_bytes: int = 50 * 1024 * 1024

    # --- email -------------------------------------------------------------
    # Empty SMTP_HOST disables sending: the app logs what it would have sent
    # and carries on. That is a SUPPORTED deployment, not a broken one — see
    # the invite-link escape hatch in PLAN.md §2.4. Dev points at Mailpit.
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_start_tls: bool = False
    # Falls back to a brand-derived address when unset — see mailer.from_address().
    mail_from: str = ""

    @property
    def api_domain(self) -> str:
        """What SuperTokens is told the API's origin is. Same as the site: the
        API is not on a host of its own and never will be."""
        return self.site_url

    @property
    def website_domain(self) -> str:
        """What SuperTokens is told the frontend's origin is."""
        return self.site_url

    @property
    def s3_public_url(self) -> str:
        """Where the browser reaches storage. Defaults to the site origin,
        because Caddy routes /media/* to RustFS on the same host."""
        return self.s3_public_endpoint or self.site_url

    @property
    def cors_origins(self) -> list[str]:
        """Single origin, so this list has exactly one entry and CORS is a
        formality. It exists so a dev setup that bypasses Caddy (talking to
        the API on :8000 directly) still works."""
        return sorted({self.site_url})

    @property
    def database_url_async(self) -> str:
        """
        DATABASE_URL is stored in the plain libpq form (postgresql://...) so it
        works with psql and other tools. SQLAlchemy's async engine and Alembic
        need the asyncpg driver spelled out.
        """
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)


settings = Settings()
