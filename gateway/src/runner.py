"""Cloud Run Job execution client.

Translates a validated API request into a fire-and-forget ``run_job`` call with
per-run environment overrides. The gateway never blocks on the download — it
kicks off the execution and returns immediately. Status is observed later via
Firestore (the worker's visibility layer).
"""

from __future__ import annotations

from .config import GatewaySettings


class JobRunError(RuntimeError):
    """Raised when the Cloud Run Job could not be started."""


class JobRunner:
    """Thin wrapper around the Cloud Run Admin v2 ``run_job`` RPC."""

    def __init__(self, settings: GatewaySettings) -> None:
        self._settings = settings
        self._client = None  # lazily created so imports stay cheap / testable

    def _get_client(self):
        if self._client is None:
            from google.cloud import run_v2

            self._client = run_v2.JobsClient()
        return self._client

    def run(self, env_overrides: dict[str, str]) -> str:
        """Start the worker Job with the given env vars; return execution name."""
        settings = self._settings
        if not (settings.project_id and settings.job_name):
            raise JobRunError("Gateway is missing GOOGLE_PROJECT_ID or JOB_NAME.")

        from google.cloud import run_v2

        env_vars = [run_v2.EnvVar(name=k, value=v) for k, v in env_overrides.items()]
        overrides = run_v2.RunJobRequest.Overrides(
            container_overrides=[
                run_v2.RunJobRequest.Overrides.ContainerOverride(env=env_vars)
            ],
            task_count=1,
        )
        request = run_v2.RunJobRequest(name=settings.job_path, overrides=overrides)

        try:
            operation = self._get_client().run_job(request=request)
        except Exception as exc:  # noqa: BLE001 - surface a clean API error
            raise JobRunError(f"Failed to start Cloud Run Job: {exc}") from exc

        # The execution resource name is available on the operation metadata.
        try:
            return operation.metadata.name  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return ""
