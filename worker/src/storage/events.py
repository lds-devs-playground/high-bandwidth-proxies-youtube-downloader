"""Unified event protocol shared by all storage/transport channels.

Every progress or status update emitted by the worker uses the same JSON shape
so any subscriber (logging service, frontend, callback receiver) can parse it
identically::

    {
      "job_id": "abc123",
      "progress_percentage": 42.0,
      "status": "downloading",
      "metadata": {...},
      "origin_id": "project-a",
      "timestamp": "2026-06-20T12:34:56.000Z"
    }
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum


class JobStatus(str, Enum):
    """Lifecycle states for a download job."""

    QUEUED = "queued"
    STARTED = "started"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobEvent:
    """A single standardized progress/status update."""

    job_id: str
    status: JobStatus
    progress_percentage: float = 0.0
    metadata: dict = field(default_factory=dict)
    origin_id: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        # Allow passing the status as a plain string.
        if not isinstance(self.status, JobStatus):
            self.status = JobStatus(str(self.status))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    def to_bytes(self) -> bytes:
        return self.to_json().encode("utf-8")
