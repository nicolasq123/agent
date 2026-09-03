from datetime import datetime, timedelta

from ad_rca.domain.models import (
    CapObservation,
    ConfigChange,
    DemoRecipe,
    PerformanceRow,
    QualityEvent,
    RoutingChange,
    ScenarioBundle,
    ScenarioMetadata,
)


def build_demo_bundle(recipe: DemoRecipe) -> ScenarioBundle:
    if recipe.kind == "pricing_error":
        history = _history(recipe, (_spec("offer-a", "channel-c", 1000, 100, 90, 1000, 600),))
        current = _current(recipe, (_spec("offer-a", "channel-c", 1000, 100, 90, 1000, 900),))
        return _bundle(
            recipe,
            history + current,
            config_changes=(
                ConfigChange(
                    record_id="change-payout-1",
                    event_time=recipe.start - timedelta(minutes=15),
                    entity_type="offer",
                    entity_id="offer-a",
                    field_name="payout_per_conversion",
                    old_value=6.0,
                    new_value=9.0,
                ),
            ),
        )
    if recipe.kind == "cap_mix_shift":
        history_specs = (
            _spec("offer-high", "channel-c", 800, 80, 72, 800, 400),
            _spec("offer-low", "channel-c", 200, 20, 18, 200, 180),
        )
        current_specs = (
            _spec("offer-high", "channel-c", 200, 20, 18, 200, 100),
            _spec("offer-low", "channel-c", 800, 80, 72, 800, 720),
        )
        return _bundle(
            recipe,
            _history(recipe, history_specs) + _current(recipe, current_specs),
            caps=(
                CapObservation(
                    record_id="cap-hit-1",
                    event_time=recipe.start,
                    offer_id="offer-high",
                    limit=100,
                    used=100,
                    hit=True,
                ),
            ),
            routing_changes=(
                RoutingChange(
                    record_id="route-1",
                    event_time=recipe.start,
                    channel_id="channel-c",
                    from_offer_id="offer-high",
                    to_offer_id="offer-low",
                ),
            ),
        )
    if recipe.kind == "traffic_quality":
        history = _history(recipe, (_spec("offer-a", "channel-risk", 1000, 100, 90, 900, 500),))
        current = _current(recipe, (_spec("offer-a", "channel-risk", 1000, 100, 50, 500, 450),))
        signals = (
            QualityEvent(
                record_id="quality-short-ctit",
                event_time=recipe.start,
                channel_id="channel-risk",
                signal_type="short_ctit_rate",
                signal_value=0.30,
                adjudicated=False,
            ),
            QualityEvent(
                record_id="quality-duplicate-ip",
                event_time=recipe.start,
                channel_id="channel-risk",
                signal_type="duplicate_ip_rate",
                signal_value=0.25,
                adjudicated=False,
            ),
        )
        return _bundle(recipe, history + current, quality_events=signals)
    raise ValueError(f"unsupported demo recipe kind: {recipe.kind}")


def _spec(
    offer: str,
    channel: str,
    clicks: int,
    conversions: int,
    approved: int,
    revenue: float,
    payout: float,
) -> tuple[str, str, int, int, int, float, float]:
    return offer, channel, clicks, conversions, approved, revenue, payout


def _history(
    recipe: DemoRecipe,
    specs: tuple[tuple[str, str, int, int, int, float, float], ...],
) -> tuple[PerformanceRow, ...]:
    return tuple(
        _row(recipe.start + timedelta(hours=hour) - timedelta(weeks=week), spec)
        for week in range(1, recipe.history_weeks + 1)
        for hour in range(3)
        for spec in specs
    )


def _current(
    recipe: DemoRecipe,
    specs: tuple[tuple[str, str, int, int, int, float, float], ...],
) -> tuple[PerformanceRow, ...]:
    return tuple(
        _row(recipe.start + timedelta(hours=hour), spec) for hour in range(3) for spec in specs
    )


def _row(
    event_hour: datetime, spec: tuple[str, str, int, int, int, float, float]
) -> PerformanceRow:
    offer, channel, clicks, conversions, approved, revenue, payout = spec
    return PerformanceRow(
        event_hour=event_hour,
        advertiser_id="adv-1",
        offer_id=offer,
        channel_id=channel,
        country="US",
        clicks=clicks,
        conversions=conversions,
        approved_conversions=approved,
        revenue=revenue,
        payout=payout,
    )


def _bundle(
    recipe: DemoRecipe, performance: tuple[PerformanceRow, ...], **events: object
) -> ScenarioBundle:
    payload = {
        "metadata": ScenarioMetadata(
            scenario_id=recipe.scenario_id, name=recipe.name, timezone="UTC"
        ),
        "performance": performance,
        **events,
    }
    return ScenarioBundle.model_validate(payload)
