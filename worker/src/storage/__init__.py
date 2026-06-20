"""Decoupled visibility layer: progress (Pub/Sub) + persistence (Firestore) +
cross-project completion (callback).

``JobReporter`` is the single entry point the worker uses:

* ``progress()`` -> publishes a transient event to Pub/Sub only.
* ``complete()`` / ``fail()`` -> publishes the final event, persists it to
  Firestore, and POSTs it to the requester's ``callback_url``.
"""

from __future__ import annotations

import logging

from .callback import post_callback
from .events import JobEvent, JobStatus
from .firestore import FirestoreStore
from .bucket import AudioStreamService
from .gcs import GCSUploader
from .pubsub import ProgressPublisher

logger = logging.getLogger(__name__)

__all__ = [
    "JobEvent",
    "JobStatus",
    "ProgressPublisher",
    "FirestoreStore",
    "AudioStreamService",
    "GCSUploader",
    "post_callback",
    "JobReporter",
]


class JobReporter:
    """Coordinates transient progress and persistent completion for one job."""

    def __init__(
        self,
        job_id: str,
        publisher: ProgressPublisher | None = None,
        store: FirestoreStore | None = None,
        callback_url: str = "",
        origin_id: str = "",
    ):
        self.job_id = job_id
        self.publisher = publisher or ProgressPublisher()
        self.store = store or FirestoreStore()
        self.callback_url = callback_url
        self.origin_id = origin_id

    def _event(self, status: JobStatus, progress: float, metadata: dict | None = None) -> JobEvent:
        return JobEvent(
            job_id=self.job_id,
            status=status,
            progress_percentage=progress,
            metadata=metadata or {},
            origin_id=self.origin_id,
        )

    # ----- transient progress (Pub/Sub only) -----------------------------------

    def progress(self, status: JobStatus, percentage: float, metadata: dict | None = None) -> None:
        """Emit a live progress update (not persisted)."""
        self.publisher.publish(self._event(status, percentage, metadata))

    # ----- terminal states (persist + callback) --------------------------------

    def complete(self, metadata: dict | None = None) -> None:
        event = self._event(JobStatus.COMPLETED, 100.0, metadata)
        self.publisher.publish(event)
        self.store.save_result(event)
        post_callback(self.callback_url, event)

    def fail(self, error: str, metadata: dict | None = None) -> None:
        meta = {"error": error, **(metadata or {})}
        event = self._event(JobStatus.FAILED, 0.0, meta)
        self.publisher.publish(event)
        self.store.save_result(event)
        post_callback(self.callback_url, event)
