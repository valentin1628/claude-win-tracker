from claude_tracker.__main__ import DemoFetcher


def test_demo_is_smooth_pro_and_flagged():
    fetcher = DemoFetcher()
    a, b = fetcher.fetch(), fetcher.fetch()
    assert a.demo and b.demo
    assert a.plan == "pro"
    assert a.extras == []
    assert 0 < b.session.utilization - a.session.utilization <= 3
    assert a.session.resets_at == b.session.resets_at  # compte à rebours stable


def test_demo_wraps_around():
    fetcher = DemoFetcher()
    values = [fetcher.fetch().session.utilization for _ in range(40)]
    assert max(values) <= 100
    assert min(values) >= 5
