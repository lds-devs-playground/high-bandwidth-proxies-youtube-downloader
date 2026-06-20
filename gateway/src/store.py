"""Read-only Firestore access for job status lookups.

The worker owns writes to this collection (final assets + lifecycle). The
gateway only reads, so callers can poll ``GET /jobs/{id}`` without touching the
worker or its infrastructure directly.
"""

from __future__ import annotations

from .config import GatewaySettings


class StatusStore:
    """Lazily-initialised Firestore reader keyed by ``job_id``."""

    def __init__(self, settings: GatewaySettings) -> None:
        self._settings = settings
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.Client(
                project=self._settings.project_id or None,
                database=self._settings.firestore_database,
            )
        return self._client

    @property
    def enabled(self) -> bool:
        return bool(self._settings.firestore_collection)

    def get(self, job_id: str) -> dict | None:
        """Return the stored job document, or ``None`` if not found."""
        if not self.enabled:
            return None
        doc = (
            self._get_client()
            .collection(self._settings.firestore_collection)
            .document(job_id)
            .get()
        )
        if not doc.exists:
            return None
        return doc.to_dict() or {}
