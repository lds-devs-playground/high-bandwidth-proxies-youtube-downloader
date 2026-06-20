"""Download YouTube audio and convert it to MP3, rotating proxies on failure.

Relies on yt-dlp for extraction and ffmpeg for the MP3 conversion. If a
download fails (block, timeout, dead proxy) the current proxy is penalised and
a different one is tried, up to ``max_attempts`` times.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from proxy_manager import ProxyManager

logger = logging.getLogger(__name__)


class DownloadError(RuntimeError):
    """Raised when a video could not be downloaded after all attempts."""


@dataclass
class YouTubeMP3Downloader:
    proxy_manager: ProxyManager
    output_dir: str = "downloads"
    audio_quality: str = "192"  # kbps for the MP3 encode
    max_attempts: int = 8
    socket_timeout: int = 20
    cookies_from_browser: str | None = None  # e.g. "chrome", "firefox", "edge"
    cookies_file: str | None = None  # path to a Netscape cookies.txt
    progress_hook: Callable[[dict], None] | None = None  # yt-dlp progress callback

    def __post_init__(self) -> None:
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def _build_options(self, proxy: str | None, output_name: str | None = None) -> dict:
        stem = output_name if output_name else "%(title)s"
        opts: dict = {
            "format": "bestaudio/best",
            "outtmpl": str(Path(self.output_dir) / f"{stem}.%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": self.audio_quality,
                }
            ],
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "socket_timeout": self.socket_timeout,
            "retries": 1,
            "ignoreerrors": False,
        }
        if proxy:
            opts["proxy"] = proxy
        if self.cookies_from_browser:
            # yt-dlp expects a tuple: (browser, profile, keyring, container).
            opts["cookiesfrombrowser"] = (self.cookies_from_browser,)
        if self.cookies_file:
            opts["cookiefile"] = self.cookies_file
        if self.progress_hook:
            opts["progress_hooks"] = [self.progress_hook]
        return opts

    def download(self, video_url: str, output_name: str | None = None) -> Path:
        """Download a single video as MP3, rotating proxies on failure.

        When ``output_name`` is given, the file is written as
        ``<output_name>.mp3`` (e.g. the video id); otherwise the video title is
        used. Returns the path to the produced MP3 file.
        Raises ``DownloadError`` if every attempt fails.
        """
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            proxy = self.proxy_manager.get()
            label = proxy or "direct connection"
            logger.info("Attempt %d/%d via %s", attempt, self.max_attempts, label)

            try:
                with yt_dlp.YoutubeDL(self._build_options(proxy, output_name)) as ydl:
                    info = ydl.extract_info(video_url, download=True)
            except Exception as exc:  # noqa: BLE001 - we want to rotate on any failure
                last_error = exc
                logger.warning("Attempt %d failed via %s: %s", attempt, label, exc)
                if proxy:
                    self.proxy_manager.report_failure(proxy)
                continue
            else:
                if proxy:
                    self.proxy_manager.report_success(proxy)
                mp3_path = self._resolve_output_path(info, output_name)
                logger.info("Downloaded: %s", mp3_path)
                return mp3_path

        raise DownloadError(
            f"Failed to download {video_url!r} after {self.max_attempts} attempts: {last_error}"
        )

    def download_many(self, video_urls: list[str]) -> dict[str, Path | None]:
        """Download several videos; returns a url -> path (or None on failure) map."""
        results: dict[str, Path | None] = {}
        for url in video_urls:
            try:
                results[url] = self.download(url)
            except DownloadError as exc:
                logger.error("%s", exc)
                results[url] = None
        return results

    def _resolve_output_path(self, info: dict, output_name: str | None = None) -> Path:
        """Figure out the final .mp3 path yt-dlp produced for this video."""
        if output_name:
            return Path(self.output_dir) / f"{output_name}.mp3"
        title = info.get("title", "audio")
        # yt-dlp sanitises filenames; reuse its logic so we match what was written.
        safe_name = yt_dlp.utils.sanitize_filename(title, restricted=False)
        return Path(self.output_dir) / f"{safe_name}.mp3"
