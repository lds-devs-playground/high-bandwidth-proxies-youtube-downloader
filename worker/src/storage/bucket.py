"""Stream finished audio files into Google Cloud Storage, keyed by video id.

Cloud Run's local filesystem is ephemeral (and in-memory by default), so large
MP3s should be pushed to durable storage without buffering the whole file in
memory. ``AudioStreamService`` performs a resumable, chunked upload straight
from the local file handle into the bucket, naming the object after the
YouTube video id (e.g. ``dQw4w9WgXcQ.mp3``).

It can also drive an end-to-end download → stream in one call via
``download_and_stream`` when given a downloader instance.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Resumable-upload chunk size; must be a multiple of 256 KiB. 8 MiB keeps memory
# flat while staying efficient for typical audio file sizes.
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
DEFAULT_CONTENT_TYPE = "audio/mpeg"


class AudioStreamService:
    """Streams local audio files into a GCS bucket using the video id as name.

    No-op (``enabled is False``) when no bucket is configured, so callers can
    wire it unconditionally and let local-only runs skip the upload.
    """

    def __init__(
        self,
        bucket: str = "",
        project_id: str = "",
        prefix: str = "",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        content_type: str = DEFAULT_CONTENT_TYPE,
    ) -> None:
        self.bucket = bucket
        self.project_id = project_id
        self.prefix = prefix.strip("/")
        self.chunk_size = chunk_size
        self.content_type = content_type
        self._client = None

        if self.bucket:
            self._init_client()

    def _init_client(self) -> None:
        try:
            from google.cloud import storage
        except ImportError:  # pragma: no cover - dependency missing
            logger.warning("google-cloud-storage not installed; streaming disabled.")
            return
        try:
            self._client = storage.Client(project=self.project_id or None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not initialise GCS client: %s", exc)
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def blob_name(self, video_id: str, suffix: str = ".mp3") -> str:
        """Object name for a video id, honouring the optional prefix."""
        name = f"{video_id}{suffix}"
        return f"{self.prefix}/{name}" if self.prefix else name

    def stream_file(
        self,
        file_path: Path | str,
        video_id: str,
        content_type: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Stream a local file into the bucket as ``<video_id><suffix>``.

        Returns the resulting ``gs://`` URI, or ``""`` when disabled/failed.
        The upload is chunked so memory stays flat regardless of file size.
        ``metadata`` is attached to the object as GCS custom metadata (all
        values are coerced to strings, ``None`` entries dropped).
        """
        if not self.enabled:
            return ""
        if not video_id:
            logger.warning("Cannot stream without a video id; skipping upload.")
            return ""

        path = Path(file_path)
        if not path.is_file():
            logger.warning("Cannot stream missing file: %s", path)
            return ""

        suffix = path.suffix or ".mp3"
        name = self.blob_name(video_id, suffix)
        ctype = content_type or self.content_type
        custom_meta = _clean_metadata(metadata)

        try:
            blob = self._client.bucket(self.bucket).blob(name)
            blob.chunk_size = self.chunk_size
            if custom_meta:
                blob.metadata = custom_meta
            with path.open("rb") as src, blob.open(
                "wb", content_type=ctype, chunk_size=self.chunk_size
            ) as dst:
                shutil.copyfileobj(src, dst, length=self.chunk_size)
            uri = f"gs://{self.bucket}/{name}"
            logger.info("Streamed audio to %s", uri)
            return uri
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to stream %s to GCS: %s", path, exc)
            return ""

    def download_and_stream(
        self,
        downloader,
        video_url: str,
        video_id: str,
        content_type: str | None = None,
        metadata: dict | None = None,
        cleanup: bool = True,
    ) -> str:
        """Download the audio (named by video id) and stream it to the bucket.

        ``downloader`` is a ``YouTubeMP3Downloader``. Returns the ``gs://`` URI,
        or ``""`` on failure. The local file is removed afterwards when
        ``cleanup`` is set (recommended on ephemeral Cloud Run disks).
        """
        path = downloader.download(video_url, output_name=video_id)
        try:
            return self.stream_file(
                path, video_id, content_type=content_type, metadata=metadata
            )
        finally:
            if cleanup:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError as exc:  # noqa: BLE001
                    logger.debug("Could not remove %s: %s", path, exc)


def _clean_metadata(metadata: dict | None) -> dict[str, str]:
    """Coerce a metadata mapping into GCS-safe ``{str: str}`` (drop ``None``)."""
    if not metadata:
        return {}
    return {str(k): str(v) for k, v in metadata.items() if v is not None}
