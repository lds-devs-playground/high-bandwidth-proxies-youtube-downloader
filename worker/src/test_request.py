"""Basic tests for the proxy pool and providers (no network required)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from proxy_manager import ProxyManager
from providers import (
    DataImpulseProvider,
    SmartProxyProvider,
    WebshareProvider,
    build_manager,
)
from providers.base import build_gateway_url, normalize


def test_normalize_adds_scheme():
    assert normalize("1.2.3.4:8080") == "http://1.2.3.4:8080"
    assert normalize("http://1.2.3.4:8080") == "http://1.2.3.4:8080"


def test_smartproxy_gateway_builds_credentialed_url():
    provider = SmartProxyProvider(
        gateway="gate.smartproxy.com:7000",
        username="user",
        password="pass",
    )
    mgr = build_manager(provider)
    assert len(mgr) == 1
    assert mgr.get() == "http://user:pass@gate.smartproxy.com:7000"


def test_smartproxy_country_targeting():
    provider = SmartProxyProvider(
        gateway="gate.smartproxy.com:7000",
        username="user",
        password="pass",
    )
    assert provider.country_proxy("US") == "http://user-country-us:pass@gate.smartproxy.com:7000"
    assert provider.country_proxy("GLOBAL") == "http://user:pass@gate.smartproxy.com:7000"


def test_webshare_rotating_gateway():
    provider = WebshareProvider(username="wuser", password="wpass")
    mgr = build_manager(provider)
    assert len(mgr) == 1
    assert mgr.get() == "http://wuser:wpass@p.webshare.io:80"


def test_dataimpulse_rotating_gateway():
    provider = DataImpulseProvider(username="duser", password="dpass")
    mgr = build_manager(provider)
    assert len(mgr) == 1
    assert mgr.get() == "http://duser:dpass@gw.dataimpulse.com:823"


def test_dataimpulse_country_targeting():
    provider = DataImpulseProvider(username="duser", password="dpass")
    assert provider.country_proxy("US") == "http://duser__cr.us:dpass@gw.dataimpulse.com:823"
    assert provider.country_proxy("GLOBAL") == "http://duser:dpass@gw.dataimpulse.com:823"


def test_build_gateway_url_no_creds():
    assert build_gateway_url("host:7000", "", "") == "http://host:7000"


def test_get_returns_member():
    mgr = ProxyManager(proxies=["http://a:1", "http://b:2"])
    assert mgr.get() in {"http://a:1", "http://b:2"}


def test_failure_then_success_scoring():
    mgr = ProxyManager(proxies=["http://a:1", "http://b:2"], cooldown_seconds=0)
    mgr.report_failure("http://a:1")
    mgr.report_success("http://b:2")
    # b should be reachable and a should still exist in the pool.
    assert len(mgr) == 2
    assert mgr.get() is not None


def test_remove():
    mgr = ProxyManager(proxies=["http://a:1", "http://b:2"])
    mgr.remove("http://a:1")
    assert len(mgr) == 1
    assert mgr.get() == "http://b:2"


def test_empty_pool_returns_none():
    mgr = ProxyManager(proxies=[])
    assert mgr.get() is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok - {name}")
    print("All tests passed.")
