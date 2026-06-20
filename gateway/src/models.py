"""Request/response schemas for the gateway API."""

from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl, field_validator


class CreateJobRequest(BaseModel):
    """Payload to enqueue a new download job."""

    urls: list[str] = Field(..., min_length=1, description="YouTube video URLs to download.")
    provider: str | None = Field(
        default=None, description="Proxy provider override (smartproxy|webshare)."
    )
    callback_url: HttpUrl | None = Field(
        default=None, description="URL the worker POSTs the final result to."
    )
    origin_id: str = Field(
        ..., min_length=1, description="Caller-supplied correlation id for the requesting service."
    )
    quality: str | None = Field(default=None, description="Target MP3 bitrate, e.g. '192'.")
    max_attempts: int | None = Field(default=None, ge=1, le=50)

    @field_validator("urls")
    @classmethod
    def _strip_urls(cls, value: list[str]) -> list[str]:
        cleaned = [u.strip() for u in value if u and u.strip()]
        if not cleaned:
            raise ValueError("at least one non-empty URL is required")
        return cleaned

    @field_validator("provider")
    @classmethod
    def _valid_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in {"smartproxy", "webshare"}:
            raise ValueError("provider must be 'smartproxy' or 'webshare'")
        return normalized


class CreateJobResponse(BaseModel):
    job_id: str
    status: str
    origin_id: str
    execution: str | None = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress_percentage: float = 0.0
    origin_id: str = ""
    metadata: dict = Field(default_factory=dict)
    timestamp: str = ""
