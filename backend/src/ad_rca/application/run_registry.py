from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from threading import Condition, RLock
from time import monotonic
from typing import Literal

from ad_rca.domain.models import StrictModel
from ad_rca.workflow.events import WorkflowEvent
from ad_rca.workflow.graph import WorkflowRun


class RunHandle(StrictModel):
    run_id: str
    incident_id: str
    status: Literal["running", "completed", "failed"]


@dataclass
class _LiveRun:
    handle: RunHandle
    condition: Condition = field(default_factory=Condition)
    events: list[WorkflowEvent] = field(default_factory=lambda: list[WorkflowEvent]())
    completed: WorkflowRun | None = None
    error: str | None = None


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, _LiveRun] = {}
        self._lock = RLock()

    def start(self, handle: RunHandle) -> None:
        with self._lock:
            if handle.run_id in self._runs:
                raise ValueError(f"run already exists: {handle.run_id}")
            self._runs[handle.run_id] = _LiveRun(handle=handle)

    def publish(self, run_id: str, event: WorkflowEvent) -> None:
        live = self._require(run_id)
        with live.condition:
            live.events.append(event)
            live.condition.notify_all()

    def complete(self, run: WorkflowRun) -> None:
        live = self._require(run.run_id)
        with live.condition:
            live.completed = run
            live.handle = live.handle.model_copy(update={"status": "completed"})
            live.condition.notify_all()

    def fail(self, run_id: str, error: str) -> None:
        live = self._require(run_id)
        with live.condition:
            live.error = error
            live.handle = live.handle.model_copy(update={"status": "failed"})
            live.condition.notify_all()

    def add(self, run: WorkflowRun) -> None:
        incident = run.result.incident
        if incident is None:
            raise ValueError("cannot register a run without an incident")
        self.start(
            RunHandle(
                run_id=run.run_id,
                incident_id=incident.incident_id,
                status="running",
            )
        )
        for event in run.events:
            self.publish(run.run_id, event)
        self.complete(run)

    def get(self, run_id: str) -> WorkflowRun | None:
        with self._lock:
            live = self._runs.get(run_id)
            return None if live is None else live.completed

    def wait(self, run_id: str, timeout_seconds: float = 35.0) -> WorkflowRun:
        live = self._require(run_id)
        with live.condition:
            ready = live.condition.wait_for(
                lambda: live.completed is not None or live.error is not None,
                timeout=timeout_seconds,
            )
            if not ready:
                raise TimeoutError(f"investigation is still running: {run_id}")
            if live.error is not None:
                raise RuntimeError(live.error)
            if live.completed is None:
                raise RuntimeError("investigation finished without a result")
            return live.completed

    def stream(self, run_id: str, timeout_seconds: float = 35.0) -> Iterator[WorkflowEvent]:
        live = self._require(run_id)
        index = 0
        deadline = monotonic() + timeout_seconds
        while True:
            with live.condition:
                while index >= len(live.events) and live.completed is None and live.error is None:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f"event stream timed out: {run_id}")
                    live.condition.wait(timeout=remaining)
                pending = tuple(live.events[index:])
                index += len(pending)
                terminal = live.completed is not None or live.error is not None
            yield from pending
            if terminal and index >= len(live.events):
                if live.error is not None:
                    raise RuntimeError(live.error)
                return

    def contains(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._runs

    def _require(self, run_id: str) -> _LiveRun:
        with self._lock:
            live = self._runs.get(run_id)
        if live is None:
            raise KeyError(run_id)
        return live
