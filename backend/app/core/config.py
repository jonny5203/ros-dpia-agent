"""Application settings (pydantic-settings).

All secrets come from the environment (compose `env_file: ../.env`). No value
here is a real secret — defaults exist only so a misconfigured box boots far
enough to report what's missing.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────
    app_name: str = "Kommune DPIA & ROS Copilot"
    env: str = "dev"
    debug: bool = False
    app_secret_key: SecretStr = SecretStr("change-me")  # signs the session cookie
    cors_origins: str = "http://localhost"

    # ── OpenRouter (chat + embeddings, sole MVP provider) ────────────────
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "anthropic/claude-sonnet-4.5"
    embed_model: str = "openai/text-embedding-3-large"
    embed_dim: int = 3072

    # ── Relational DB / vector store / queue ─────────────────────────────
    # Defaults match infra/docker-compose.yml fallbacks so the stack connects
    # even without a .env (the api still reports degraded without OPENROUTER_API_KEY).
    database_url: str = "postgresql+asyncpg://dpia:dpia_dev_change_me@postgres:5432/dpia"
    qdrant_url: str = "http://qdrant:6333"
    redis_url: str = "redis://redis:6379/0"

    # ── MinIO (original uploaded files) ──────────────────────────────────
    minio_endpoint: str = "http://minio:9000"
    minio_access_key: str = ""
    minio_secret_key: SecretStr = SecretStr("")
    minio_bucket: str = "kommune-docs"
    minio_secure: bool = False

    # ── Keycloak (BFF / OIDC — wired in Phase 1) ─────────────────────────
    keycloak_url: str = "http://keycloak:8080"
    keycloak_public_url: str = "http://localhost:8080"
    keycloak_realm: str = "sandefjord"
    keycloak_client_id: str = "dpia-bff"
    keycloak_client_secret: SecretStr = SecretStr("")

    # ── BFF callbacks ────────────────────────────────────────────────────
    # Where the browser should land after /auth/login and /auth/logout.
    # localhost (not the container host) because these are browser-facing.
    public_base_url: str = "http://localhost"

    # ── Derived helpers ──────────────────────────────────────────────────
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def openrouter_api_key_value(self) -> str | None:
        """The raw key, or None if unset (so we never send an empty Bearer)."""
        value = self.openrouter_api_key.get_secret_value()
        return value or None

    # ── Keycloak OIDC endpoints ──────────────────────────────────────────
    # The dual-URL rule lives here, so every consumer gets it right:
    #   - *_public  → browser redirects (resolved on the user's laptop)
    #   - *_internal → server-to-server calls from the api container
    @property
    def keycloak_realm_path(self) -> str:
        return f"/realms/{self.keycloak_realm}"

    @property
    def keycloak_issuer(self) -> str:
        # Must match the `iss` claim in minted tokens → use the PUBLIC url.
        return f"{self.keycloak_public_url}{self.keycloak_realm_path}"

    @property
    def keycloak_authorization_endpoint(self) -> str:
        return (
            f"{self.keycloak_public_url}{self.keycloak_realm_path}"
            "/protocol/openid-connect/auth"
        )

    @property
    def keycloak_token_endpoint(self) -> str:
        # Server-to-server: internal url (faster, no network hairpin).
        return (
            f"{self.keycloak_url}{self.keycloak_realm_path}"
            "/protocol/openid-connect/token"
        )

    @property
    def keycloak_jwks_uri(self) -> str:
        # Server-to-server: Keycloak's public signing keys.
        return (
            f"{self.keycloak_url}{self.keycloak_realm_path}"
            "/protocol/openid-connect/certs"
        )

    @property
    def keycloak_end_session_endpoint(self) -> str:
        # Browser-facing logout.
        return (
            f"{self.keycloak_public_url}{self.keycloak_realm_path}"
            "/protocol/openid-connect/logout"
        )

    @property
    def public_callback_url(self) -> str:
        # The redirect_uri Keycloak sends the browser back to after login.
        return f"{self.public_base_url}/auth/callback"

    @property
    def minio_secret_key_value(self) -> str:
        return self.minio_access_key.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
