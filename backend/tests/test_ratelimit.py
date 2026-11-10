from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.ratelimit import SlidingWindowLimiter, parse_rate
from app.transcriber import MockTranscriber


def test_parse_rate_variants() -> None:
    assert parse_rate("20/min") == (20, 60.0)
    assert parse_rate("30/hour") == (30, 3600.0)
    assert parse_rate("5/s") == (5, 1.0)
    assert parse_rate("10 per min") == (10, 60.0)
    assert parse_rate("2:3600") == (2, 3600.0)


def test_parse_rate_invalid_falls_back() -> None:
    assert parse_rate("") == (0, 0.0)
    assert parse_rate("abc") == (0, 0.0)
    assert parse_rate("10/fortnight") == (0, 0.0)
    assert parse_rate("oops", default=(3, 60.0)) == (3, 60.0)


def test_limiter_allows_up_to_limit() -> None:
    limiter = SlidingWindowLimiter(2, 60)
    assert limiter.hit("k")[0] is True
    assert limiter.hit("k")[0] is True
    allowed, retry = limiter.hit("k")
    assert allowed is False
    assert retry > 0


def test_limiter_keys_are_independent() -> None:
    limiter = SlidingWindowLimiter(1, 60)
    assert limiter.hit("a")[0] is True
    assert limiter.hit("b")[0] is True
    assert limiter.hit("a")[0] is False


def test_limiter_disabled_when_zero() -> None:
    limiter = SlidingWindowLimiter(0, 60)
    assert limiter.enabled is False
    assert all(limiter.hit("k")[0] for _ in range(100))


def test_limiter_window_expires(monkeypatch) -> None:
    clock = {"t": 1000.0}
    monkeypatch.setattr("app.ratelimit.time.monotonic", lambda: clock["t"])
    limiter = SlidingWindowLimiter(1, 10)
    assert limiter.hit("k")[0] is True
    assert limiter.hit("k")[0] is False
    clock["t"] += 10.1
    assert limiter.hit("k")[0] is True


def test_limiter_reset() -> None:
    limiter = SlidingWindowLimiter(1, 60)
    assert limiter.hit("k")[0] is True
    assert limiter.hit("k")[0] is False
    limiter.reset()
    assert limiter.hit("k")[0] is True


def test_login_returns_429_when_limited(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EDGETAPE_RATE_LIMIT", "1")
    monkeypatch.setenv("EDGETAPE_AUTH_RATE_LIMIT", "1/hour")
    client = TestClient(create_app(tmp_path / "storage", MockTranscriber()))

    first = client.post("/api/auth/login", json={"email": "x@y.dev", "password": "nope"})
    assert first.status_code == 401

    second = client.post("/api/auth/login", json={"email": "x@y.dev", "password": "nope"})
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1
