"""Command-line entry point for the proxy-rotating YouTube -> MP3 downloader.

Examples
--------
SmartProxy rotating residential gateway:
    python src/main.py URL --provider smartproxy \
        --smartproxy-gateway gate.smartproxy.com:7000 \
        --smartproxy-username USER --smartproxy-password PASS

Webshare rotating endpoint or API token:
    python src/main.py URL --provider webshare \
        --webshare-username USER --webshare-password PASS
    python src/main.py URL --provider webshare --webshare-token YOUR_TOKEN

Survive YouTube bot checks by reusing your browser's cookies:
    python src/main.py URL --provider webshare --cookies-from-browser chrome

Credentials can also come from the environment, e.g. SMARTPROXY_*, WEBSHARE_*.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from urllib.parse import parse_qs, urlparse

from downloader import DownloadError, YouTubeMP3Downloader
from proxy_manager import ProxyManager
from providers import (
    DataImpulseProvider,
    SmartProxyProvider,
    WebshareProvider,
    build_manager,
)
from restrictions import RestrictionError, resolve_working_proxy
from config import Settings
from youtube_client import YouTubeClient
from storage import (
    AudioStreamService,
    FirestoreStore,
    JobReporter,
    JobStatus,
    ProgressPublisher,
)


def build_parser(cfg: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download YouTube audio as MP3 with automatic proxy rotation.",
    )
    parser.add_argument(
        "urls",
        nargs="*",
        default=cfg.video_urls,
        help="YouTube video URLs. Defaults to the VIDEO_URLS env var when omitted.",
    )
    parser.add_argument(
        "-o", "--output", default=cfg.output_dir,
        help="Output directory (default: downloads / OUTPUT_DIR).",
    )
    parser.add_argument(
        "-q", "--quality", default=cfg.quality,
        help="MP3 bitrate in kbps (default: 192 / AUDIO_QUALITY).",
    )
    parser.add_argument(
        "--provider",
        choices=["smartproxy", "webshare", "dataimpulse"],
        default=cfg.provider,
        help="Proxy-rotation provider to use (default: smartproxy / PROVIDER).",
    )
    smartproxy = parser.add_argument_group("SmartProxy (smartproxy.org)")
    smartproxy.add_argument(
        "--smartproxy-gateway",
        default=None,
        help="Rotating gateway endpoint, e.g. gate.smartproxy.com:7000.",
    )
    smartproxy.add_argument(
        "--smartproxy-username",
        default=None,
        help="SmartProxy username (or set SMARTPROXY_USERNAME).",
    )
    smartproxy.add_argument(
        "--smartproxy-password",
        default=None,
        help="SmartProxy password (or set SMARTPROXY_PASSWORD).",
    )
    smartproxy.add_argument(
        "--smartproxy-api",
        default=None,
        help="SmartProxy API-extraction URL that returns a fresh IP list.",
    )
    webshare = parser.add_argument_group("Webshare (webshare.io)")
    webshare.add_argument(
        "--webshare-token",
        default=None,
        help="Webshare API token to fetch your proxy list (or set WEBSHARE_TOKEN).",
    )
    webshare.add_argument(
        "--webshare-username",
        default=None,
        help="Webshare proxy username (or set WEBSHARE_USERNAME).",
    )
    webshare.add_argument(
        "--webshare-password",
        default=None,
        help="Webshare proxy password (or set WEBSHARE_PASSWORD).",
    )
    webshare.add_argument(
        "--webshare-gateway",
        default=None,
        help="Webshare rotating endpoint (default: p.webshare.io:80).",
    )
    dataimpulse = parser.add_argument_group("DataImpulse (dataimpulse.com)")
    dataimpulse.add_argument(
        "--dataimpulse-username",
        default=None,
        help="DataImpulse login (or set DATAIMPULSE_USERNAME).",
    )
    dataimpulse.add_argument(
        "--dataimpulse-password",
        default=None,
        help="DataImpulse password (or set DATAIMPULSE_PASSWORD).",
    )
    dataimpulse.add_argument(
        "--dataimpulse-gateway",
        default=None,
        help="DataImpulse rotating endpoint (default: gw.dataimpulse.com:823).",
    )
    cookies = parser.add_argument_group("Cookies (bypass YouTube bot checks)")
    cookies.add_argument(
        "--cookies-from-browser",
        default=None,
        metavar="BROWSER",
        help="Load cookies from a browser, e.g. chrome, firefox, edge, brave, safari.",
    )
    cookies.add_argument(
        "--cookies",
        default=cfg.cookies_file or None,
        metavar="FILE",
        help="Path to a Netscape-format cookies.txt file (or set COOKIES_FILE).",
    )
    geo = parser.add_argument_group("Geo-restriction (YouTube Data API)")
    geo.add_argument(
        "--api-key",
        default=cfg.youtube_api_key or None,
        help="YouTube Data API key. Enables auto geo-targeting per video "
        "(SmartProxy only; or set YOUTUBE_API_KEY).",
    )
    geo.add_argument(
        "--no-verify-country",
        action="store_true",
        default=not cfg.verify_country,
        help="Skip confirming the proxy's real exit country before downloading.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=cfg.max_attempts,
        help="Max proxy rotations per video before giving up (default: 8).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    cfg = Settings.from_env()
    args = build_parser(cfg).parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("main")

    if not args.urls:
        log.error("No video URLs provided. Pass them as arguments or set VIDEO_URLS.")
        return 2

    geo_enabled = cfg.youtube.enabled or bool(args.api_key)
    provider = _build_provider(args)
    if geo_enabled and args.provider in {"smartproxy", "dataimpulse"}:
        client = YouTubeClient(
            api_key=args.api_key or cfg.youtube.api_key,
            sa_json=cfg.youtube.sa_json,
            sa_file=cfg.youtube.sa_file,
            content_owner_id=cfg.youtube.content_owner_id,
        )
        return _run_with_geo_targeting(args, cfg, client, log, provider)
    if geo_enabled:
        log.warning(
            "YouTube geo-targeting is unsupported for %s; using plain rotation.",
            args.provider,
        )

    proxy_manager = build_manager(provider)

    if len(proxy_manager) == 0:
        log.warning(
            "No proxies loaded for provider %r; will attempt a direct connection. "
            "Check the provider's credentials / environment variables.",
            args.provider,
        )

    publisher, store = _build_visibility(cfg)
    streamer = AudioStreamService(
        bucket=cfg.visibility.result_bucket,
        project_id=cfg.gcp_project_id,
        prefix=cfg.visibility.result_prefix,
    )
    overall_failed = 0
    for index, url in enumerate(args.urls):
        reporter = _build_reporter(cfg, publisher, store, url, index)
        video_id = _extract_video_id(url)
        downloader = _build_downloader(args, proxy_manager, reporter)
        reporter.progress(JobStatus.STARTED, 0.0, {"url": url})
        try:
            path = downloader.download(url, output_name=video_id)
            log.info("  %s -> %s", url, path)
            asset_id = video_id or path.stem
            reporter.complete(
                _asset_metadata(url, path, asset_id, streamer, reporter, cfg)
            )
        except DownloadError as exc:
            log.error("%s", exc)
            reporter.fail(str(exc), {"url": url})
            overall_failed += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("Unexpected error processing %s", url)
            reporter.fail(f"unexpected error: {exc}", {"url": url})
            overall_failed += 1

    log.info("Done. %d succeeded, %d failed.", len(args.urls) - overall_failed, overall_failed)
    return 0 if overall_failed == 0 else 1


def _build_provider(args):
    """Construct the selected proxy provider from CLI args / environment."""
    if args.provider == "webshare":
        return WebshareProvider(
            token=args.webshare_token,
            username=args.webshare_username,
            password=args.webshare_password,
            gateway=args.webshare_gateway,
        )
    if args.provider == "dataimpulse":
        return DataImpulseProvider(
            username=args.dataimpulse_username,
            password=args.dataimpulse_password,
            gateway=args.dataimpulse_gateway,
        )
    return SmartProxyProvider(
        gateway=args.smartproxy_gateway,
        username=args.smartproxy_username,
        password=args.smartproxy_password,
        api_url=args.smartproxy_api,
    )


def _build_downloader(
    args, proxy_manager: ProxyManager, reporter: JobReporter | None = None
) -> YouTubeMP3Downloader:
    """Construct the downloader, wiring through cookie options and progress."""
    return YouTubeMP3Downloader(
        proxy_manager=proxy_manager,
        output_dir=args.output,
        audio_quality=args.quality,
        max_attempts=args.max_attempts,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies,
        progress_hook=_make_progress_hook(reporter) if reporter else None,
    )


def _build_visibility(cfg: Settings) -> tuple[ProgressPublisher, FirestoreStore]:
    """Build the shared Pub/Sub publisher and Firestore store from config."""
    publisher = ProgressPublisher(
        project_id=cfg.gcp_project_id, topic=cfg.visibility.pubsub_topic
    )
    store = FirestoreStore(
        project_id=cfg.gcp_project_id,
        collection=cfg.visibility.firestore_collection,
        database=cfg.visibility.firestore_database,
    )
    return publisher, store


def _asset_metadata(
    url: str,
    path,
    video_id: str,
    streamer: AudioStreamService,
    reporter: JobReporter,
    cfg: Settings,
) -> dict:
    """Stream the MP3 to the bucket (named by video id) and build the asset record."""
    meta = {"url": url, "video_id": video_id, "output_path": str(path)}
    if streamer.enabled:
        reporter.progress(JobStatus.UPLOADING, 99.5, {"url": url})
        object_metadata = {
            "video_id": video_id,
            "source_url": url,
            "job_id": reporter.job_id,
            "origin_id": reporter.origin_id,
            "provider": cfg.provider,
            "audio_quality": cfg.quality,
            "environment": cfg.environment,
        }
        uri = streamer.stream_file(path, video_id, metadata=object_metadata)
        if uri:
            meta["asset_uri"] = uri
    return meta


def _build_reporter(
    cfg: Settings, publisher: ProgressPublisher, store: FirestoreStore, url: str, index: int
) -> JobReporter:
    """Build a per-URL JobReporter, deriving a stable job id."""
    base = cfg.visibility.job_id
    if base and len(cfg.video_urls) > 1:
        job_id = f"{base}:{index}"
    else:
        job_id = base or uuid.uuid4().hex
    return JobReporter(
        job_id=job_id,
        publisher=publisher,
        store=store,
        callback_url=cfg.visibility.callback_url,
        origin_id=cfg.visibility.origin_id,
    )


def _make_progress_hook(reporter: JobReporter):
    """Adapt yt-dlp's progress dict into transient JobReporter updates."""

    def hook(d: dict) -> None:
        phase = d.get("status")
        if phase == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100.0) if total else 0.0
            reporter.progress(JobStatus.DOWNLOADING, round(pct, 1))
        elif phase == "finished":
            # Download done; ffmpeg post-processing (MP3 extract) follows.
            reporter.progress(JobStatus.PROCESSING, 99.0)

    return hook


def _run_with_geo_targeting(
    args, cfg: Settings, client: YouTubeClient, log, provider
) -> int:
    """Resolve a viewable country per video via the provider, then download."""
    publisher, store = _build_visibility(cfg)
    streamer = AudioStreamService(
        bucket=cfg.visibility.result_bucket,
        project_id=cfg.gcp_project_id,
        prefix=cfg.visibility.result_prefix,
    )
    overall_failed = 0
    for index, url in enumerate(args.urls):
        reporter = _build_reporter(cfg, publisher, store, url, index)
        video_id = _extract_video_id(url)
        if not video_id:
            log.error("Could not extract a video id from %s; skipping.", url)
            reporter.fail("could not extract video id", {"url": url})
            overall_failed += 1
            continue

        try:
            target = resolve_working_proxy(
                video_id=video_id,
                provider=provider,
                client=client,
                verify=not args.no_verify_country,
            )
        except RestrictionError as exc:
            log.error("%s", exc)
            reporter.fail(str(exc), {"url": url})
            overall_failed += 1
            continue
        except Exception as exc:  # noqa: BLE001
            log.exception("Unexpected error resolving proxy for %s", url)
            reporter.fail(f"unexpected error: {exc}", {"url": url})
            overall_failed += 1
            continue

        log.info("Using %s proxy (verified=%s) for %s", target.country, target.verified, url)
        reporter.progress(JobStatus.STARTED, 0.0, {"url": url, "country": target.country})
        proxy_manager = ProxyManager(proxies=[target.proxy_url])
        downloader = _build_downloader(args, proxy_manager, reporter)
        try:
            path = downloader.download(url, output_name=video_id)
            log.info("  %s -> %s", url, path)
            meta = _asset_metadata(url, path, video_id, streamer, reporter, cfg)
            meta["country"] = target.country
            reporter.complete(meta)
        except DownloadError as exc:
            log.error("%s", exc)
            reporter.fail(str(exc), {"url": url})
            overall_failed += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("Unexpected error processing %s", url)
            reporter.fail(f"unexpected error: {exc}", {"url": url})
            overall_failed += 1

    return 0 if overall_failed == 0 else 1


def _extract_video_id(url: str) -> str | None:
    """Pull the 11-char video id from common YouTube URL shapes (or a bare id)."""
    parsed = urlparse(url)
    if not parsed.scheme:
        return url if len(url) == 11 else None
    if parsed.hostname and "youtu.be" in parsed.hostname:
        return parsed.path.lstrip("/") or None
    query = parse_qs(parsed.query)
    if "v" in query:
        return query["v"][0]
    # /embed/<id> or /shorts/<id>
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0] in {"embed", "shorts", "v"}:
        return parts[1]
    return None


if __name__ == "__main__":
    sys.exit(main())
