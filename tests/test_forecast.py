from datetime import datetime, timedelta, timezone

from claude_tracker.forecast import forecast
from claude_tracker.formatting import forecast_text

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def ramp(start_pct, per_min, minutes, step=5):
    t0 = NOW - timedelta(minutes=minutes)
    return [((t0 + timedelta(minutes=m)).timestamp(), start_pct + per_min * m) for m in range(0, minutes + 1, step)]


def test_constant_rate_gives_eta():
    # 40 % -> 70 % en 30 min (1 %/min) : encore 30 min pour atteindre 100 %.
    fc = forecast(ramp(40, 1.0, 30), 3600, NOW + timedelta(hours=3), now=NOW)
    assert fc.kind == "eta"
    assert abs((fc.at - (NOW + timedelta(minutes=30))).total_seconds()) < 60


def test_eta_after_reset_is_safe():
    fc = forecast(ramp(10, 0.1, 30), 3600, NOW + timedelta(hours=1), now=NOW)
    assert fc.kind == "safe"


def test_flat_usage_is_safe():
    fc = forecast(ramp(30, 0.0, 30), 3600, NOW + timedelta(hours=1), now=NOW)
    assert fc.kind == "safe"


def test_not_enough_points():
    assert forecast(ramp(10, 1.0, 5), 3600, NOW + timedelta(hours=1), now=NOW) is None
    assert forecast([], 3600, None, now=NOW) is None


def test_old_points_are_ignored():
    old = [(p[0] - 7200, p[1]) for p in ramp(10, 2.0, 30)]
    assert forecast(old, 3600, NOW + timedelta(hours=1), now=NOW) is None


def test_texts():
    fc = forecast(ramp(40, 1.0, 30), 3600, NOW + timedelta(hours=3), now=NOW)
    assert forecast_text(fc, now=NOW).startswith("100 % vers ")
    assert forecast_text(forecast(ramp(30, 0.0, 30), 3600, NOW + timedelta(hours=1), now=NOW)) == "tient jusqu'au reset"
    assert forecast_text(None) == ""
