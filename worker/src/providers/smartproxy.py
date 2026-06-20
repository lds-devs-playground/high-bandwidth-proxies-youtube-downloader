"""SmartProxy (smartproxy.org) residential proxy provider.

Two usage modes:
* Gateway endpoint  -> one endpoint that rotates the exit IP server-side,
  e.g. http://user:pass@gate.smartproxy.com:7000
* API extraction    -> a link that returns a fresh list of host:port IPs each
  time it is fetched (re-fetch the link to refresh the pool).

Country targeting is done through the gateway username, e.g.
``user-country-us``. The exact template is configurable via ``country_format``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import requests

from .base import ProxyProvider, build_gateway_url, normalize

logger = logging.getLogger(__name__)

DEFAULT_COUNTRY_FORMAT = "{user}-country-{cc}"


@dataclass
class SmartProxyProvider(ProxyProvider):
    """Build proxies from a SmartProxy gateway and/or API-extraction link."""

    name = "smartproxy"

    gateway: str | None = None
    username: str | None = None
    password: str | None = None
    api_url: str | None = None
    country_format: str | None = None

    def __post_init__(self) -> None:
        self.gateway = (self.gateway or os.environ.get("SMARTPROXY_GATEWAY", "")).strip()
        self.username = (self.username or os.environ.get("SMARTPROXY_USERNAME", "")).strip()
        self.password = (self.password or os.environ.get("SMARTPROXY_PASSWORD", "")).strip()
        self.api_url = (self.api_url or os.environ.get("SMARTPROXY_API_URL", "")).strip()
        self.country_format = (
            self.country_format
            or os.environ.get("SMARTPROXY_COUNTRY_FORMAT", "")
            or DEFAULT_COUNTRY_FORMAT
        )

    def build_proxies(self) -> list[str]:
        collected: list[str] = []
        if self.gateway:
            collected.append(build_gateway_url(self.gateway, self.username, self.password))
        if self.api_url:
            collected.extend(_fetch_api(self.api_url))
        logger.info("SmartProxy: built %d proxies", len(collected))
        return collected

    def country_proxy(self, country: str) -> str | None:
        if not self.gateway:
            return None
        user = self.username
        if user and country and country.upper() != "GLOBAL":
            user = self.country_format.format(user=self.username, cc=country.lower())
        return build_gateway_url(self.gateway, user, self.password)


def _fetch_api(api_url: str, timeout: float = 15.0) -> list[str]:
    """Fetch a fresh proxy list from a SmartProxy API-extraction link."""
    try:
        resp = requests.get(api_url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Could not fetch SmartProxy API list: %s", exc)
        return []

    found: list[str] = []
    for line in resp.text.splitlines():
        line = line.strip()
        if line and ":" in line:
            found.append(normalize(line))

    logger.info("Fetched %d proxies from SmartProxy API", len(found))
    return found
