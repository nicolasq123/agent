from typing import Protocol

from ad_rca.domain.models import (
    CapObservation,
    ConfigChange,
    ConversionEvent,
    PerformanceRow,
    PostbackEvent,
    QualityEvent,
    RoutingChange,
    SliceKey,
    TimeWindow,
)


class AnalyticsReader(Protocol):
    def performance(
        self, window: TimeWindow, slice_key: SliceKey
    ) -> tuple[PerformanceRow, ...]: ...

    def conversion_events(
        self, window: TimeWindow, slice_key: SliceKey
    ) -> tuple[ConversionEvent, ...]: ...

    def postback_events(
        self, window: TimeWindow, slice_key: SliceKey
    ) -> tuple[PostbackEvent, ...]: ...

    def quality_events(
        self, window: TimeWindow, slice_key: SliceKey
    ) -> tuple[QualityEvent, ...]: ...


class OperationalReader(Protocol):
    def pricing_changes(
        self, window: TimeWindow, slice_key: SliceKey
    ) -> tuple[ConfigChange, ...]: ...

    def cap_observations(
        self, window: TimeWindow, slice_key: SliceKey
    ) -> tuple[CapObservation, ...]: ...

    def routing_changes(
        self, window: TimeWindow, slice_key: SliceKey
    ) -> tuple[RoutingChange, ...]: ...
