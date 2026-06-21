"""Gateway configuration loaded from environment variables.

Mirrors the worker's pattern: in Cloud Run, plain config arrives via
``--set-env-vars`` and any secret (e.g. the API keys) via ``--set-secrets``.
The gateway is the control plane — it only needs to know how to reach the
worker Job and the Firestore collection the worker writes its results to.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class GatewaySettings:
    """Resolved gateway configuration."""

    # GCP / Cloud Run Job targeting.
    project_id: str = ""
    region: str = "us-central1"
    job_name: str = ""

    # Firestore (read-only status lookups).
    firestore_collection: str = "download_jobs"
    firestore_database: str = "(default)"

    # Per-run defaults forwarded to the worker.
    default_provider: str = "dataimpulse"

    environment: str = "development"

    @classmethod
    def from_env(cls) -> "GatewaySettings":
        return cls(
            project_id=_get("GOOGLE_PROJECT_ID") or _get("GCP_PROJECT_ID"),
            region=_get("REGION", "us-central1") or "us-central1",
            job_name=_get("JOB_NAME"),
            firestore_collection=_get("FIRESTORE_COLLECTION", "download_jobs")
            or "download_jobs",
            firestore_database=_get("FIRESTORE_DATABASE", "(default)") or "(default)",
            default_provider=_get("DEFAULT_PROVIDER", "dataimpulse") or "dataimpulse",
            environment=_get("ENVIRONMENT", "development") or "development",
        )

    @property
    def job_path(self) -> str:
        return f"projects/{self.project_id}/locations/{self.region}/jobs/{self.job_name}"
