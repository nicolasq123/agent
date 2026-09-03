from threading import RLock

from ad_rca.workflow.graph import WorkflowRun


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, WorkflowRun] = {}
        self._lock = RLock()

    def add(self, run: WorkflowRun) -> None:
        with self._lock:
            if run.run_id in self._runs:
                raise ValueError(f"run already exists: {run.run_id}")
            self._runs[run.run_id] = run

    def get(self, run_id: str) -> WorkflowRun | None:
        with self._lock:
            return self._runs.get(run_id)
