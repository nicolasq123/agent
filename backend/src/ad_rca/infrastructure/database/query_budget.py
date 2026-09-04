from threading import Lock


class QueryBudgetExceeded(RuntimeError):
    pass


class QueryBudget:
    def __init__(self, max_queries: int = 20) -> None:
        if max_queries < 1:
            raise ValueError("query budget must be positive")
        self._max_queries = max_queries
        self._used = 0
        self._lock = Lock()

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    def consume(self) -> None:
        with self._lock:
            if self._used >= self._max_queries:
                raise QueryBudgetExceeded(
                    f"query budget exceeded: maximum {self._max_queries} queries"
                )
            self._used += 1

    def reset(self) -> None:
        with self._lock:
            self._used = 0
