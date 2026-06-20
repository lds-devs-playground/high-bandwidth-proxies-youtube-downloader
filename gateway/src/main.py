"""FastAPI control-plane gateway for the YouTube→MP3 worker Job.

Responsibilities (control plane only):
  * Authenticate callers and attribute every request to an ``origin_id``.
  * Validate the payload and mint a unique ``JOB_ID``.
  * Start the Cloud Run worker Job with per-run env overrides (fire-and-forget).
  * Expose read-only status by reading the worker's Firestore collection.

It deliberately does **no** downloading/transcoding — that stays in the worker,
preserving the stateless-worker + decoupled-visibility design.

AuthN is handled at the platform edge: the service is deployed with
``--no-allow-unauthenticated`` so only callers holding a valid Cloud Run IAM
identity token (internal service accounts) can reach it.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException, status

from .config import GatewaySettings
from .models import CreateJobRequest, CreateJobResponse, JobStatusResponse
from .runner import JobRunError, JobRunner
from .store import StatusStore

app = FastAPI(title="YouTube Downloader Gateway", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    settings = GatewaySettings.from_env()
    app.state.settings = settings
    app.state.runner = JobRunner(settings)
    app.state.store = StatusStore(settings)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/jobs", response_model=CreateJobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(payload: CreateJobRequest) -> CreateJobResponse:
    settings: GatewaySettings = app.state.settings
    runner: JobRunner = app.state.runner

    job_id = uuid.uuid4().hex
    effective_origin = payload.origin_id

    env_overrides: dict[str, str] = {
        "JOB_ID": job_id,
        "ORIGIN_ID": effective_origin,
        "VIDEO_URLS": ",".join(payload.urls),
        "PROVIDER": payload.provider or settings.default_provider,
    }
    if payload.callback_url:
        env_overrides["CALLBACK_URL"] = str(payload.callback_url)
    if payload.quality:
        env_overrides["AUDIO_QUALITY"] = payload.quality
    if payload.max_attempts:
        env_overrides["MAX_ATTEMPTS"] = str(payload.max_attempts)

    try:
        execution = runner.run(env_overrides)
    except JobRunError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    return CreateJobResponse(
        job_id=job_id,
        status="queued",
        origin_id=effective_origin,
        execution=execution or None,
    )


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str) -> JobStatusResponse:
    store: StatusStore = app.state.store

    if not store.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Status store is not configured.",
        )

    doc = store.get(job_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found."
        )

    return JobStatusResponse(
        job_id=job_id,
        status=str(doc.get("status", "unknown")),
        progress_percentage=float(doc.get("progress_percentage", 0.0) or 0.0),
        origin_id=str(doc.get("origin_id", "")),
        metadata=doc.get("metadata", {}) or {},
        timestamp=str(doc.get("timestamp", "")),
    )
