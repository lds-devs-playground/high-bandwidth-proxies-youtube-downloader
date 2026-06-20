"""Upload final MP3 assets to Google Cloud Storage.

In Cloud Run the local filesystem is ephemeral, so the downloaded file must be
persisted to durable storage. The resulting ``gs://`` URI (and an optional
public/Firestore-stored path) is what gets recorded as the job's final asset.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class GCSUploader:
    """Uploads files to a GCS bucket. No-op when no bucket is configured."""

    def __init__(self, bucket: str = "", project_id: str = "", prefix: str = ""):
        self.bucket = bucket
        self.project_id = project_id
        self.prefix = prefix.strip("/")
        self._client = None

        if self.bucket:
            self._init_client()

    def _init_client(self) -> None:
        try:
            from google.cloud import storage
        except ImportError:  # pragma: no cover - dependency missing
            logger.warning("google-cloud-storage not installed; uploads disabled.")
            return
        try:
            self._client = storage.Client(project=self.project_id or None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not initialise GCS client: %s", exc)
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def upload(self, file_path: Path | str) -> str:
        """Upload a file and return its ``gs://`` URI (or "" if disabled/failed)."""
        if not self.enabled:
            return ""
        path = Path(file_path)
        if not path.is_file():
            logger.warning("Cannot upload missing file: %s", path)
            return ""

        blob_name = f"{self.prefix}/{path.name}" if self.prefix else path.name
        try:
            bucket = self._client.bucket(self.bucket)
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(str(path))
            uri = f"gs://{self.bucket}/{blob_name}"
            logger.info("Uploaded asset to %s", uri)
            return uri
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to upload %s to GCS: %s", path, exc)
            return ""
