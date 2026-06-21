"""Geo-restriction resolver: pick a SmartProxy country that can view a video.

Flow
----
1. Ask the YouTube Data API which countries a video is allowed/blocked in.
2. Choose a target country (the first allowed one, or the first common region
   that is not on the block-list).
3. Build a *country-targeted* SmartProxy residential gateway for that country.
4. Verify the proxy actually exits in the requested country before using it.

SmartProxy residential proxies are geo-targeted through the gateway username,
e.g. ``user-country-us``. The exact separator/keyword can vary per account, so
it is configurable via ``country_format`` / ``SMARTPROXY_COUNTRY_FORMAT``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import requests

from providers.base import ProxyProvider, build_gateway_url
from youtube_client import YouTubeAuthError, YouTubeClient

logger = logging.getLogger(__name__)

# Regions we have proxies for / are willing to try, in preference order.
COMMON_REGIONS = ["US", "GB", "DE", "FR", "JP", "CA", "AU", "NL"]

# Endpoint used to confirm which country a proxy actually exits from.
IP_GEO_URL = "https://ipinfo.io/json"


class RestrictionError(RuntimeError):
    """Raised when no usable country/proxy could be resolved."""


@dataclass
class GeoTarget:
    """Result of resolving a video's geo-restriction to a working proxy."""

    country: str
    proxy_url: str
    verified: bool


# ----- YouTube API -----------------------------------------------------------


def get_video_restrictions(video_id: str, client: YouTubeClient | None = None) -> dict:
    """Return the ``regionRestriction`` dict for a video (may be empty).

    Uses an authenticated ``YouTubeClient`` (service account / content owner, or
    API key). When ``client`` is omitted one is built from the environment.
    """
    client = client or YouTubeClient.from_env()
    try:
        return client.get_region_restriction(video_id)
    except YouTubeAuthError as exc:
        raise RestrictionError(str(exc)) from exc


def determine_target_country(restrictions: dict) -> str | None:
    """Pick a country to proxy through, or ``None`` if globally available.

    Returns a two-letter country code, the sentinel ``"GLOBAL"`` when there are
    no restrictions, or ``None`` if every candidate region is blocked.
    """
    if not restrictions:
        logger.info("Video is globally available; no geo-block detected.")
        return "GLOBAL"

    allowed = restrictions.get("allowed")
    if allowed:
        logger.info("Video is ONLY viewable in: %s", allowed)
        return allowed[0]

    blocked = restrictions.get("blocked")
    if blocked:
        logger.info("Video is blocked in: %s", blocked)
        blocked_set = {c.upper() for c in blocked}
        for region in COMMON_REGIONS:
            if region not in blocked_set:
                logger.info("Recommended proxy region: %s (not blocked)", region)
                return region
        logger.warning("All standard proxy regions are blocked; inspect manually.")
        return None

    return "GLOBAL"


# ----- SmartProxy country targeting ------------------------------------------


def build_country_gateway(
    country: str,
    gateway: str | None = None,
    username: str | None = None,
    password: str | None = None,
    country_format: str | None = None,
) -> str:
    """Build a SmartProxy gateway URL targeted at ``country``.

    ``country_format`` is a template applied to the username; ``{user}`` and
    ``{cc}`` are substituted. Default ``"{user}-country-{cc}"`` matches the
    common SmartProxy residential scheme.
    """
    gateway = (gateway or os.environ.get("SMARTPROXY_GATEWAY", "")).strip()
    username = (username or os.environ.get("SMARTPROXY_USERNAME", "")).strip()
    password = (password or os.environ.get("SMARTPROXY_PASSWORD", "")).strip()
    country_format = (
        country_format
        or os.environ.get("SMARTPROXY_COUNTRY_FORMAT", "")
        or "{user}-country-{cc}"
    )

    if not gateway:
        raise RestrictionError(
            "SMARTPROXY_GATEWAY (or gateway=) is required for country targeting."
        )

    targeted_user = username
    if username and country and country != "GLOBAL":
        targeted_user = country_format.format(user=username, cc=country.lower())

    return build_gateway_url(gateway, targeted_user, password)


def verify_proxy_country(proxy_url: str, expected: str, timeout: float = 15.0) -> bool:
    """Confirm a proxy actually exits in ``expected`` country.

    Returns ``True`` when the detected country matches (or when ``expected`` is
    ``"GLOBAL"``). Network/parse failures return ``False`` so the caller can try
    another option rather than trusting an unverified proxy.
    """
    if expected == "GLOBAL":
        return True

    proxies = {"http": proxy_url, "https": proxy_url}
    try:
        resp = requests.get(IP_GEO_URL, proxies=proxies, timeout=timeout)
        resp.raise_for_status()
        detected = (resp.json().get("country") or "").upper()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Could not verify proxy country: %s", exc)
        return False

    match = detected == expected.upper()
    logger.info(
        "Proxy exit country: %s (expected %s) -> %s",
        detected or "unknown",
        expected,
        "match" if match else "MISMATCH",
    )
    return match


# ----- High-level resolver ---------------------------------------------------


def resolve_working_proxy(
    video_id: str,
    provider: ProxyProvider,
    client: YouTubeClient | None = None,
    verify: bool = True,
) -> GeoTarget:
    """End-to-end: find a country ``provider`` can view ``video_id`` through.

    Tries the API-recommended country first, then falls back through
    ``COMMON_REGIONS`` (verifying each exit country) until one works. The proxy
    URL for each candidate country is built via ``provider.country_proxy``, so
    any provider with country targeting (SmartProxy, DataImpulse, ...) works.
    Raises ``RestrictionError`` if nothing usable is found.
    """
    restrictions = get_video_restrictions(video_id, client=client)
    primary = determine_target_country(restrictions)

    if primary is None:
        raise RestrictionError("Every candidate region is blocked for this video.")

    # Build the ordered list of countries to attempt.
    candidates: list[str] = [primary]
    if primary == "GLOBAL":
        candidates = ["GLOBAL"]
    else:
        blocked = {c.upper() for c in restrictions.get("blocked", [])}
        allowed = {c.upper() for c in restrictions.get("allowed", [])}
        for region in COMMON_REGIONS:
            if region in candidates:
                continue
            if region in blocked:
                continue
            if allowed and region not in allowed:
                continue
            candidates.append(region)

    last_proxy = ""
    for country in candidates:
        proxy_url = provider.country_proxy(country)
        if not proxy_url:
            raise RestrictionError(
                f"Provider {provider.name!r} cannot build a country-targeted "
                "proxy; check its credentials / gateway configuration."
            )
        last_proxy = proxy_url

        if not verify:
            return GeoTarget(country=country, proxy_url=proxy_url, verified=False)

        if verify_proxy_country(proxy_url, country):
            return GeoTarget(country=country, proxy_url=proxy_url, verified=True)

        logger.info("Country %s did not verify; trying next candidate.", country)

    raise RestrictionError(
        f"No {provider.name} country could be verified for video {video_id!r}. "
        f"Last attempted proxy: {last_proxy}"
    )
