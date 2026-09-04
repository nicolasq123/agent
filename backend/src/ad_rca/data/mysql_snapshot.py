from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from ad_rca.agent.intent import AnalysisIntent
from ad_rca.application.scope_discovery import discover_scope
from ad_rca.data.fixture_repository import FixtureRepository
from ad_rca.domain.models import (
    CapObservation,
    MarginObservation,
    PerformanceRow,
    RoutingChange,
    ScenarioBundle,
    ScenarioMetadata,
    SettlementObservation,
    SliceKey,
)
from ad_rca.infrastructure.database.query_budget import QueryBudget

_DISCOVERY_DIMENSIONS = {
    "advertiser": "advertiser_id",
    "offer": "offer_id",
    "channel": "channel_id",
    "country": "country",
}


class NamedQueryReader(Protocol):
    async def query(
        self, name: str, parameters: Mapping[str, object]
    ) -> tuple[Mapping[str, object], ...]: ...

    async def check(self) -> None: ...


@dataclass(frozen=True)
class LoadedAnalysisSnapshot:
    intent: AnalysisIntent
    selected_scope: SliceKey
    repository: FixtureRepository


class MySqlSnapshotLoader:
    def __init__(
        self,
        stat_reader: NamedQueryReader,
        config_reader: NamedQueryReader,
        *,
        stat_timezone: str,
        query_budget: QueryBudget | None = None,
    ) -> None:
        self._stat_reader = stat_reader
        self._config_reader = config_reader
        self._stat_timezone = ZoneInfo(stat_timezone)
        self._query_budget = query_budget

    async def check(self) -> None:
        await self._stat_reader.check()
        await self._config_reader.check()

    async def load(self, intent: AnalysisIntent) -> LoadedAnalysisSnapshot:
        if self._query_budget is not None:
            self._query_budget.reset()
        history_start = intent.window.start - timedelta(weeks=8)
        common: dict[str, object] = {
            "history_start": self._database_time(history_start),
            "window_end": self._database_time(intent.window.end),
        }
        if intent.scope.depth:
            selected_scope = intent.scope
        else:
            candidate_values: dict[str, list[object]] = {}
            for query_suffix, dimension in _DISCOVERY_DIMENSIONS.items():
                rows = await self._stat_reader.query(f"scope_candidates_by_{query_suffix}", common)
                candidate_values[dimension] = [row["dimension_value"] for row in rows[:6]]

            series_by_dimension: dict[str, tuple[PerformanceRow, ...]] = {}
            for query_suffix, dimension in _DISCOVERY_DIMENSIONS.items():
                values = candidate_values[dimension]
                padding: object = "__none__" if dimension == "country" else -1
                padded = (values + [padding] * 6)[:6]
                parameters = dict(common)
                parameters.update(
                    {f"value_{index}": value for index, value in enumerate(padded, start=1)}
                )
                rows = await self._stat_reader.query(f"performance_by_{query_suffix}", parameters)
                series_by_dimension[dimension] = tuple(
                    self._map_series_row(row, dimension, intent.timezone) for row in rows
                )
            selected_scope = discover_scope(intent, series_by_dimension).selected_scope

        performance_parameters = {
            **common,
            "advertiser_id": selected_scope.advertiser_id,
            "offer_id": selected_scope.offer_id,
            "channel_id": selected_scope.channel_id,
            "country": selected_scope.country,
        }
        performance_rows = await self._stat_reader.query(
            "performance_scoped", performance_parameters
        )
        performance = tuple(
            self._map_performance_row(row, intent.timezone) for row in performance_rows
        )

        settlements, margins, caps, routing = await self._load_evidence(intent, selected_scope)
        bundle = ScenarioBundle(
            metadata=ScenarioMetadata(
                scenario_id="mysql-analysis",
                name="MySQL profit analysis",
                timezone=intent.timezone,
            ),
            performance=performance,
            settlements=settlements,
            margins=margins,
            caps=caps,
            routing_changes=routing,
        )
        return LoadedAnalysisSnapshot(
            intent=intent,
            selected_scope=selected_scope,
            repository=FixtureRepository(bundle),
        )

    async def _load_evidence(
        self, intent: AnalysisIntent, scope: SliceKey
    ) -> tuple[
        tuple[SettlementObservation, ...],
        tuple[MarginObservation, ...],
        tuple[CapObservation, ...],
        tuple[RoutingChange, ...],
    ]:
        evidence_start = intent.window.start - timedelta(minutes=30)
        scope_time: dict[str, object] = {
            "advertiser_id": scope.advertiser_id,
            "offer_id": scope.offer_id,
            "channel_id": scope.channel_id,
            "evidence_start": self._database_time(evidence_start),
            "window_end": self._database_time(intent.window.end),
        }
        settlements: tuple[SettlementObservation, ...] = ()
        margins: tuple[MarginObservation, ...] = ()
        caps: tuple[CapObservation, ...] = ()
        routing: tuple[RoutingChange, ...] = ()
        if scope.offer_id is not None or scope.channel_id is not None:
            rows = await self._config_reader.query(
                "settlement",
                {
                    key: scope_time[key]
                    for key in ("offer_id", "channel_id", "evidence_start", "window_end")
                },
            )
            settlements = tuple(self._map_settlement(row, intent.timezone) for row in rows)
        if (
            scope.advertiser_id is not None
            or scope.offer_id is not None
            or scope.channel_id is not None
        ):
            margin_rows = await self._config_reader.query("margin", scope_time)
            cap_rows = await self._config_reader.query("cap_observations", scope_time)
            routing_rows = await self._config_reader.query("routing_changes", scope_time)
            margins = tuple(self._map_margin(row, intent.timezone) for row in margin_rows)
            caps = tuple(self._map_cap(row, intent.timezone) for row in cap_rows)
            routing = tuple(self._map_routing(row, intent.timezone) for row in routing_rows)
        return settlements, margins, caps, routing

    def _map_performance_row(
        self, row: Mapping[str, object], target_timezone: str
    ) -> PerformanceRow:
        conversions = _integer(row, "conversions")
        return PerformanceRow(
            event_hour=self._time(row, "event_hour", target_timezone),
            advertiser_id=_identifier(row, "advertiser_id"),
            offer_id=_identifier(row, "offer_id"),
            channel_id=_identifier(row, "channel_id"),
            country=_text(row, "country"),
            os=_identifier(row, "clk_os"),
            carrier=_identifier(row, "carrier"),
            clicks=_integer(row, "clicks"),
            conversions=conversions,
            approved_conversions=0,
            settled_conversions=_integer(row, "settled_conversions"),
            revenue=_number(row, "revenue"),
            payout=_number(row, "payout"),
        )

    def _map_series_row(
        self, row: Mapping[str, object], dimension: str, target_timezone: str
    ) -> PerformanceRow:
        dimensions = {
            "advertiser_id": "__all__",
            "offer_id": "__all__",
            "channel_id": "__all__",
            "country": "__all__",
        }
        dimensions[dimension] = _identifier(row, "dimension_value")
        return PerformanceRow(
            event_hour=self._time(row, "event_hour", target_timezone),
            advertiser_id=dimensions["advertiser_id"],
            offer_id=dimensions["offer_id"],
            channel_id=dimensions["channel_id"],
            country=dimensions["country"],
            clicks=_integer(row, "clicks"),
            conversions=_integer(row, "conversions"),
            approved_conversions=0,
            revenue=_number(row, "revenue"),
            payout=_number(row, "payout"),
        )

    def _map_settlement(
        self, row: Mapping[str, object], target_timezone: str
    ) -> SettlementObservation:
        return SettlementObservation(
            record_id=_identifier(row, "id"),
            observed_at=self._time(row, "ut", target_timezone),
            offer_id=_identifier(row, "oid"),
            channel_id=_identifier(row, "aid"),
            payout=_number(row, "payout"),
            ratio=_integer(row, "ratio"),
            status=_integer(row, "status"),
            inactive=_integer(row, "inactive"),
        )

    def _map_margin(self, row: Mapping[str, object], target_timezone: str) -> MarginObservation:
        return MarginObservation(
            record_id=_identifier(row, "id"),
            observed_at=self._time(row, "ut", target_timezone),
            advertiser_id=_identifier(row, "ader_id"),
            offer_id=_identifier(row, "oid"),
            channel_id=_identifier(row, "aid"),
            ratio=_integer(row, "ratio2"),
            margin_type=_integer(row, "margin_type"),
            status=_integer(row, "status"),
            inactive=_integer(row, "inactive"),
        )

    def _map_cap(self, row: Mapping[str, object], target_timezone: str) -> CapObservation:
        limit = max(round(_number(row, "cap_value")), 0)
        remain = _optional_number(row, "remain")
        usage_percent = _optional_number(row, "usage_percent")
        used = max(round(limit - remain), 0) if remain is not None else 0
        event_key = "create_at" if row.get("create_at") is not None else "ut"
        return CapObservation(
            record_id=_identifier(row, "id"),
            event_time=self._time(row, event_key, target_timezone),
            offer_id=_identifier(row, "oid"),
            limit=limit,
            used=used,
            hit=row.get("create_at") is not None
            or (remain is not None and remain <= 0)
            or (usage_percent is not None and usage_percent >= 100),
        )

    def _map_routing(self, row: Mapping[str, object], target_timezone: str) -> RoutingChange:
        return RoutingChange(
            record_id=_identifier(row, "id"),
            event_time=self._time(row, "ut", target_timezone),
            channel_id=_identifier(row, "aid"),
            from_offer_id=_identifier(row, "oid"),
            to_offer_id=_identifier(row, "toid"),
        )

    def _time(self, row: Mapping[str, object], key: str, target_timezone: str) -> datetime:
        value = row.get(key)
        if not isinstance(value, datetime):
            raise ValueError(f"invalid datetime column: {key}")
        if value.tzinfo is None:
            value = value.replace(tzinfo=self._stat_timezone)
        return value.astimezone(ZoneInfo(target_timezone))

    def _database_time(self, value: datetime) -> datetime:
        return value.astimezone(self._stat_timezone).replace(tzinfo=None)


def _identifier(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"invalid identifier column: {key}")
    return str(value)


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"invalid text column: {key}")
    return value


def _integer(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"invalid integer column: {key}")
    integer = int(value)
    if integer != value:
        raise ValueError(f"invalid integer column: {key}")
    return integer


def _number(row: Mapping[str, object], key: str) -> float:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        try:
            value = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid numeric column: {key}") from error
    return float(value)


def _optional_number(row: Mapping[str, object], key: str) -> float | None:
    if row.get(key) is None:
        return None
    return _number(row, key)
