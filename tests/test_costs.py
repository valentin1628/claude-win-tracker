import json
from datetime import datetime, timezone

import pytest

from claude_tracker import costs
from claude_tracker.formatting import cost_text, money
from claude_tracker.history import History


def line(msg_id, model="claude-opus-5-5", ts="2026-10-20T10:00:00Z", request="req_1", **usage):
    usage = {"input_tokens": 1000, "output_tokens": 500, **usage}
    return json.dumps({
        "type": "assistant", "timestamp": ts, "requestId": request,
        "message": {"id": msg_id, "model": model, "usage": usage},
    }) + "\n"


def test_price_lookup_uses_longest_prefix():
    assert costs.price_for("claude-opus-5-5").input == 4.0
    assert costs.price_for("claude-opus-5").input == 5.0
    assert costs.price_for("claude-haiku-4-5-20251001").input == 1.0
    assert costs.price_for("gpt-4") is None


def test_message_cost_with_cache():
    usage = {
        "input_tokens": 1_000_000, "output_tokens": 1_000_000,
        "cache_creation_input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000,
        "cache_creation": {"ephemeral_1h_input_tokens": 400_000},
    }
    # Opus 5.5 : 4 + 20 + 0,6M x 5 + 0,4M x 8 + 0,20 = 30,40 $
    assert costs.message_cost("claude-opus-5-5", usage) == pytest.approx(4 + 20 + 3.0 + 3.2 + 0.2)


def test_haiku_long_prompt_tier():
    short = costs.message_cost("claude-haiku-5-5", {"input_tokens": 50_000, "output_tokens": 0})
    long = costs.message_cost("claude-haiku-5-5", {"input_tokens": 200_000, "output_tokens": 0})
    assert short == pytest.approx(0.005)
    assert long == pytest.approx(0.1)


def test_scan_dedup_incremental_and_unknown(tmp_path):
    proj = tmp_path / "projects" / "mon-projet"
    proj.mkdir(parents=True)
    log = proj / "session.jsonl"
    log.write_text(
        line("msg_1") + line("msg_1")  # même réponse écrite deux fois
        + json.dumps({"type": "user", "message": {"content": "salut"}}) + "\n"
        + line("msg_2", model="<synthetic>")
        + line("msg_3", model="claude-inconnu-9", request="req_3")
    )
    tracker = costs.CostTracker(History(), projects_dir=tmp_path / "projects")
    assert tracker.scan() == 2
    assert tracker.scan() == 0  # rien de nouveau
    with open(log, "a") as fh:
        fh.write(line("msg_4", request="req_4"))
        fh.write('{"type": "assistant", "incomp')  # ligne en cours d'écriture
    assert tracker.scan() == 1
    summary = tracker.summary(now=datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc))
    per_msg = (1000 * 4 + 500 * 20) / 1_000_000
    assert summary.month == pytest.approx(2 * per_msg)
    assert summary.messages == 3
    assert summary.unknown_tokens == 1500


def test_missing_projects_dir(tmp_path):
    tracker = costs.CostTracker(History(), projects_dir=tmp_path / "absent")
    assert tracker.scan() == 0
    assert tracker.summary().messages == 0


def test_texts():
    assert money(1234.5) == "1 234,50 $"
    assert "calcul en cours" in cost_text(None)
    s = costs.CostSummary(today=1.1, month=23.4, unknown_tokens=0, messages=10)
    assert cost_text(s) == "Aujourd'hui : 1,10 $   ·   Ce mois : 23,40 $"


def test_scan_reads_in_chunks(tmp_path, monkeypatch):
    proj = tmp_path / "projects"
    proj.mkdir()
    (proj / "s.jsonl").write_text("".join(line(f"msg_{i}", request=f"r{i}") for i in range(50)))
    monkeypatch.setattr(costs.CostTracker, "CHUNK", 500)  # plus petit qu'une dizaine de lignes
    tracker = costs.CostTracker(History(), projects_dir=proj)
    assert tracker.scan() == 50
