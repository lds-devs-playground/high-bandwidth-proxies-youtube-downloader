"""Centralised configuration loaded from environment variables.

In Google Cloud Run, secrets stored in **Secret Manager** are injected into the
container as environment variables via ``--set-secrets`` (and plain config via
``--set-env-vars``). This module reads them in one place so the rest of the app
never touches ``os.environ`` directly.

Example Cloud Run wiring (in the deploy workflow)::

    gcloud run jobs update JOB \
      --set-env-vars   PROVIDER=smartproxy,VIDEO_URLS="https://youtu.be/...,..." \
      --set-secrets    SMARTPROXY_USERNAME=smartproxy-username:latest \
      --set-secrets    SMARTPROXY_PASSWORD=smartproxy-password:latest \
      --set-secrets    YOUTUBE_API_KEY=youtube-api-key:latest
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _split(name: str) -> list[str]:
    """Parse a comma/newline/space separated env var into a clean list."""
    raw = os.environ.get(name, "")
    parts = raw.replace("\n", ",").replace(" ", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


@dataclass
class SmartProxyConfig:
    gateway: str = ""
    username: str = ""
    password: str = ""
    api_url: str = ""
    country_format: str = ""

    @classmethod
    def from_env(cls) -> "SmartProxyConfig":
        return cls(
            gateway=_get("SMARTPROXY_GATEWAY"),
            username=_get("SMARTPROXY_USERNAME"),
            password=_get("SMARTPROXY_PASSWORD"),
            api_url=_get("SMARTPROXY_API_URL"),
            country_format=_get("SMARTPROXY_COUNTRY_FORMAT"),
        )


@dataclass
class WebshareConfig:
    token: str = ""
    username: str = ""
    password: str = ""
    gateway: str = ""

    @classmethod
    def from_env(cls) -> "WebshareConfig":
        return cls(
            token=_get("WEBSHARE_TOKEN"),
            username=_get("WEBSHARE_USERNAME"),
            password=_get("WEBSHARE_PASSWORD"),
            gateway=_get("WEBSHARE_GATEWAY"),
        )


@dataclass
class DataImpulseConfig:
    gateway: str = ""
    username: str = ""
    password: str = ""
    country_format: str = ""

    @classmethod
    def from_env(cls) -> "DataImpulseConfig":
        return cls(
            gateway=_get("DATAIMPULSE_GATEWAY"),
            username=_get("DATAIMPULSE_USERNAME"),
            password=_get("DATAIMPULSE_PASSWORD"),
            country_format=_get("DATAIMPULSE_COUNTRY_FORMAT"),
        )


@dataclass
class YouTubeConfig:
    """YouTube Data API credentials (content-owner service account or API key)."""

    api_key: str = ""
    sa_json: str = ""
    sa_file: str = ""
    content_owner_id: str = ""

    @classmethod
    def from_env(cls) -> "YouTubeConfig":
        return cls(
            api_key=_get("YOUTUBE_API_KEY"),
            sa_json=_get("YOUTUBE_SA_JSON"),
            sa_file=_get("YOUTUBE_SA_FILE") or _get("GOOGLE_APPLICATION_CREDENTIALS"),
            content_owner_id=_get("YOUTUBE_CONTENT_OWNER_ID"),
        )

    @property
    def enabled(self) -> bool:
        """True when any credential is configured to query the API."""
        return bool(self.api_key or self.sa_json or self.sa_file or self.content_owner_id)


@dataclass
class VisibilityConfig:
    """Decoupled logging/persistence/callback wiring (Pub/Sub + Firestore)."""

    job_id: str = ""
    origin_id: str = ""
    callback_url: str = ""
    pubsub_topic: str = ""
    firestore_collection: str = ""
    firestore_database: str = "audio-download-jobs"
    result_bucket: str = ""
    result_prefix: str = ""

    @classmethod
    def from_env(cls) -> "VisibilityConfig":
        return cls(
            job_id=_get("JOB_ID"),
            origin_id=_get("ORIGIN_ID"),
            callback_url=_get("CALLBACK_URL"),
            pubsub_topic=_get("PUBSUB_TOPIC"),
            firestore_collection=_get("FIRESTORE_COLLECTION"),
            firestore_database=_get("FIRESTORE_DATABASE", "audio-download-jobs") or "audio-download-jobs",
            result_bucket=_get("RESULT_BUCKET"),
            result_prefix=_get("RESULT_PREFIX"),
        )


@dataclass
class Settings:
    """Full application configuration resolved from the environment."""

    # Job inputs / behaviour.
    provider: str = "smartproxy"
    video_urls: list[str] = field(default_factory=list)
    output_dir: str = "downloads"
    quality: str = "192"
    max_attempts: int = 8

    # Geo-restriction (YouTube Data API) + bot-check bypass.
    youtube_api_key: str = ""
    verify_country: bool = True
    cookies_file: str = ""

    # GCP context (set automatically by the deploy workflow).
    gcp_project_id: str = ""
    environment: str = "development"

    # Provider credentials (from Secret Manager).
    smartproxy: SmartProxyConfig = field(default_factory=SmartProxyConfig)
    webshare: WebshareConfig = field(default_factory=WebshareConfig)
    dataimpulse: DataImpulseConfig = field(default_factory=DataImpulseConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    visibility: VisibilityConfig = field(default_factory=VisibilityConfig)

    @classmethod
    def from_env(cls) -> "Settings":
        provider = _get("PROVIDER", "smartproxy").lower() or "smartproxy"
        try:
            max_attempts = int(_get("MAX_ATTEMPTS", "8") or "8")
        except ValueError:
            max_attempts = 8

        return cls(
            provider=provider,
            video_urls=_split("VIDEO_URLS"),
            output_dir=_get("OUTPUT_DIR", "downloads") or "downloads",
            quality=_get("AUDIO_QUALITY", "192") or "192",
            max_attempts=max_attempts,
            youtube_api_key=_get("YOUTUBE_API_KEY"),
            verify_country=_get("VERIFY_COUNTRY", "true").lower() not in {"false", "0", "no"},
            cookies_file=_get("COOKIES_FILE"),
            gcp_project_id=_get("GOOGLE_PROJECT_ID") or _get("GCP_PROJECT_ID"),
            environment=_get("ENVIRONMENT", "development") or "development",
            smartproxy=SmartProxyConfig.from_env(),
            webshare=WebshareConfig.from_env(),
            dataimpulse=DataImpulseConfig.from_env(),
            youtube=YouTubeConfig.from_env(),
            visibility=VisibilityConfig.from_env(),
        )
