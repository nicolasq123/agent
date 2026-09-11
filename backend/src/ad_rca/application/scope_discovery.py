from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import median

from ad_rca.agent.intent import AnalysisIntent
from ad_rca.detection.baseline import comparable_history_slots
from ad_rca.detection.metrics import aggregate_metrics
from ad_rca.domain.models import PerformanceRow, SliceKey, StrictModel

_DIMENSION_ORDER = ("advertiser_id", "country", "channel_id", "offer_id")


class NoAnalyzableDataError(RuntimeError):
    pass


class NoCurrentDataError(NoAnalyzableDataError):
    pass


class InsufficientComparableHistoryError(NoAnalyzableDataError):
    pass


class ScopeDiscovery(StrictModel):
    requested_scope: SliceKey
    selected_scope: SliceKey
    lost_profit: float
    source_dimension: str


def discover_scope(
    intent: AnalysisIntent,
    rows_by_dimension: Mapping[str, Sequence[PerformanceRow]],
) -> ScopeDiscovery:
    ranked: list[tuple[float, int, str, str]] = []
    current_data_found = False
    for dimension in _DIMENSION_ORDER:
        grouped: dict[str, list[PerformanceRow]] = defaultdict(list)
        for row in rows_by_dimension.get(dimension, ()):
            grouped[str(getattr(row, dimension))].append(row)
        for value, rows in grouped.items():
            if any(intent.window.start <= row.event_hour < intent.window.end for row in rows):
                current_data_found = True
            loss = _candidate_loss(intent, rows)
            if loss is not None:
                ranked.append((loss, _DIMENSION_ORDER.index(dimension), value, dimension))
    if not ranked:
        if not current_data_found:
            raise NoCurrentDataError("requested window contains no performance rows")
        raise InsufficientComparableHistoryError(
            "current data exists but fewer than four comparable history slots are available"
        )
    loss, _, value, dimension = min(
        ranked,
        key=lambda item: (-item[0], item[1], item[2]),
    )
    return ScopeDiscovery(
        requested_scope=intent.scope,
        selected_scope=SliceKey(**{dimension: value}),
        lost_profit=loss,
        source_dimension=dimension,
    )


def _candidate_loss(intent: AnalysisIntent, rows: Sequence[PerformanceRow]) -> float | None:
    current = [row for row in rows if intent.window.start <= row.event_hour < intent.window.end]
    history = [row for row in rows if row.event_hour < intent.window.start]
    if not current:
        return None
    expected_profit = 0.0
    actual_profit = 0.0
    for current_row in current:
        slots = comparable_history_slots(current_row.event_hour, history)
        if not slots:
            return None
        expected_profit += median(aggregate_metrics(slot).profit for slot in slots)
        actual_profit += current_row.revenue - current_row.payout
    return max(expected_profit - actual_profit, 0.0)
