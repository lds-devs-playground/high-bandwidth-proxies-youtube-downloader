"""Authenticated YouTube Data API client.

Supports three credential modes, in priority order:

1. **Service account JSON** supplied inline via ``YOUTUBE_SA_JSON`` (e.g. mounted
   from GCP Secret Manager) — used for *content owner* access.
2. **Service account key file** via ``GOOGLE_APPLICATION_CREDENTIALS`` /
   ``YOUTUBE_SA_FILE``.
3. **Application Default Credentials** — the Cloud Run runtime service account.
4. **API key** fallback (``YOUTUBE_API_KEY``) for simple public lookups.

When a content owner id is configured (``YOUTUBE_CONTENT_OWNER_ID``), requests
are made ``onBehalfOfContentOwner`` so a CMS/partner account can inspect videos
it manages.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from google.auth import default as google_auth_default
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Read-only is enough for videos.list; youtubepartner enables content-owner ops.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtubepartner",
]


class YouTubeAuthError(RuntimeError):
    """Raised when no usable YouTube credentials could be resolved."""


@dataclass
class YouTubeClient:
    """Thin wrapper over the ``youtube`` v3 service with content-owner support."""

    api_key: str = ""
    sa_json: str = ""
    sa_file: str = ""
    content_owner_id: str = ""

    @classmethod
    def from_env(cls) -> "YouTubeClient":
        return cls(
            api_key=os.environ.get("YOUTUBE_API_KEY", "").strip(),
            sa_json=os.environ.get("YOUTUBE_SA_JSON", "").strip(),
            sa_file=(
                os.environ.get("YOUTUBE_SA_FILE", "")
                or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            ).strip(),
            content_owner_id=os.environ.get("YOUTUBE_CONTENT_OWNER_ID", "").strip(),
        )

    # ----- service construction ------------------------------------------------

    def _build_service(self):
        """Build a discovery service using the best available credentials."""
        if self.api_key and not (self.sa_json or self.sa_file or self.content_owner_id):
            # Simple public-data access via API key.
            return build("youtube", "v3", developerKey=self.api_key, cache_discovery=False)

        creds = self._resolve_credentials()
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    def _resolve_credentials(self):
        if self.sa_json:
            try:
                info = json.loads(self.sa_json)
            except json.JSONDecodeError as exc:
                raise YouTubeAuthError(f"YOUTUBE_SA_JSON is not valid JSON: {exc}") from exc
            return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

        if self.sa_file:
            if not os.path.isfile(self.sa_file):
                raise YouTubeAuthError(f"Service account file not found: {self.sa_file}")
            return service_account.Credentials.from_service_account_file(
                self.sa_file, scopes=SCOPES
            )

        # Fall back to the runtime service account (Cloud Run / GCE / etc.).
        try:
            creds, _ = google_auth_default(scopes=SCOPES)
        except Exception as exc:  # noqa: BLE001 - surface a clear auth error
            raise YouTubeAuthError(
                "No YouTube credentials available (set YOUTUBE_SA_JSON, "
                "YOUTUBE_SA_FILE, YOUTUBE_API_KEY, or run with a GCP service account)."
            ) from exc
        return creds

    # ----- API calls -----------------------------------------------------------

    def get_region_restriction(self, video_id: str) -> dict:
        """Return a video's ``regionRestriction`` dict (possibly empty)."""
        service = self._build_service()
        params = {"part": "contentDetails,status", "id": video_id}
        if self.content_owner_id:
            params["onBehalfOfContentOwner"] = self.content_owner_id

        try:
            response = service.videos().list(**params).execute()
        except HttpError as exc:
            raise YouTubeAuthError(f"YouTube API request failed: {exc}") from exc

        items = response.get("items", [])
        if not items:
            raise YouTubeAuthError("Video not found, or it is completely private.")

        content_details = items[0].get("contentDetails", {})
        return content_details.get("regionRestriction", {})
