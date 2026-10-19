from datetime import datetime, timedelta, timezone

from claude_tracker.history import History
from claude_tracker.usage_client import UsageSnapshot, UsageWindow

RESET = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)


def snap(pct, at, reset=RESET, weekly=None):
    windows = {"five_hour": UsageWindow("five_hour", "Session 5h", pct, reset)}
    if weekly is not None:
        windows["seven_day"] = UsageWindow("seven_day", "Semaine", weekly, RESET + timedelta(days=4))
    return UsageSnapshot(windows=windows, fetched_at=at)


def test_duplicates_are_skipped_but_kept_every_15_min():
    h = History()
    t0 = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    for minutes in (0, 5, 10, 16):
        h.record(snap(20, t0 + timedelta(minutes=minutes)))
    h.record(snap(25, t0 + timedelta(minutes=20)))
    values = [round((ts - t0.timestamp()) / 60) for ts, _ in h.series("five_hour", 0)]
    assert values == [0, 16, 20]


def test_window_samples_only_current_window():
    h = History()
    t0 = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    h.record(snap(80, t0, reset=RESET - timedelta(hours=5)))
    h.record(snap(10, t0 + timedelta(minutes=30)))
    h.record(snap(15, t0 + timedelta(minutes=40), reset=RESET + timedelta(seconds=3)))
    assert [u for _, u in h.window_samples("five_hour", RESET)] == [10, 15]


def test_daily_increase_handles_resets():
    h = History()
    day = datetime(2026, 10, 20, 9, 0).astimezone()
    old_reset = RESET - timedelta(days=7)
    h.record(UsageSnapshot(windows={"seven_day": UsageWindow("seven_day", "Semaine", 50, old_reset)},
                           fetched_at=day))
    # Reset de la semaine : on repart de 0, les 4 % affichés comptent pour la journée.
    h.record(UsageSnapshot(windows={"seven_day": UsageWindow("seven_day", "Semaine", 4, RESET)},
                           fetched_at=day + timedelta(hours=1)))
    h.record(UsageSnapshot(windows={"seven_day": UsageWindow("seven_day", "Semaine", 10, RESET)},
                           fetched_at=day + timedelta(hours=2)))
    h.record(UsageSnapshot(windows={"seven_day": UsageWindow("seven_day", "Semaine", 9, RESET)},
                           fetched_at=day + timedelta(hours=3)))  # petite baisse : ignorée
    days = dict(h.daily_increase("seven_day", 7, now=day + timedelta(hours=4)))
    assert days[day.date()] == 10
    assert len(days) == 7


def test_file_database(tmp_path):
    path = tmp_path / "sub" / "history.db"
    h = History(path)
    h.record(snap(5, datetime.now(timezone.utc)))
    h.close()
    assert len(History(path).series("five_hour", 0)) == 1
