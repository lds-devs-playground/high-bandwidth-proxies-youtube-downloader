"""Proxy-rotation providers and a small factory to build a ProxyManager.

Add a new provider by creating a module with a ``ProxyProvider`` subclass and
registering it in ``PROVIDERS`` below.
"""

from __future__ import annotations

import logging

from proxy_manager import ProxyManager

from .base import ProxyProvider, build_gateway_url, normalize
from .smartproxy import SmartProxyProvider
from .webshare import WebshareProvider
from .dataimpulse import DataImpulseProvider

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, type[ProxyProvider]] = {
    SmartProxyProvider.name: SmartProxyProvider,
    WebshareProvider.name: WebshareProvider,
    DataImpulseProvider.name: DataImpulseProvider,
}

__all__ = [
    "ProxyProvider",
    "SmartProxyProvider",
    "WebshareProvider",
    "DataImpulseProvider",
    "PROVIDERS",
    "build_gateway_url",
    "normalize",
    "build_manager",
]


def build_manager(provider: ProxyProvider, cooldown_seconds: float = 120.0) -> ProxyManager:
    """Build a ``ProxyManager`` from a provider's proxies (de-duplicated)."""
    seen: set[str] = set()
    unique = [p for p in provider.build_proxies() if not (p in seen or seen.add(p))]
    logger.info("Loaded %d proxies from %s", len(unique), provider.name)
    return ProxyManager(proxies=unique, cooldown_seconds=cooldown_seconds)
