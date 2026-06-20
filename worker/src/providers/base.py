"""Common interface and helpers shared by all proxy-rotation providers.

Each provider knows how to turn account credentials / API tokens into a list of
proxy URLs (``http://user:pass@host:port``) that the generic ``ProxyManager``
pool can rotate through. Providers may optionally support country targeting.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from urllib.parse import quote

logger = logging.getLogger(__name__)


def normalize(proxy: str) -> str:
    """Ensure a proxy string has a scheme; default to http://."""
    proxy = proxy.strip()
    if "://" not in proxy:
        proxy = "http://" + proxy
    return proxy


def build_gateway_url(gateway: str, username: str, password: str) -> str:
    """Compose a gateway proxy URL from its parts.

    ``gateway`` may be given as ``host:port`` or a full ``scheme://host:port``.
    Credentials, when supplied, are injected as ``user:pass@`` so the rotating
    endpoint authenticates on every request.
    """
    gateway = gateway.strip()
    if "://" in gateway:
        scheme, _, hostport = gateway.partition("://")
    else:
        scheme, hostport = "http", gateway

    if username and password and "@" not in hostport:
        creds = f"{quote(username, safe='')}:{quote(password, safe='')}@"
        hostport = creds + hostport

    return f"{scheme}://{hostport}"


class ProxyProvider(ABC):
    """Base class for a proxy-rotation provider."""

    #: Short identifier used on the CLI (e.g. "smartproxy", "webshare").
    name: str = "provider"

    @abstractmethod
    def build_proxies(self) -> list[str]:
        """Return the list of proxy URLs this provider can offer right now."""

    def country_proxy(self, country: str) -> str | None:
        """Return a proxy targeted at ``country``, or ``None`` if unsupported.

        Default implementation has no geo targeting. Providers that support it
        (e.g. SmartProxy username-based targeting) override this.
        """
        return None
