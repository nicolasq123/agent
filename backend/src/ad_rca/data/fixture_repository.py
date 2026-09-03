from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from ad_rca.domain.models import (
    CapObservation,
    ConfigChange,
    ConversionEvent,
    PerformanceRow,
    PostbackEvent,
    QualityEvent,
    RoutingChange,
    ScenarioBundle,
    SliceKey,
    TimeWindow,
)


class FixtureRepository:
    def __init__(self, bundle: ScenarioBundle) -> None:
        self._bundle = bundle

    @classmethod
    def load(cls, path: Path) -> "FixtureRepository":
        return cls(ScenarioBundle.model_validate_json(path.read_bytes()))

    @property
    def scenario_id(self) -> str:
        return self._bundle.metadata.scenario_id

    @property
    def name(self) -> str:
        return self._bundle.metadata.name

    def all_performance(self) -> tuple[PerformanceRow, ...]:
        return self._bundle.performance

    def performance(self, window: TimeWindow, slice_key: SliceKey) -> tuple[PerformanceRow, ...]:
        return tuple(
            row
            for row in self._bundle.performance
            if _in_window(row.event_hour, window) and _matches(row, slice_key)
        )

    def conversion_events(
        self, window: TimeWindow, slice_key: SliceKey
    ) -> tuple[ConversionEvent, ...]:
        return _filter_events(self._bundle.conversion_events, window, slice_key)

    def postback_events(self, window: TimeWindow, slice_key: SliceKey) -> tuple[PostbackEvent, ...]:
        return _filter_events(self._bundle.postbacks, window, slice_key)

    def quality_events(self, window: TimeWindow, slice_key: SliceKey) -> tuple[QualityEvent, ...]:
        return _filter_events(self._bundle.quality_events, window, slice_key)

    def pricing_changes(self, window: TimeWindow, slice_key: SliceKey) -> tuple[ConfigChange, ...]:
        return _filter_events(self._bundle.config_changes, window, slice_key)

    def cap_observations(
        self, window: TimeWindow, slice_key: SliceKey
    ) -> tuple[CapObservation, ...]:
        return _filter_events(self._bundle.caps, window, slice_key)

    def routing_changes(self, window: TimeWindow, slice_key: SliceKey) -> tuple[RoutingChange, ...]:
        return _filter_events(self._bundle.routing_changes, window, slice_key)


def _in_window(event_time: datetime, window: TimeWindow) -> bool:
    return window.start <= event_time < window.end


def _matches(record: object, slice_key: SliceKey) -> bool:
    for name, expected in slice_key.dimensions():
        observed = getattr(record, name, None)
        if observed is not None and observed != expected:
            return False
    return True


def _filter_events[
    EventT: ConversionEvent
    | ConfigChange
    | CapObservation
    | PostbackEvent
    | QualityEvent
    | RoutingChange
](events: Iterable[EventT], window: TimeWindow, slice_key: SliceKey) -> tuple[EventT, ...]:
    return tuple(
        event
        for event in events
        if _in_window(event.event_time, window) and _matches(event, slice_key)
    )
