"""Generic proxy pool with rotation, health tracking, and scoring.

Provider-specific construction (SmartProxy, Webshare, ...) lives in the
``providers`` package; this module only manages a pool of proxy URLs of the
form ``http://host:port`` or ``http://user:pass@host:port``.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ProxyStats:
    """Tracks how reliable a single proxy has been so far."""

    url: str
    successes: int = 0
    failures: int = 0
    # Monotonic timestamp until which the proxy is "benched" after a failure.
    cooldown_until: float = 0.0

    @property
    def score(self) -> float:
        total = self.successes + self.failures
        if total == 0:
            return 0.5  # unknown proxies get a neutral score
        return self.successes / total


@dataclass
class ProxyManager:
    """Holds a pool of proxies and hands them out with rotation + scoring."""

    proxies: list[str] = field(default_factory=list)
    cooldown_seconds: float = 120.0
    _stats: dict[str, ProxyStats] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        for url in self.proxies:
            self._stats.setdefault(url, ProxyStats(url=url))

    # ----- pool operations ------------------------------------------------------

    def __len__(self) -> int:
        return len(self.proxies)

    def get(self) -> str | None:
        """Return the best currently-available proxy, or None if pool is empty.

        Selection favours proxies with a higher success ratio while still
        exploring unknown ones. Proxies in cooldown are skipped unless every
        proxy is benched (in which case the soonest-available one is returned).
        """
        with self._lock:
            if not self.proxies:
                return None

            now = time.monotonic()
            available = [
                self._stats[p] for p in self.proxies if self._stats[p].cooldown_until <= now
            ]

            if not available:
                # Everything is in cooldown: reuse whichever frees up soonest.
                soonest = min(self._stats.values(), key=lambda s: s.cooldown_until)
                return soonest.url

            # Weighted-random pick biased toward higher scores so a few bad
            # proxies don't trap us, but good ones get used more often.
            weights = [max(stat.score, 0.05) for stat in available]
            chosen = random.choices(available, weights=weights, k=1)[0]
            return chosen.url

    def report_success(self, proxy: str) -> None:
        with self._lock:
            stat = self._stats.get(proxy)
            if stat:
                stat.successes += 1
                stat.cooldown_until = 0.0

    def report_failure(self, proxy: str) -> None:
        with self._lock:
            stat = self._stats.get(proxy)
            if stat:
                stat.failures += 1
                stat.cooldown_until = time.monotonic() + self.cooldown_seconds

    def remove(self, proxy: str) -> None:
        """Permanently drop a proxy from the pool (e.g. hard-dead)."""
        with self._lock:
            if proxy in self.proxies:
                self.proxies.remove(proxy)
            self._stats.pop(proxy, None)
