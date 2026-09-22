"""Server-side PostHog capture: no-op without a key, background POST with one, never raises."""
from __future__ import annotations

import threading

from app.services import analytics_events


def test_capture_is_noop_without_key(monkeypatch):
    calls: list = []
    monkeypatch.setattr(analytics_events.httpx, "post", lambda *a, **k: calls.append(a))
    analytics_events.capture("user-1", "email_sent", {"template": "welcome"})
    assert calls == []


def test_capture_posts_in_background(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.POSTHOG_PROJECT_KEY", "phc_test")
    done = threading.Event()
    seen: dict = {}

    class _Resp:
        status_code = 200

    def fake_post(url, json, timeout):
        seen.update(url=url, json=json, timeout=timeout)
        done.set()
        return _Resp()

    monkeypatch.setattr(analytics_events.httpx, "post", fake_post)
    analytics_events.capture("user-1", "email_sent", {"template": "welcome"})
    assert done.wait(2)
    assert seen["url"] == "https://us.i.posthog.com/i/v0/e/"
    assert seen["json"]["api_key"] == "phc_test"
    assert seen["json"]["distinct_id"] == "user-1"
    assert seen["json"]["event"] == "email_sent"
    assert seen["json"]["properties"]["template"] == "welcome"


def test_capture_never_raises(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.POSTHOG_PROJECT_KEY", "phc_test")
    done = threading.Event()

    def boom(*a, **k):
        done.set()
        raise RuntimeError("network down")

    monkeypatch.setattr(analytics_events.httpx, "post", boom)
    analytics_events.capture("user-1", "email_sent")
    assert done.wait(2)
    # Missing distinct id or event: silently skipped.
    analytics_events.capture(None, "email_sent")
    analytics_events.capture("user-1", "")
