"""Webshare (webshare.io) residential/rotating proxy provider.

Two usage modes:
* Rotating endpoint -> Webshare's backbone gateway that rotates the exit IP per
  request, e.g. http://user:pass@p.webshare.io:80
* API token        -> fetch your proxy list from the Webshare API v2; each entry
  becomes an individual ``http://user:pass@ip:port`` proxy in the pool.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from urllib.parse import quote

import requests

from .base import ProxyProvider, build_gateway_url

logger = logging.getLogger(__name__)

DEFAULT_GATEWAY = "p.webshare.io:80"
API_LIST_URL = "https://proxy.webshare.io/api/v2/proxy/list/"


@dataclass
class WebshareProvider(ProxyProvider):
    """Build proxies from a Webshare rotating endpoint and/or API token."""

    name = "webshare"

    token: str | None = None
    username: str | None = None
    password: str | None = None
    gateway: str | None = None
    page_size: int = 100

    def __post_init__(self) -> None:
        self.token = (self.token or os.environ.get("WEBSHARE_TOKEN", "")).strip()
        self.username = (self.username or os.environ.get("WEBSHARE_USERNAME", "")).strip()
        self.password = (self.password or os.environ.get("WEBSHARE_PASSWORD", "")).strip()
        self.gateway = (
            self.gateway or os.environ.get("WEBSHARE_GATEWAY", "") or DEFAULT_GATEWAY
        ).strip()

    def build_proxies(self) -> list[str]:
        collected: list[str] = []
        # Rotating backbone endpoint (only useful with credentials).
        if self.username and self.password:
            collected.append(build_gateway_url(self.gateway, self.username, self.password))
        # Individual proxies pulled from the account via the API token.
        if self.token:
            collected.extend(_fetch_list(self.token, self.page_size))
        logger.info("Webshare: built %d proxies", len(collected))
        return collected


def _fetch_list(token: str, page_size: int = 100, timeout: float = 15.0) -> list[str]:
    """Fetch the account's proxy list from the Webshare API v2.

    Returns ``http://user:pass@ip:port`` URLs. Failures are non-fatal.
    """
    headers = {"Authorization": f"Token {token}"}
    params = {"mode": "direct", "page": 1, "page_size": page_size}
    try:
        resp = requests.get(API_LIST_URL, headers=headers, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Could not fetch Webshare proxy list: %s", exc)
        return []

    found: list[str] = []
    for item in data.get("results", []):
        addr = item.get("proxy_address")
        port = item.get("port")
        if not addr or not port:
            continue
        user = item.get("username")
        secret = item.get("password")
        if user and secret:
            creds = f"{quote(user, safe='')}:{quote(secret, safe='')}@"
            found.append(f"http://{creds}{addr}:{port}")
        else:
            found.append(f"http://{addr}:{port}")

    logger.info("Fetched %d proxies from Webshare API", len(found))
    return found
