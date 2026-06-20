"""Cross-project completion callback — the "return address" pattern.

When a job is created the requester supplies a ``callback_url`` pointing at
*their* API. On completion the worker POSTs the final result there; the
receiving project is responsible for its own database write. The worker stays
stateless with respect to other projects' databases.
"""

from __future__ import annotations

import logging

import requests

from .events import JobEvent

logger = logging.getLogger(__name__)


def post_callback(callback_url: str, event: JobEvent, timeout: float = 15.0) -> bool:
    """POST a final job event to the requester's callback URL.

    Returns ``True`` on a 2xx response. Failures are logged, not raised, so a
    broken callback never crashes the worker.
    """
    if not callback_url:
        return False
    try:
        resp = requests.post(callback_url, json=event.to_dict(), timeout=timeout)
        resp.raise_for_status()
        logger.info("Callback to %s succeeded (%s)", callback_url, resp.status_code)
        return True
    except requests.RequestException as exc:
        logger.warning("Callback to %s failed: %s", callback_url, exc)
        return False
