"""Transient real-time transport via Google Cloud Pub/Sub.

Maps the doc's Redis ``job_updates:job_id`` channel onto a single Pub/Sub topic
where each message carries the ``job_id`` as both an attribute and the ordering
key. A separate logging service subscribes and relays to frontends over
WebSockets — that service is outside this worker's responsibility.

Progress events are *transient*: they are not written to Firestore, keeping the
database free of "write-bloat". Only final assets are persisted (see
``firestore.py``).
"""

from __future__ import annotations

import logging

from .events import JobEvent

logger = logging.getLogger(__name__)


class ProgressPublisher:
    """Publishes :class:`JobEvent` updates to a Pub/Sub topic.

    The Google client is imported lazily so the rest of the app (and tests) can
    run without the dependency or credentials. If no topic is configured the
    publisher is a no-op.
    """

    def __init__(self, project_id: str = "", topic: str = "", enable_ordering: bool = True):
        self.project_id = project_id
        self.topic = topic
        self.enable_ordering = enable_ordering
        self._client = None
        self._topic_path = None

        if self.project_id and self.topic:
            self._init_client()

    def _init_client(self) -> None:
        try:
            from google.cloud import pubsub_v1
        except ImportError:  # pragma: no cover - dependency missing
            logger.warning("google-cloud-pubsub not installed; progress publishing disabled.")
            return

        try:
            settings = pubsub_v1.types.PublisherOptions(enable_message_ordering=self.enable_ordering)
            self._client = pubsub_v1.PublisherClient(publisher_options=settings)
            self._topic_path = self._client.topic_path(self.project_id, self.topic)
        except Exception as exc:  # noqa: BLE001 - never let telemetry break the job
            logger.warning("Could not initialise Pub/Sub publisher: %s", exc)
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None and self._topic_path is not None

    def publish(self, event: JobEvent) -> None:
        """Publish one event. Failures are logged but never raised."""
        if not self.enabled:
            logger.debug("Pub/Sub disabled; dropping event %s", event.status)
            return
        try:
            kwargs = {
                "data": event.to_bytes(),
                "job_id": event.job_id,
                "status": event.status.value,
            }
            if self.enable_ordering and event.job_id:
                # Ordering key guarantees per-job ordered delivery.
                self._client.publish(self._topic_path, ordering_key=event.job_id, **kwargs)
            else:
                self._client.publish(self._topic_path, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to publish progress event: %s", exc)
