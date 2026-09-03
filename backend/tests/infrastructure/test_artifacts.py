from datetime import UTC, datetime
from pathlib import Path

import pytest

from ad_rca.infrastructure.artifacts import ArtifactStore
from ad_rca.workflow.events import WorkflowEvent


def test_artifact_store_appends_and_replays_events_in_sequence(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    events = (
        WorkflowEvent(
            run_id="run-1",
            sequence=2,
            event_type="report_generated",
            occurred_at=datetime(2026, 9, 3, tzinfo=UTC),
            payload={"status": "completed"},
        ),
        WorkflowEvent(
            run_id="run-1",
            sequence=1,
            event_type="baseline_loaded",
            occurred_at=datetime(2026, 9, 3, tzinfo=UTC),
            payload={},
        ),
    )

    store.write_events("inc-1", "run-1", events)

    assert [item.sequence for item in store.read_events("run-1")] == [1, 2]
    event_file = tmp_path / "inc-1" / "run-1" / "events.jsonl"
    assert len(event_file.read_text().splitlines()) == 2


def test_artifact_store_rejects_unsafe_identifiers(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="identifier"):
        store.write_events("../escape", "run-1", ())
