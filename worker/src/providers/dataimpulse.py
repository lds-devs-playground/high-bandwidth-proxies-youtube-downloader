"""DataImpulse (dataimpulse.com) residential proxy provider.

DataImpulse exposes a single rotating backbone gateway that rotates the exit IP
server-side on every request, e.g. ``http://login:pass@gw.dataimpulse.com:823``.

Country targeting is done through the gateway username by appending a suffix,
e.g. ``login__cr.us``. The exact template is configurable via ``country_format``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from .base import ProxyProvider, build_gateway_url

logger = logging.getLogger(__name__)

DEFAULT_GATEWAY = "gw.dataimpulse.com:823"
DEFAULT_COUNTRY_FORMAT = "{user}__cr.{cc}"


@dataclass
class DataImpulseProvider(ProxyProvider):
    """Build proxies from the DataImpulse rotating gateway."""

    name = "dataimpulse"

    gateway: str | None = None
    username: str | None = None
    password: str | None = None
    country_format: str | None = None

    def __post_init__(self) -> None:
        self.gateway = (
            self.gateway or os.environ.get("DATAIMPULSE_GATEWAY", "") or DEFAULT_GATEWAY
        ).strip()
        self.username = (self.username or os.environ.get("DATAIMPULSE_USERNAME", "")).strip()
        self.password = (self.password or os.environ.get("DATAIMPULSE_PASSWORD", "")).strip()
        self.country_format = (
            self.country_format
            or os.environ.get("DATAIMPULSE_COUNTRY_FORMAT", "")
            or DEFAULT_COUNTRY_FORMAT
        )

    def build_proxies(self) -> list[str]:
        collected: list[str] = []
        if self.username and self.password:
            collected.append(build_gateway_url(self.gateway, self.username, self.password))
        logger.info("DataImpulse: built %d proxies", len(collected))
        return collected

    def country_proxy(self, country: str) -> str | None:
        if not (self.username and self.password):
            return None
        user = self.username
        if country and country.upper() != "GLOBAL":
            user = self.country_format.format(user=self.username, cc=country.lower())
        return build_gateway_url(self.gateway, user, self.password)
