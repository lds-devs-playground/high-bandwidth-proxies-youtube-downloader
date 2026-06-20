"""Persistent storage of final job assets in Google Cloud Firestore.

Per the data-isolation requirement, only *final* assets (status, output URLs,
file paths, metadata) are written here — never the high-volume progress stream.
Each job is a document keyed by ``job_id`` in a configurable collection.
"""

from __future__ import annotations

import logging

from .events import JobEvent, JobStatus

logger = logging.getLogger(__name__)


class FirestoreStore:
    """Writes final job records to Firestore.

    The client is imported lazily and the store degrades to a no-op when no
    collection/project is configured, so local runs and tests work without GCP.
    """

    def __init__(self, project_id: str = "", collection: str = "", database: str = "(default)"):
        self.project_id = project_id
        self.collection = collection
        self.database = database or "(default)"
        self._client = None

        if self.collection:
            self._init_client()

    def _init_client(self) -> None:
        try:
            from google.cloud import firestore
        except ImportError:  # pragma: no cover - dependency missing
            logger.warning("google-cloud-firestore not installed; persistence disabled.")
            return

        try:
            kwargs = {"database": self.database}
            if self.project_id:
                kwargs["project"] = self.project_id
            self._client = firestore.Client(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not initialise Firestore client: %s", exc)
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def save_result(self, event: JobEvent) -> None:
        """Persist (merge) the final asset record for a job."""
        if not self.enabled:
            logger.debug("Firestore disabled; not persisting job %s", event.job_id)
            return
        try:
            from google.cloud import firestore

            doc = self._client.collection(self.collection).document(event.job_id)
            payload = event.to_dict()
            payload["updated_at"] = firestore.SERVER_TIMESTAMP
            doc.set(payload, merge=True)
            logger.info("Persisted job %s (%s) to Firestore", event.job_id, event.status.value)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist job %s to Firestore: %s", event.job_id, exc)

    def mark_failed(self, job_id: str, error: str, origin_id: str = "") -> None:
        """Convenience helper to record a failed job."""
        self.save_result(
            JobEvent(
                job_id=job_id,
                status=JobStatus.FAILED,
                progress_percentage=0.0,
                metadata={"error": error},
                origin_id=origin_id,
            )
        )
