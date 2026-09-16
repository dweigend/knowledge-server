import json
from pathlib import Path

import pytest

from knowledge.knowledge_domain.application_errors import Missing
from knowledge.web_interface.fastapi_app import read_run_events


def test_run_log_reads_nested_events_but_rejects_paths_outside_runs(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "experiment"
    nested = run / "source"
    nested.mkdir(parents=True)
    (run / "events.jsonl").write_text(json.dumps({"time": "2", "event": "finished"}))
    (nested / "events.jsonl").write_text(json.dumps({"time": "1", "event": "started"}))
    events = read_run_events(tmp_path / "runs", "experiment")
    assert [event["event"] for event in events] == ["started", "finished"]
    with pytest.raises(Missing):
        read_run_events(tmp_path / "runs", "../")
